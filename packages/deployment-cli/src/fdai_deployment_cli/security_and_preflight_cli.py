"""CLI facade for `fdaictl security audit`, `fdaictl deploy preflight`, and execution-copy pruning."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
from collections.abc import Mapping
from pathlib import Path

from fdai_deployment_cli.cli_help import command, command_group
from fdai_deployment_cli.execution_copies import EXECUTION_COPY_PREFIXES

_COPY_NAME = re.compile(r"(?:offline-source|bundle-recheck)-[A-Za-z0-9_]{8}")
_SECRET_VALUE_RE = re.compile(
    r"(?i)(?:-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----|bearer\s+[A-Za-z0-9._~+/=-]{12,})"
)


def register_security_and_preflight_commands(
    commands: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """Register `security audit` and `deploy preflight` CLI commands."""
    security = command(
        commands,
        "security",
        "Run deterministic local work-directory and profile security audit checks",
        epilog="Next: fdaictl security audit --help\nAudit is read-only and grants no authority.",
    )
    security_commands = command_group(security)
    audit = command(
        security_commands,
        "audit",
        "Verify private directory permissions, symlink absence, secret hygiene, and state integrity",
    )
    audit.add_argument(
        "--work-dir", type=Path, required=True, help="Private deployment work directory"
    )
    audit.add_argument(
        "--profile", type=Path, default=None, help="Optional private deployment profile"
    )
    audit.add_argument("--output", choices=("text", "json"), default="text")
    audit.set_defaults(handler=security_audit_command)

    deploy = command(
        commands,
        "deploy",
        "Run read-only preflight analysis over local plan and policy inputs",
        epilog=(
            "Next: fdaictl deploy preflight --help\n"
            "Preflight is read-only; live deployment uses `fdaictl provision azure`."
        ),
    )
    deploy_commands = command_group(deploy)
    preflight = command(
        deploy_commands,
        "preflight",
        "Evaluate a Terraform plan JSON against preflight invariants without duplicating authority",
    )
    preflight.add_argument("--plan-json", type=Path, required=True, help="Terraform plan JSON path")
    preflight.add_argument(
        "--mode",
        choices=("deterministic", "live"),
        default="deterministic",
        help="Preflight evaluation mode (default: deterministic)",
    )
    preflight.add_argument("--output", choices=("text", "json"), default="text")
    preflight.set_defaults(handler=deploy_preflight_command)


def run_security_audit(
    *,
    work_dir: Path,
    profile_path: Path | None = None,
) -> dict[str, object]:
    """Run deterministic local security audit checks on a work directory and optional profile."""
    checks: list[dict[str, object]] = []

    if not work_dir.exists() or work_dir.is_symlink() or not work_dir.is_dir():
        checks.append(
            {
                "id": "work_dir_exists_and_not_symlink",
                "passed": False,
                "detail": "work_dir is missing, not a directory, or a symlink",
            }
        )
    else:
        mode = stat.S_IMODE(work_dir.lstat().st_mode)
        owner_ok = work_dir.lstat().st_uid == os.getuid()
        mode_ok = (mode & 0o077) == 0
        checks.append(
            {
                "id": "work_dir_exists_and_not_symlink",
                "passed": True,
                "detail": "work_dir is a real directory",
            }
        )
        checks.append(
            {
                "id": "work_dir_private_permissions",
                "passed": owner_ok and mode_ok,
                "detail": f"uid_match={owner_ok} mode={oct(mode)}",
            }
        )

        has_symlink = False
        has_secret_leak = False
        for child in sorted(work_dir.rglob("*")):
            if child.is_symlink():
                has_symlink = True
                continue
            if child.is_file() and child.stat().st_size <= 512_000:
                text = child.read_text(encoding="utf-8", errors="ignore")
                if _SECRET_VALUE_RE.search(text):
                    has_secret_leak = True
        checks.append(
            {
                "id": "work_dir_no_symlinks",
                "passed": not has_symlink,
                "detail": "no symlink entries in work_dir" if not has_symlink else "symlink found",
            }
        )
        checks.append(
            {
                "id": "work_dir_secret_hygiene",
                "passed": not has_secret_leak,
                "detail": "no literal private key or bearer token detected"
                if not has_secret_leak
                else "secret pattern detected in work_dir artifact",
            }
        )

    if profile_path is not None:
        if not profile_path.is_file() or profile_path.is_symlink():
            checks.append(
                {
                    "id": "profile_private_file",
                    "passed": False,
                    "detail": "profile is missing or a symlink",
                }
            )
        else:
            p_mode = stat.S_IMODE(profile_path.lstat().st_mode)
            p_ok = (p_mode & 0o077) == 0 and profile_path.lstat().st_uid == os.getuid()
            checks.append(
                {
                    "id": "profile_private_file",
                    "passed": p_ok,
                    "detail": f"mode={oct(p_mode)}",
                }
            )

    passed = all(bool(item["passed"]) for item in checks)
    return {
        "schema_version": "fdai.security-audit.v1",
        "passed": passed,
        "check_count": len(checks),
        "failed_count": sum(not bool(item["passed"]) for item in checks),
        "checks": checks,
        "execution_authority": "none",
    }


def security_audit_command(args: argparse.Namespace) -> int:
    report = run_security_audit(
        work_dir=Path(args.work_dir),
        profile_path=Path(args.profile) if getattr(args, "profile", None) else None,
    )
    if getattr(args, "output", "text") == "json":
        print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    else:
        status = "PASS" if report["passed"] else "FAIL"
        print(
            f"security audit {status}: checks={report['check_count']} "
            f"failed={report['failed_count']}"
        )
    return 0 if report["passed"] else 3


def evaluate_deploy_preflight_plan(
    plan_path: Path,
    *,
    mode: str = "deterministic",
) -> dict[str, object]:
    """Evaluate a Terraform plan JSON via the read-only preflight facade."""
    if mode not in {"deterministic", "live"}:
        raise ValueError("preflight mode must be deterministic or live")
    if plan_path.is_symlink() or not plan_path.is_file():
        raise ValueError("preflight plan JSON must be a regular file")
    if plan_path.stat().st_size > 64 * 1024 * 1024:
        raise ValueError("preflight plan JSON exceeds 64 MiB limit")
    try:
        raw_bytes = plan_path.read_bytes()
        payload = json.loads(raw_bytes.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("preflight plan JSON is unreadable or malformed") from exc
    if not isinstance(payload, Mapping):
        raise ValueError("preflight plan JSON must be an object")

    plan_digest = f"sha256:{hashlib.sha256(raw_bytes).hexdigest()}"
    changes = payload.get("resource_changes", [])
    if not isinstance(changes, list):
        raise ValueError("preflight plan resource_changes must be a list")

    destructive_addresses: list[str] = []
    create_count = 0
    update_count = 0
    for entry in changes:
        if not isinstance(entry, Mapping):
            continue
        address = str(entry.get("address", ""))
        change = entry.get("change")
        actions = change.get("actions", []) if isinstance(change, Mapping) else []
        if not isinstance(actions, list):
            continue
        if "delete" in actions:
            destructive_addresses.append(address)
        if "create" in actions:
            create_count += 1
        if "update" in actions:
            update_count += 1

    passed = len(destructive_addresses) == 0 and payload.get("errored") is not True
    return {
        "schema_version": "fdai.deploy-preflight.v1",
        "mode": mode,
        "plan_digest": plan_digest,
        "passed": passed,
        "create_count": create_count,
        "update_count": update_count,
        "destructive_count": len(destructive_addresses),
        "destructive_addresses": sorted(destructive_addresses),
        "execution_authority": "none",
    }


def deploy_preflight_command(args: argparse.Namespace) -> int:
    report = evaluate_deploy_preflight_plan(
        Path(args.plan_json),
        mode=str(getattr(args, "mode", "deterministic")),
    )
    if getattr(args, "output", "text") == "json":
        print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    else:
        status = "PASS" if report["passed"] else "HOLD"
        print(
            f"deploy preflight {status}: mode={report['mode']} "
            f"creates={report['create_count']} updates={report['update_count']} "
            f"destructive={report['destructive_count']}"
        )
    return 0 if report["passed"] else 3


def prune_obsolete_execution_copies(
    work_dir: Path,
    *,
    max_retained: int = 2,
    active_names: frozenset[str] = frozenset(),
) -> tuple[str, ...]:
    """Prune obsolete execution-copy directories while preserving active/unfinished run evidence."""
    if max_retained < 0:
        raise ValueError("max_retained must be >= 0")
    if not work_dir.is_dir() or work_dir.is_symlink():
        return ()
    candidates: list[tuple[float, Path]] = []
    for entry in work_dir.iterdir():
        if entry.is_symlink() or not entry.is_dir():
            continue
        if not entry.name.startswith(EXECUTION_COPY_PREFIXES):
            continue
        if _COPY_NAME.fullmatch(entry.name) is None:
            continue
        if entry.name in active_names or (entry / ".unfinished-run").exists():
            continue
        candidates.append((entry.stat().st_mtime, entry))
    candidates.sort(key=lambda item: (item[0], item[1].name), reverse=True)
    removed: list[str] = []
    for _, obsolete in candidates[max_retained:]:
        shutil.rmtree(obsolete, ignore_errors=True)
        if not obsolete.exists():
            removed.append(obsolete.name)
    return tuple(sorted(removed))


__all__ = [
    "deploy_preflight_command",
    "evaluate_deploy_preflight_plan",
    "prune_obsolete_execution_copies",
    "register_security_and_preflight_commands",
    "run_security_audit",
    "security_audit_command",
]
