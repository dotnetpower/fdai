"""Resolve immutable support source only after the existing signed Hub verification."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from uuid import UUID

from fdai_deployment_cli.hub_image_deploy import DEFAULT_HUB_URL, hub_request
from fdai_deployment_cli.hub_image_trust import (
    MAX_SELECTION_BYTES,
    HubImageSelection,
    load_selection,
    selection_bytes,
    verify_export,
)
from fdai_deployment_cli.private_output import write_private_bytes
from fdai_deployment_cli.source_input import inspect_source

OFFICIAL_SOURCE = "https://github.com/dotnetpower/fdai.git"
_SYNC_FILES = (
    "azureProfile.json",
    "msal_token_cache.json",
    "msal_token_cache.bin",
    "clouds.config",
    "config",
    "msal_http_cache.bin",
)


def configure_wsl_browser(area: Path, environment: dict[str, str]) -> None:
    """Provide a PowerShell browser helper on WSL when wslview is not installed."""
    configured = environment.get("BROWSER", "").split(":", 1)[0].strip()
    if (
        (not configured or shutil.which(configured) is None)
        and ("WSL_DISTRO_NAME" in os.environ or "WSL_INTEROP" in os.environ)
        and shutil.which("wslview") is None
        and shutil.which("powershell.exe") is not None
    ):
        helper = area / "open-browser.sh"
        if helper.is_symlink():
            raise ValueError("Bootstrap browser helper must not be a symlink.")
        fd = os.open(helper, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o700)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(
                "#!/bin/sh\n"
                "exec powershell.exe -NoProfile -NonInteractive "
                "-Command \"Start-Process '$1'\" >/dev/null 2>&1\n"
            )
        environment["BROWSER"] = str(helper)


def default_profile_subscription_and_tenant(azure_dir: Path) -> tuple[str | None, str | None]:
    """Read the default enabled subscription and tenant from azureProfile.json."""
    profile = azure_dir / "azureProfile.json"
    try:
        raw = (
            json.loads(profile.read_bytes().decode("utf-8-sig"))
            if profile.is_file() and not profile.is_symlink()
            else None
        )
    except (OSError, ValueError):
        return None, None
    for item in raw.get("subscriptions", []) if isinstance(raw, dict) else []:
        if isinstance(item, dict) and item.get("isDefault") and item.get("state") == "Enabled":
            try:
                return str(UUID(str(item["id"]))), str(UUID(str(item["tenantId"])))
            except (ValueError, KeyError, TypeError):
                continue
    return None, None


def sync_local_azure_profile(source_azure: Path, target_azure: Path) -> None:
    """Seed or refresh the executor's private Azure CLI cache from the operator's local profile."""
    try:
        if (
            not source_azure.is_dir()
            or source_azure.is_symlink()
            or source_azure.resolve() == target_azure.resolve()
        ):
            return
    except OSError:
        return
    uid = os.getuid()
    dst_empty = default_profile_subscription_and_tenant(target_azure) == (None, None)
    for name in _SYNC_FILES:
        src, dst = source_azure / name, target_azure / name
        try:
            if not src.is_file() or src.is_symlink() or dst.is_symlink():
                continue
            info = src.stat()
            if info.st_uid != uid or not (0 < info.st_size <= 4 * 1024 * 1024):
                continue
            if dst.exists() and not dst_empty and info.st_mtime_ns <= dst.stat().st_mtime_ns:
                continue
            fd = os.open(dst, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, "wb") as stream:
                stream.write(src.read_bytes())
        except OSError:
            continue


def resolve_hub_source(
    area: Path, pem: str, supplied: str | None
) -> tuple[Path, HubImageSelection]:
    """Fetch one verified content-addressed commit, never branches or executing hooks."""
    selection_path = area / "deployment/hub-images/selection.json"
    if selection_path.exists():
        from fdai_deployment_cli.private_output import read_private_bytes

        raw = read_private_bytes(selection_path, max_bytes=MAX_SELECTION_BYTES)
        selection = load_selection(selection_path, hashlib.sha256(raw).hexdigest())
        if (
            selection.document["public_key"] != pem
            or selection.document["hub_url"] != DEFAULT_HUB_URL
        ):
            raise ValueError("Retained Hub trust changed")
        # Refresh the signed catalog, recall and expiry using the existing immutable selection seam.
        from fdai_deployment_cli.hub_image_deploy import prepare_hub_selection

        source = Path(supplied) if supplied else area / "support-source"
        key_path = area / "hub-public.pem"
        if not key_path.exists():
            write_private_bytes(key_path, pem.encode())
        elif key_path.is_symlink() or key_path.read_bytes() != pem.encode():
            raise ValueError("Retained Hub public key changed")
        selection = prepare_hub_selection(
            source_root=source,
            work_dir=area / "deployment",
            public_key_path=key_path,
        )
        return source, selection
    _, headers, raw = hub_request(DEFAULT_HUB_URL, "/v1/catalog/export")
    verified = verify_export(
        raw,
        signature=headers["x-fdai-export-signature"],
        export_key_id=headers["x-fdai-export-key-id"],
        trusted_pem=pem.encode(),
        channel="RELEASE",
        release_id=None,
    )
    commit = verified["source_commit"]
    if not isinstance(commit, str) or re.fullmatch(r"[a-f0-9]{40}", commit) is None:
        raise ValueError("Signed support source commit is invalid")
    source = Path(supplied).absolute() if supplied else area / "support-source"
    if supplied is None:
        if source.exists():
            inspect_source(source, expected_commit=commit)
            deployment = area / "deployment"
            if deployment.exists() and any(deployment.iterdir()):
                raise ValueError("Hub support cannot adopt partial or source deployment state")
            deployment.mkdir(mode=0o700, exist_ok=True)
        else:
            source.mkdir(mode=0o700)
            commands = (
                ("git", "init", "--quiet", str(source)),
                (
                    "git",
                    "-C",
                    str(source),
                    "-c",
                    "core.hooksPath=/dev/null",
                    "fetch",
                    "--quiet",
                    "--depth=1",
                    "--no-tags",
                    OFFICIAL_SOURCE,
                    commit,
                ),
                (
                    "git",
                    "-C",
                    str(source),
                    "-c",
                    "core.hooksPath=/dev/null",
                    "checkout",
                    "--quiet",
                    "--detach",
                    commit,
                ),
            )
            import os

            environment = {
                key: value
                for key, value in os.environ.items()
                if key in {"PATH", "HOME", "SSL_CERT_FILE", "REQUESTS_CA_BUNDLE"}
            }
            environment.update(
                GIT_CONFIG_GLOBAL=os.devnull,
                GIT_CONFIG_NOSYSTEM="1",
                GIT_TERMINAL_PROMPT="0",
            )
            for command in commands:
                result = subprocess.run(
                    command,
                    stdin=subprocess.DEVNULL,
                    capture_output=True,
                    timeout=300,
                    check=False,
                    env=environment,
                )
                if result.returncode:
                    raise ValueError("Pinned official support source retrieval failed; no fallback")
    inspect_source(source, expected_commit=commit)
    selected = selection_bytes(
        raw=raw,
        signature=headers["x-fdai-export-signature"],
        export_key_id=headers["x-fdai-export-key-id"],
        pem=pem.encode(),
        hub_url=DEFAULT_HUB_URL,
        channel="RELEASE",
        verified=verified,
    )
    selection_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    write_private_bytes(selection_path, selected)
    return source, load_selection(selection_path, hashlib.sha256(selected).hexdigest())
