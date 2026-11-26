"""Remove managed-host transfer residue after a converged standalone application run."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import stat
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fdai_deployment_cli.deployment_progress import begin_stage, progress_detail
from fdai_deployment_cli.standalone_host_state import (
    absolute,
    acquire_checkpoint_lock,
    private_directory,
)

PRUNE_SCHEMA = "fdai.standalone-transfer-prune.v1"
_MODULE = "fdai_deployment_cli.standalone_transfer_cleanup"
_TRANSFER = re.compile(r"\.fdai-transfer-[0-9a-f]{24}")
_CLAIM_SUFFIX = "-claim.json"
# Re-derivable copies and credential caches; claims, receipts, reviews, plans, and migration
# evidence stay with any directory whose claim has no receipt.
_DISPOSABLE_ROOT = ("kit", "kit.tar.gz", "venv")
_DISPOSABLE_APPLICATION = ("kit-work", "oci", "runtime-venv", "azure", "aks.kubeconfig")
_PROVIDER_DATA_PREFIX = "terraform-data"


def cleanup_remote_transfers(
    tunnel: Any,
    *,
    transient_paths: tuple[str, ...],
    remote_approval: str,
    prune: Callable[[], dict[str, Any]],
) -> None:
    """Remove this run's transient files, then prune transfers that earlier kits left."""

    if not transient_paths:
        raise ValueError("standalone remote transient cleanup has no transfer paths")
    begin_stage("cleanup")
    progress_detail("Removing transient transfers and verifying their absence")
    cleanup = tunnel.ssh(("rm", "-f", "--", *transient_paths, remote_approval), timeout=300)
    absent = [
        tunnel.ssh(("test", "!", "-e", path), timeout=60)
        for path in (*transient_paths, remote_approval)
    ]
    if any(result.returncode != 0 for result in (cleanup, *absent)):
        raise ValueError("standalone remote transient cleanup is incomplete")
    try:
        report = validate_prune_report(prune())
    except ValueError as exc:
        progress_detail(f"Superseded managed-host transfers were not pruned: {exc}")
        return
    freed = max(0, report["free_bytes_after"] - report["free_bytes_before"])
    progress_detail(
        f"Pruned {len(report['removed'])} superseded transfer(s), kept the evidence of "
        f"{len(report['preserved'])}, skipped {len(report['skipped'])}; "
        f"{freed / 1_000_000_000:.1f} GB freed"
    )


def validate_prune_report(value: object) -> dict[str, Any]:
    """Accept only the bounded host prune report this package produces."""

    if not isinstance(value, dict) or value.get("schema_version") != PRUNE_SCHEMA:
        raise ValueError("managed-host prune report is invalid")
    removed, preserved, skipped = value.get("removed"), value.get("preserved"), value.get("skipped")
    if (
        not isinstance(removed, list)
        or not isinstance(preserved, list)
        or not isinstance(skipped, list)
        or any(not isinstance(name, str) or _TRANSFER.fullmatch(name) is None for name in removed)
        or any(
            not isinstance(item, dict)
            or _TRANSFER.fullmatch(str(item.get("name"))) is None
            or not isinstance(item.get("unmatched_claims"), list)
            or not item["unmatched_claims"]
            for item in preserved
        )
        or any(
            not isinstance(item, dict) or _TRANSFER.fullmatch(str(item.get("name"))) is None
            for item in skipped
        )
        or any(type(value.get(key)) is not int for key in ("free_bytes_before", "free_bytes_after"))
    ):
        raise ValueError("managed-host prune report is invalid")
    return value


def prune_superseded_transfers(work_dir: Path) -> dict[str, object]:
    """Prune transfer directories from earlier kits once the current application converged."""

    current = work_dir.parent
    home = current.parent
    if work_dir.name != "application" or _TRANSFER.fullmatch(current.name) is None:
        raise ValueError("managed-host transfer layout is invalid")
    if not (work_dir / "application-receipt.json").is_file():
        raise ValueError("superseded transfers are pruned only after the application converges")
    free_before = shutil.disk_usage(home).free
    removed: list[str] = []
    preserved: list[dict[str, object]] = []
    skipped: list[dict[str, str]] = []
    for entry in sorted(home.iterdir(), key=lambda path: path.name):
        if entry.name == current.name or _TRANSFER.fullmatch(entry.name) is None:
            continue
        reason = _prune_one(entry, removed, preserved)
        if reason is not None:
            skipped.append({"name": entry.name, "reason": reason})
    return {
        "schema_version": PRUNE_SCHEMA,
        "removed": removed,
        "preserved": preserved,
        "skipped": skipped,
        "free_bytes_before": free_before,
        "free_bytes_after": shutil.disk_usage(home).free,
        "mutation_performed": bool(removed or preserved),
        "subscription_ready": False,
    }


def _prune_one(entry: Path, removed: list[str], preserved: list[dict[str, object]]) -> str | None:
    details = entry.lstat()
    if not stat.S_ISDIR(details.st_mode) or details.st_uid != os.geteuid():
        return "not-an-owned-directory"
    application = entry / "application"
    if os.path.lexists(application) and (application.is_symlink() or not application.is_dir()):
        return "unexpected-layout"
    lock: int | None = None
    try:
        if application.is_dir():
            lock = acquire_checkpoint_lock(application)
        unmatched = _unmatched_claims(application)
        if unmatched:
            for path in _disposable_paths(entry, application):
                _remove(path)
            preserved.append({"name": entry.name, "unmatched_claims": unmatched})
            return None
        _remove(entry)
        removed.append(entry.name)
        return None
    except (OSError, ValueError):
        return "in-use-or-not-removable"
    finally:
        if lock is not None:
            os.close(lock)


def _unmatched_claims(application: Path) -> list[str]:
    if not application.is_dir():
        return []
    return sorted(
        claim.name
        for claim in application.glob(f"*{_CLAIM_SUFFIX}")
        if not os.path.lexists(
            application / f"{claim.name.removesuffix(_CLAIM_SUFFIX)}-receipt.json"
        )
    )


def _disposable_paths(entry: Path, application: Path) -> list[Path]:
    paths = [entry / name for name in _DISPOSABLE_ROOT]
    if application.is_dir():
        paths.extend(application / name for name in _DISPOSABLE_APPLICATION)
        paths.extend(
            child for child in application.iterdir() if child.name.startswith(_PROVIDER_DATA_PREFIX)
        )
    return [path for path in paths if os.path.lexists(path)]


def _remove(path: Path) -> None:
    if path.is_symlink() or not path.is_dir():
        path.unlink()
    else:
        shutil.rmtree(path)
    if os.path.lexists(path):
        raise OSError("managed-host transfer residue remains after removal")


def remote_prune(
    tunnel: Any, *, remote_root: str, work_dir: str, timeout: int = 1800
) -> dict[str, Any]:
    """Run the managed-host prune from the current transfer's environment and validate it."""

    result = tunnel.ssh(
        (f"{remote_root}/venv/bin/python", "-m", _MODULE, "--work-dir", work_dir),
        timeout=timeout,
    )
    if result.returncode != 0:
        raise ValueError("managed-host prune failed")
    try:
        value = json.loads(result.stdout)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("managed-host prune report is invalid") from exc
    return validate_prune_report(value)


def main(argv: list[str] | None = None) -> int:
    """Prune superseded transfers under the current application's checkpoint lock."""

    parser = argparse.ArgumentParser(prog=f"python -m {_MODULE}")
    parser.add_argument("--work-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    work_dir = absolute(args.work_dir)
    lock: int | None = None
    try:
        if not work_dir.is_dir():
            raise ValueError("managed-host transfer layout is invalid")
        private_directory(work_dir)
        lock = acquire_checkpoint_lock(work_dir)
        report = prune_superseded_transfers(work_dir)
    except (OSError, ValueError):
        print(json.dumps({"schema_version": PRUNE_SCHEMA, "state": "refused"}), file=sys.stderr)
        return 3
    finally:
        if lock is not None:
            os.close(lock)
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return 0


__all__ = [
    "PRUNE_SCHEMA",
    "cleanup_remote_transfers",
    "main",
    "prune_superseded_transfers",
    "remote_prune",
    "validate_prune_report",
]


if __name__ == "__main__":
    raise SystemExit(main())
