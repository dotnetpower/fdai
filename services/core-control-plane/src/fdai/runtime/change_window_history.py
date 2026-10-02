"""Append-only ChangeWindow history from the deployment-owned operating-intent source."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from fdai.shared.providers.operating_model import OperatingModelSnapshot
from fdai.shared.providers.state_store import StateStore

CHANGE_WINDOW_HISTORY_PREFIX = "change-window-history:v1:"
CHANGE_WINDOW_COVERAGE_PREFIX = "change-window-history-coverage:v1:"
CHANGE_WINDOW_HISTORY_SCHEMA_VERSION = "1.0.0"
CHANGE_WINDOW_HISTORY_WATERMARK_PREFIX = "change-window-history-watermark:"


@dataclass(frozen=True, slots=True)
class ChangeWindowHistoryReceipt:
    """Receipt for one operating-intent admission's retained ChangeWindow history."""

    source_revision: str
    document_digest: str
    recorded_at: datetime
    window_count: int
    watermark: str


async def record_change_window_history(
    store: StateStore,
    snapshot: OperatingModelSnapshot,
    *,
    document_digest: str,
    recorded_at: datetime,
) -> ChangeWindowHistoryReceipt:
    """Retain every admitted ChangeWindow revision without changing authority."""

    if recorded_at.tzinfo is None or recorded_at.utcoffset() is None:
        raise ValueError("ChangeWindow history recorded_at MUST be timezone-aware")
    rows = tuple(
        _row(
            record.id,
            record.properties,
            source_revision=snapshot.source_revision,
            document_digest=document_digest,
            recorded_at=recorded_at.astimezone(UTC),
        )
        for record in snapshot.objects
        if record.object_type == "ChangeWindow"
    )
    revision_refs: list[str] = []
    for row in sorted(rows, key=lambda item: (item["window_id"], item["revision_ref"])):
        prior = await _latest_for_window(store, str(row["window_id"]))
        if prior is not None and prior.get("revision_ref") != row["revision_ref"]:
            row = {**row, "supersedes_revision_ref": str(prior["revision_ref"])}
        key = CHANGE_WINDOW_HISTORY_PREFIX + str(row["revision_ref"]).removeprefix("sha256:")
        await store.write_state_if_absent(key, row)
        revision_refs.append(str(row["revision_ref"]))
    watermark = CHANGE_WINDOW_HISTORY_WATERMARK_PREFIX + _digest(
        {
            "source_revision": snapshot.source_revision,
            "document_digest": document_digest,
            "recorded_at": recorded_at.astimezone(UTC).isoformat(),
            "revision_refs": revision_refs,
        }
    )
    await store.write_state_if_absent(
        CHANGE_WINDOW_COVERAGE_PREFIX + _digest(snapshot.source_revision),
        {
            "schema_version": CHANGE_WINDOW_HISTORY_SCHEMA_VERSION,
            "source_revision": snapshot.source_revision,
            "document_digest": document_digest,
            "recorded_at": recorded_at.astimezone(UTC).isoformat(),
            "window_count": len(rows),
            "watermark": watermark,
            "revision_refs": revision_refs,
        },
    )
    return ChangeWindowHistoryReceipt(
        source_revision=snapshot.source_revision,
        document_digest=document_digest,
        recorded_at=recorded_at.astimezone(UTC),
        window_count=len(rows),
        watermark=watermark,
    )


async def _latest_for_window(store: StateStore, window_id: str) -> Mapping[str, Any] | None:
    rows, _total = await store.read_state_page(
        CHANGE_WINDOW_HISTORY_PREFIX,
        limit=1,
        field="window_id",
        value=window_id,
    )
    return dict(rows[0]) if rows else None


def _row(
    window_id: str,
    properties: Mapping[str, Any],
    *,
    source_revision: str,
    document_digest: str,
    recorded_at: datetime,
) -> dict[str, object]:
    scope_ref = _text(properties, "scope_ref")
    window_kind = _text(properties, "window_kind")
    status = _text(properties, "status")
    effective_from = _timestamp(properties, "effective_from")
    effective_to = _timestamp(properties, "effective_to")
    policy_ref = _text(properties, "policy_ref")
    approval_ref = properties.get("approval_ref")
    if approval_ref is not None and not isinstance(approval_ref, str):
        raise ValueError("ChangeWindow approval_ref MUST be text when present")
    if effective_from > effective_to:
        raise ValueError("ChangeWindow effective interval is invalid")
    payload = {
        "window_id": window_id,
        "scope_ref": scope_ref,
        "window_kind": window_kind,
        "status": status,
        "effective_from": effective_from.astimezone(UTC).isoformat(),
        "effective_to": effective_to.astimezone(UTC).isoformat(),
        "policy_ref": policy_ref,
        "approval_ref": approval_ref,
        "source_revision": source_revision,
        "document_digest": document_digest,
    }
    revision_ref = "sha256:" + _digest(payload)
    return {
        "schema_version": CHANGE_WINDOW_HISTORY_SCHEMA_VERSION,
        **payload,
        "recorded_at": recorded_at.isoformat(),
        "revision_ref": revision_ref,
        "supersedes_revision_ref": None,
    }


def _text(properties: Mapping[str, Any], key: str) -> str:
    value = properties.get(key)
    if not isinstance(value, str) or not value.strip() or len(value) > 512:
        raise ValueError(f"ChangeWindow {key} MUST be bounded text")
    return value


def _timestamp(properties: Mapping[str, Any], key: str) -> datetime:
    value = properties.get(key)
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        raise ValueError(f"ChangeWindow {key} MUST be a timestamp")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"ChangeWindow {key} MUST be timezone-aware")
    return parsed.astimezone(UTC)


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, separators=(",", ":"), sort_keys=True, default=str).encode()
    ).hexdigest()


__all__ = [
    "CHANGE_WINDOW_COVERAGE_PREFIX",
    "CHANGE_WINDOW_HISTORY_PREFIX",
    "CHANGE_WINDOW_HISTORY_SCHEMA_VERSION",
    "CHANGE_WINDOW_HISTORY_WATERMARK_PREFIX",
    "ChangeWindowHistoryReceipt",
    "record_change_window_history",
]
