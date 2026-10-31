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


def select_available_workload(area: Path, region: str, query_groups: object) -> str:
    """Select 'fdai' or the first non-colliding workload token in the target region."""
    variables = area / "deployment/foundation/foundation-variables.json"
    if variables.is_file() and not variables.is_symlink():
        try:
            retained = json.loads(variables.read_bytes().decode("utf-8")).get("workload")
            if isinstance(retained, str) and re.fullmatch(r"[a-z][a-z0-9]{1,11}", retained):
                return retained
        except (OSError, ValueError):
            pass
    from fdai_deployment_cli.azure_naming import azure_region_short_name

    try:
        short = azure_region_short_name(region)
    except ValueError:
        return "fdai"
    if not isinstance(query_groups, list):
        return "fdai"
    existing = {
        str(item.get("name", "")).lower() for item in query_groups if isinstance(item, dict)
    }
    for candidate in ("fdai", "fdaiboot", "fdaiboot2", "fdaiboot3", "fdaiboot4", "fdaiboot5"):
        if (
            f"rg-{candidate}-ops-{short}" not in existing
            and f"rg-{candidate}-dev-{short}" not in existing
        ):
            return candidate
    raise ValueError(
        f"Existing FDAI resource groups already occupy region '{region}'. "
        "Choose another Azure region or remove unused test resource groups first."
    )


def format_nonready_message(result: dict[str, object]) -> str:
    """Format an actionable blocker message when plan_source_installation stops before ready."""
    if result.get("stage") == "aks-preflight":
        blockers = result.get("blockers")
        region = result.get("region", "")
        if isinstance(blockers, list) and blockers:
            joined = ", ".join(str(item) for item in blockers)
            return (
                f"Azure region '{region}' preflight blocked ({joined}). "
                "Reset setup and choose a region with available VM SKU/quota (such as westus3)."
            )
    if result.get("state") == "blocked" and isinstance(result.get("reason"), str):
        return f"Preparation blocked ({result['reason']}). Reset setup to adjust inputs."
    return "Installation is not accepted. Inspect retained private evidence before resuming."


def can_open_interactive_browser(environment: dict[str, str]) -> bool:
    """Return True if this host environment can open an interactive local or WSL browser."""
    configured = environment.get("BROWSER", "").split(":", 1)[0].strip()
    if configured and shutil.which(configured) is not None:
        return True
    if ("WSL_DISTRO_NAME" in environment or "WSL_INTEROP" in environment) and (
        shutil.which("wslview") is not None or shutil.which("powershell.exe") is not None
    ):
        return True
    if environment.get("DISPLAY") or environment.get("WAYLAND_DISPLAY"):
        for binary in ("x-www-browser", "firefox", "google-chrome", "chromium", "chromium-browser"):
            if shutil.which(binary) is not None:
                return True
    return False


def latest_progress_message(root: Path, current: str) -> str:
    """Extract a safe, human-readable stage progress summary from engine-trace.log."""
    trace = root / "executor/engine-trace.log"
    try:
        if not trace.is_file() or trace.is_symlink():
            return current
        raw = trace.read_bytes()[-8192:].decode("utf-8", errors="replace")
    except OSError:
        return current
    device_match = re.search(
        r"(https://microsoft\.com/devicelogin)[^\n]*?\b([A-Z0-9]{8,12})\b", raw
    )
    if device_match:
        return (
            f"Device code sign-in: open {device_match.group(1)} "
            f"and enter code {device_match.group(2)} to authenticate."
        )
    stage_line = ""
    elapsed = ""
    detail_line = ""
    for line in raw.splitlines():
        clean = line.strip()
        if clean.startswith("==> [") and "|" in clean:
            parts = [part.strip() for part in clean.removeprefix("==>").split("|")]
            stage_line = f"{parts[0]} ({parts[2]})" if len(parts) >= 3 else parts[0]
            elapsed = ""
        elif clean.startswith(".. still running | elapsed"):
            elapsed = clean.split("elapsed", 1)[-1].strip()
        elif clean.startswith("=> "):
            detail_line = clean.removeprefix("=> ").strip()
            elapsed = ""
        elif clean.startswith("[..] ") and "|" in clean:
            parts = [part.strip() for part in clean.removeprefix("[..]").split("|")]
            detail_line = parts[0]
            if len(parts) >= 2 and "elapsed" in parts[1]:
                elapsed = parts[1].replace("elapsed", "").strip()
        elif line.startswith("      ") and len(clean) <= 120 and not stage_line:
            detail_line = clean
    if stage_line:
        return f"{stage_line} - elapsed {elapsed}" if elapsed else stage_line
    if detail_line:
        return f"{detail_line} - elapsed {elapsed}" if elapsed else detail_line
    return current


def failure_diagnostic_message(root: Path) -> str:
    """Return a safe stage and reason code summary when the executor stops."""
    status_file = root / "executor/deployment/foundation/status.json"
    try:
        if status_file.is_file() and not status_file.is_symlink():
            data = json.loads(status_file.read_bytes().decode("utf-8"))
            stage = data.get("current_stage")
            reason = data.get("reason_code")
            if isinstance(stage, str) and isinstance(reason, str):
                return (
                    f"Stage '{stage}' stopped ({reason}). "
                    "Inspect retained state or reset setup if no resources were created."
                )
    except (OSError, ValueError):
        pass
    return "Executor stopped. Inspect private traces and retained evidence before resuming."


def reset_unapplied_installation(area: Path) -> None:
    """Clear retained pre-apply setup state when no Azure resource mutation has occurred."""
    if (area / "native-ownership.json").exists():
        raise ValueError(
            "Native lifecycle ownership was accepted; Bootstrap cannot reset this installation."
        )
    status_file = area / "deployment/foundation/status.json"
    if status_file.is_file() and not status_file.is_symlink():
        try:
            data = json.loads(status_file.read_bytes().decode("utf-8"))
        except (OSError, ValueError) as exc:
            raise ValueError(
                "Retained Foundation status cannot be verified; inspect before resetting."
            ) from exc
        if not isinstance(data, dict) or data.get("mutation_performed") is not False:
            raise ValueError(
                "Azure resources were already modified; inspect or resume the retained installation."
            )
    (area / "configuration.json").unlink(missing_ok=True)
    (area / "acceptance.json").unlink(missing_ok=True)
    shutil.rmtree(area / "deployment", ignore_errors=True)
    shutil.rmtree(area / "pinned-source", ignore_errors=True)


def prepare_pinned_source_checkout(area: Path, source: Path, commit: str) -> Path:
    """Create or verify an isolated detached checkout so working-tree changes cannot interrupt a run."""
    pinned = area / "pinned-source"
    if pinned.resolve() == source.resolve():
        return pinned
    if not pinned.exists():
        origin_proc = subprocess.run(
            ["git", "-C", str(source), "remote", "get-url", "origin"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        origin_url = origin_proc.stdout.strip() or OFFICIAL_SOURCE
        for cmd in (
            ("git", "clone", "--quiet", "--local", "--no-checkout", str(source), str(pinned)),
            ("git", "-C", str(pinned), "remote", "set-url", "origin", origin_url),
            (
                "git",
                "-C",
                str(pinned),
                "-c",
                "core.hooksPath=/dev/null",
                "checkout",
                "--quiet",
                "--detach",
                commit,
            ),
        ):
            res = subprocess.run(
                cmd, stdin=subprocess.DEVNULL, capture_output=True, timeout=120, check=False
            )
            if res.returncode:
                shutil.rmtree(pinned, ignore_errors=True)
                return source
    try:
        inspect_source(pinned, expected_commit=commit)
    except (ValueError, OSError):
        return source
    return pinned


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
