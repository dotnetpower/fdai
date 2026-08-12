#!/usr/bin/env python3
"""Validate and apply the shared FDAI VS Code profile contract."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
VSCODE_DIR = REPO_ROOT / ".vscode"
EXTENSIONS_PATH = VSCODE_DIR / "extensions.json"
PROFILE_PATH = VSCODE_DIR / "fdai.code-profile"
MACHINE_TEMPLATE_PATH = VSCODE_DIR / "fdai.machine-settings.json"
UNWANTED_TERRAFORM_EXTENSION = "ms-azuretools.vscode-azureterraform"
TERRAFORM_LS_RESERVED_IGNORE_DIRECTORY_NAMES = frozenset({".terraform"})


class ProfileContractError(ValueError):
    """Raised when a shared VS Code profile artifact is inconsistent."""


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ProfileContractError(f"cannot read JSON from {path}: {error}") from error


def _string_set(values: object, *, label: str) -> set[str]:
    if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
        raise ProfileContractError(f"{label} must be an array of strings")
    normalized = {value.lower() for value in values}
    if len(normalized) != len(values):
        raise ProfileContractError(f"{label} contains duplicate extension ids")
    return normalized


def _profile_extensions(profile: dict[str, object]) -> set[str]:
    serialized = profile.get("extensions")
    if not isinstance(serialized, str):
        raise ProfileContractError("profile extensions must be a JSON string")
    try:
        extensions = json.loads(serialized)
    except json.JSONDecodeError as error:
        raise ProfileContractError(f"profile extensions are invalid JSON: {error}") from error
    if not isinstance(extensions, list):
        raise ProfileContractError("profile extensions must decode to an array")

    identifiers: list[str] = []
    for extension in extensions:
        if not isinstance(extension, dict):
            raise ProfileContractError("profile extension entries must be objects")
        if set(extension) != {"identifier"}:
            raise ProfileContractError("profile extension entries may contain only identifier")
        identifier = extension.get("identifier")
        if isinstance(identifier, dict) and set(identifier) != {"id"}:
            raise ProfileContractError("profile identifiers may contain only id")
        extension_id = identifier.get("id") if isinstance(identifier, dict) else None
        if not isinstance(extension_id, str):
            raise ProfileContractError("profile extension entries require identifier.id")
        identifiers.append(extension_id)
    return _string_set(identifiers, label="profile extensions")


def _profile_settings(profile: dict[str, object]) -> dict[str, object]:
    serialized = profile.get("settings")
    if not isinstance(serialized, str):
        raise ProfileContractError("profile settings must be a JSON string")
    try:
        settings = json.loads(serialized)
    except json.JSONDecodeError as error:
        raise ProfileContractError(f"profile settings are invalid JSON: {error}") from error
    if not isinstance(settings, dict):
        raise ProfileContractError("profile settings must decode to an object")
    return settings


def _validate_machine_settings(settings: dict[str, object]) -> None:
    key = "terraform.languageServer.indexing.ignoreDirectoryNames"
    ignored_names = _string_set(settings.get(key), label=key)
    reserved_names = sorted(ignored_names & TERRAFORM_LS_RESERVED_IGNORE_DIRECTORY_NAMES)
    if reserved_names:
        raise ProfileContractError(
            f"terraform-ls reserved ignore directory names are not configurable: {reserved_names}"
        )


def validate_artifacts(vscode_dir: Path = VSCODE_DIR) -> tuple[int, int]:
    extensions_path = vscode_dir / EXTENSIONS_PATH.name
    profile_path = vscode_dir / PROFILE_PATH.name
    machine_template_path = vscode_dir / MACHINE_TEMPLATE_PATH.name
    extension_config = _read_json(extensions_path)
    profile = _read_json(profile_path)
    machine_template = _read_json(machine_template_path)
    if not isinstance(extension_config, dict) or not isinstance(profile, dict):
        raise ProfileContractError("extension config and profile must be JSON objects")
    if not isinstance(machine_template, dict):
        raise ProfileContractError("machine settings template must be a JSON object")
    _validate_machine_settings(machine_template)
    if profile.get("name") != "FDAI":
        raise ProfileContractError("profile name must be FDAI")

    recommendations = _string_set(
        extension_config.get("recommendations"), label="extension recommendations"
    )
    unwanted = _string_set(
        extension_config.get("unwantedRecommendations"),
        label="unwanted extension recommendations",
    )
    profile_extensions = _profile_extensions(profile)
    if recommendations != profile_extensions:
        missing = sorted(recommendations - profile_extensions)
        extra = sorted(profile_extensions - recommendations)
        raise ProfileContractError(f"profile extension drift: missing={missing}, extra={extra}")
    if recommendations & unwanted:
        raise ProfileContractError("recommended and unwanted extension sets overlap")
    if UNWANTED_TERRAFORM_EXTENSION not in unwanted:
        raise ProfileContractError("Microsoft Terraform must remain an unwanted recommendation")

    settings = _profile_settings(profile)
    profile_machine_settings = {key: settings.get(key) for key in machine_template}
    if profile_machine_settings != machine_template:
        raise ProfileContractError("profile and machine settings template have drifted")
    serialized_profile = json.dumps(profile).lower()
    forbidden_tokens = (
        "api://",
        "azure_config_dir",
        "fdai_operator_api",
        "subscription_id",
        "tenant_id",
    )
    leaked = [token for token in forbidden_tokens if token in serialized_profile]
    if leaked:
        raise ProfileContractError(f"profile contains runtime or identity settings: {leaked}")
    return len(recommendations), len(settings)


def default_machine_settings_path() -> Path:
    override = os.environ.get("VSCODE_MACHINE_SETTINGS")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".vscode-server" / "data" / "Machine" / "settings.json"


def machine_settings_match(destination: Path, template: Path = MACHINE_TEMPLATE_PATH) -> bool:
    if not destination.is_file():
        return False
    current = _read_json(destination)
    expected = _read_json(template)
    if not isinstance(current, dict) or not isinstance(expected, dict):
        raise ProfileContractError("machine settings must be JSON objects")
    return all(current.get(key) == value for key, value in expected.items())


def apply_machine_settings(destination: Path, template: Path = MACHINE_TEMPLATE_PATH) -> bool:
    expected = _read_json(template)
    if not isinstance(expected, dict):
        raise ProfileContractError("machine settings template must be a JSON object")
    if destination.exists():
        current = _read_json(destination)
        if not isinstance(current, dict):
            raise ProfileContractError("existing machine settings must be a JSON object")
    else:
        current = {}
    merged = {**current, **expected}
    if merged == current:
        return False

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.tmp")
    temporary.write_text(json.dumps(merged, ensure_ascii=False, indent=4) + "\n", encoding="utf-8")
    temporary.chmod(destination.stat().st_mode & 0o777 if destination.exists() else 0o600)
    temporary.replace(destination)
    return True


def profile_settings_match(destination: Path, profile_path: Path = PROFILE_PATH) -> bool:
    if not destination.is_file():
        return False
    current = _read_json(destination)
    profile = _read_json(profile_path)
    if not isinstance(current, dict) or not isinstance(profile, dict):
        raise ProfileContractError("profile settings and profile must be JSON objects")
    expected = _profile_settings(profile)
    return all(current.get(key) == value for key, value in expected.items())


def apply_profile_settings(destination: Path, profile_path: Path = PROFILE_PATH) -> bool:
    profile = _read_json(profile_path)
    if not isinstance(profile, dict):
        raise ProfileContractError("profile must be a JSON object")
    expected = _profile_settings(profile)
    if destination.exists():
        current = _read_json(destination)
        if not isinstance(current, dict):
            raise ProfileContractError("existing profile settings must be a JSON object")
    else:
        current = {}
    merged = {**current, **expected}
    if merged == current:
        return False

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.tmp")
    temporary.write_text(json.dumps(merged, ensure_ascii=False, indent=4) + "\n", encoding="utf-8")
    temporary.chmod(destination.stat().st_mode & 0o777 if destination.exists() else 0o600)
    temporary.replace(destination)
    return True


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply-machine-settings",
        action="store_true",
        help="merge the shared machine settings into the VS Code remote settings file",
    )
    parser.add_argument(
        "--check-machine-settings",
        action="store_true",
        help="fail when the VS Code remote machine settings do not match the template",
    )
    parser.add_argument(
        "--machine-settings",
        type=Path,
        help=(
            "override the machine settings destination (also available via VSCODE_MACHINE_SETTINGS)"
        ),
    )
    parser.add_argument(
        "--apply-profile-settings",
        action="store_true",
        help="merge the portable FDAI settings into an existing profile settings file",
    )
    parser.add_argument(
        "--check-profile-settings",
        action="store_true",
        help="fail when a profile settings file does not contain the portable FDAI settings",
    )
    parser.add_argument(
        "--profile-settings",
        type=Path,
        help="existing FDAI profile settings destination",
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        extension_count, setting_count = validate_artifacts()
        print(f"profile artifacts valid: extensions={extension_count} settings={setting_count}")
        destination = args.machine_settings or default_machine_settings_path()
        if args.apply_machine_settings:
            changed = apply_machine_settings(destination)
            state = "updated" if changed else "already current"
            print(f"machine settings {state}: {destination}")
        if args.check_machine_settings:
            if not machine_settings_match(destination):
                raise ProfileContractError(
                    f"machine settings do not match {MACHINE_TEMPLATE_PATH}: {destination}"
                )
            print(f"machine settings current: {destination}")
        if args.apply_profile_settings or args.check_profile_settings:
            if args.profile_settings is None:
                raise ProfileContractError("--profile-settings is required for profile operations")
            if args.apply_profile_settings:
                changed = apply_profile_settings(args.profile_settings)
                state = "updated" if changed else "already current"
                print(f"profile settings {state}: {args.profile_settings}")
            if args.check_profile_settings:
                if not profile_settings_match(args.profile_settings):
                    raise ProfileContractError(
                        f"profile settings do not match {PROFILE_PATH}: {args.profile_settings}"
                    )
                print(f"profile settings current: {args.profile_settings}")
    except ProfileContractError as error:
        print(f"profile configuration error: {error}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
