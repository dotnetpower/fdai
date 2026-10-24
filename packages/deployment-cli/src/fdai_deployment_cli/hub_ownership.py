"""Local Hub ownership marker: once the Lifecycle Agent owns the workloads, Terraform must not.

The marker is recorded after the Terraform release step of the ownership handoff. While it exists,
every entry point that would plan or apply the AKS workloads root refuses, so Terraform and the
agent never write the same object. A present but unreadable marker also refuses: a damaged marker
must not silently hand the objects back to Terraform. Rollback removes the marker only through the
explicit release function after the agent has stopped reconciling.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

from fdai_deployment_cli.contracts import canonical_digest
from fdai_deployment_cli.standalone_host_state import private_json, replace_private_json

MARKER_NAME = "hub-ownership.json"
MARKER_SCHEMA = "fdai.hub-ownership-marker.v1"
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")


def marker_path(work_dir: Path) -> Path:
    return work_dir / MARKER_NAME


def record_hub_ownership(
    work_dir: Path,
    *,
    installation_id: str,
    handoff_receipt_digest: str,
    recorded_at: datetime | None = None,
) -> dict[str, object]:
    """Record the marker once; repeating the same handoff returns the retained record."""

    if _ID.fullmatch(installation_id) is None or _DIGEST.fullmatch(handoff_receipt_digest) is None:
        raise ValueError("hub ownership marker inputs are invalid")
    path = marker_path(work_dir)
    if path.exists():
        retained = _read(path)
        if (
            retained["installation_id"] != installation_id
            or retained["handoff_receipt_digest"] != handoff_receipt_digest
        ):
            raise ValueError("a different hub ownership marker is already recorded")
        return retained
    moment = recorded_at or datetime.now(tz=UTC)
    if moment.tzinfo is None:
        raise ValueError("hub ownership marker time MUST be timezone-aware")
    body: dict[str, object] = {
        "schema_version": MARKER_SCHEMA,
        "installation_id": installation_id,
        "handoff_receipt_digest": handoff_receipt_digest,
        "recorded_at": moment.astimezone(UTC).isoformat(),
    }
    record = body | {"record_digest": "sha256:" + canonical_digest(body)}
    replace_private_json(path, record)
    return record


def release_hub_ownership(work_dir: Path, *, rollback_receipt_digest: str) -> None:
    """Remove the marker for a verified rollback to Terraform; refuses without a receipt."""

    if _DIGEST.fullmatch(rollback_receipt_digest) is None:
        raise ValueError("hub ownership release requires a rollback receipt digest")
    path = marker_path(work_dir)
    if path.exists():
        _read(path)
        path.unlink()


def require_terraform_owned_workloads(work_dir: Path) -> None:
    """Refuse a Terraform workloads operation while the Hub owns the workloads."""

    path = marker_path(work_dir)
    if not path.exists() and not path.is_symlink():
        return
    _read(path)
    raise ValueError(
        "the workloads are Hub-managed; plan the Hub variant instead of the workloads root"
    )


def workloads_terraform_data(context: dict[str, object], work_dir: Path) -> object:
    """Return the workloads Terraform data path only while Terraform owns the workloads."""

    require_terraform_owned_workloads(work_dir)
    return context.get("workloads_terraform_data")


def _read(path: Path) -> dict[str, object]:
    try:
        record = private_json(path, "hub ownership marker")
        digest = record.pop("record_digest", None)
        if (
            record.get("schema_version") != MARKER_SCHEMA
            or set(record)
            != {"schema_version", "installation_id", "handoff_receipt_digest", "recorded_at"}
            or digest != "sha256:" + canonical_digest(record)
            or _ID.fullmatch(str(record["installation_id"])) is None
            or _DIGEST.fullmatch(str(record["handoff_receipt_digest"])) is None
        ):
            raise ValueError("hub ownership marker is invalid")
    except (OSError, ValueError):
        raise ValueError("hub ownership marker is unreadable; workloads stay Hub-managed") from None
    return record | {"record_digest": digest}
