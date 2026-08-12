from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]


def _load_module() -> ModuleType:
    path = REPO_ROOT / "scripts/automation/configure-vscode-profile.py"
    spec = importlib.util.spec_from_file_location("configure_vscode_profile", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_repository_profile_artifacts_are_consistent() -> None:
    module = _load_module()

    extension_count, setting_count = module.validate_artifacts()

    assert extension_count == 18
    assert setting_count == 6

    machine_settings = module._read_json(module.MACHINE_TEMPLATE_PATH)
    assert "python.analysis.nodeArguments" not in machine_settings
    assert "python.analysis.nodeExecutable" not in machine_settings

    profile = module._read_json(module.PROFILE_PATH)
    profile_settings = module._profile_settings(profile)
    assert "python.analysis.nodeArguments" not in profile_settings
    assert "python.analysis.nodeExecutable" not in profile_settings


def test_read_json_rejects_duplicate_keys(tmp_path: Path) -> None:
    module = _load_module()
    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text('{"settings": 1, "settings": 2}', encoding="utf-8")

    with pytest.raises(module.ProfileContractError, match="duplicate JSON key: settings"):
        module._read_json(duplicate)


def test_repository_profile_rejects_pylance_machine_settings(tmp_path: Path) -> None:
    module = _load_module()
    vscode_dir = tmp_path / ".vscode"
    vscode_dir.mkdir()
    for source in (
        module.EXTENSIONS_PATH,
        module.PROFILE_PATH,
        module.MACHINE_TEMPLATE_PATH,
    ):
        (vscode_dir / source.name).write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    profile_path = vscode_dir / module.PROFILE_PATH.name
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    settings = json.loads(profile["settings"])
    settings["python.analysis.nodeExecutable"] = "auto"
    profile["settings"] = json.dumps(settings)
    profile_path.write_text(json.dumps(profile), encoding="utf-8")

    with pytest.raises(
        module.ProfileContractError,
        match="Remote WSL Pylance machine settings cannot be isolated by profile",
    ):
        module.validate_artifacts(vscode_dir)


def test_profile_extensions_reject_export_metadata() -> None:
    module = _load_module()
    profile = {
        "extensions": json.dumps(
            [
                {
                    "identifier": {"id": "example.extension", "uuid": "local-only"},
                    "version": "1.0.0",
                }
            ]
        )
    }

    with pytest.raises(module.ProfileContractError, match="only identifier"):
        module._profile_extensions(profile)


def test_machine_settings_reject_terraform_ls_reserved_ignore_names() -> None:
    module = _load_module()

    with pytest.raises(module.ProfileContractError, match="reserved ignore directory"):
        module._validate_machine_settings(
            {"terraform.languageServer.indexing.ignoreDirectoryNames": [".terraform"]}
        )


def test_apply_machine_settings_preserves_existing_values_and_is_idempotent(
    tmp_path: Path,
) -> None:
    module = _load_module()
    template = tmp_path / "template.json"
    destination = tmp_path / "Machine" / "settings.json"
    template.write_text(json.dumps({"terraform.ignore": ["node_modules"]}), encoding="utf-8")
    destination.parent.mkdir()
    destination.write_text(json.dumps({"chat.enabled": True}), encoding="utf-8")

    assert module.apply_machine_settings(destination, template) is True
    assert json.loads(destination.read_text(encoding="utf-8")) == {
        "chat.enabled": True,
        "terraform.ignore": ["node_modules"],
    }
    assert module.apply_machine_settings(destination, template) is False
    assert module.machine_settings_match(destination, template) is True


def test_apply_machine_settings_fails_closed_on_jsonc(tmp_path: Path) -> None:
    module = _load_module()
    template = tmp_path / "template.json"
    destination = tmp_path / "settings.json"
    template.write_text(json.dumps({"terraform.ignore": []}), encoding="utf-8")
    original = '{\n  // keep this comment\n  "chat.enabled": true\n}\n'
    destination.write_text(original, encoding="utf-8")

    with pytest.raises(module.ProfileContractError, match="cannot read JSON"):
        module.apply_machine_settings(destination, template)

    assert destination.read_text(encoding="utf-8") == original


def test_apply_profile_settings_preserves_local_values_and_is_idempotent(
    tmp_path: Path,
) -> None:
    module = _load_module()
    profile = tmp_path / "fdai.code-profile"
    destination = tmp_path / "profiles" / "fdai" / "settings.json"
    profile.write_text(
        json.dumps(
            {
                "settings": json.dumps(
                    {
                        "python.analysis.nodeArguments": ["--max-old-space-size=2048"],
                        "python.analysis.nodeExecutable": "auto",
                    }
                )
            }
        ),
        encoding="utf-8",
    )
    destination.parent.mkdir(parents=True)
    destination.write_text(json.dumps({"chat.agent.maxRequests": 9999}), encoding="utf-8")

    assert module.apply_profile_settings(destination, profile) is True
    assert json.loads(destination.read_text(encoding="utf-8")) == {
        "chat.agent.maxRequests": 9999,
        "python.analysis.nodeArguments": ["--max-old-space-size=2048"],
        "python.analysis.nodeExecutable": "auto",
    }
    assert module.apply_profile_settings(destination, profile) is False
    assert module.profile_settings_match(destination, profile) is True
