"""Strict payload-free browser-evidence metadata projection."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime

from fdai_service_contracts import JsonObject, JsonValue


def browser_evidence_projection(rows: Sequence[Mapping[str, object]]) -> JsonObject:
    """Decode bounded durable metadata without captured payload material."""

    items: list[JsonValue] = []
    for row in rows:
        if not _boolean(row, "isolation_verified"):
            raise ValueError("browser evidence isolation is not verified")
        items.append(
            {
                "artifact_id": _text(row, "artifact_id"),
                "policy_id": _text(row, "policy_id"),
                "policy_version": _positive_integer(row, "policy_version"),
                "source_url": _text(row, "canonical_source_url"),
                "final_url": _text(row, "canonical_final_url"),
                "captured_at": _timestamp(row, "captured_at"),
                "expires_at": _timestamp(row, "expires_at"),
                "selector_count": _nonnegative_integer(row, "selector_count"),
                "screenshot_hash": _optional_text(row, "screenshot_hash"),
                "text_hash": _optional_text(row, "text_hash"),
                "snapshot_hash": _optional_text(row, "snapshot_hash"),
                "redaction_count": _nonnegative_integer(row, "redaction_count"),
                "browser_version": _text(row, "browser_version"),
                "custody_audit_ref": _text(row, "chain_of_custody_audit_ref"),
                "prompt_injection_finding_count": _nonnegative_integer(
                    row, "prompt_injection_finding_count"
                ),
                "isolation_verified": True,
                "untrusted": _boolean(row, "untrusted"),
                "legal_hold": _boolean(row, "legal_hold"),
                "legal_hold_ref": _optional_text(row, "legal_hold_ref"),
                "legal_hold_at": _optional_timestamp(row, "legal_hold_at"),
            }
        )
    return {"surface": "browser-evidence", "items": items, "count": len(items)}


def _text(row: Mapping[str, object], key: str) -> str:
    value = row.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"browser evidence {key} is invalid")
    return value


def _optional_text(row: Mapping[str, object], key: str) -> str | None:
    value = row.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ValueError(f"browser evidence {key} is invalid")
    return value


def _positive_integer(row: Mapping[str, object], key: str) -> int:
    value = _integer(row, key)
    if value < 1:
        raise ValueError(f"browser evidence {key} is invalid")
    return value


def _nonnegative_integer(row: Mapping[str, object], key: str) -> int:
    value = _integer(row, key)
    if value < 0:
        raise ValueError(f"browser evidence {key} is invalid")
    return value


def _integer(row: Mapping[str, object], key: str) -> int:
    value = row.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"browser evidence {key} is invalid")
    return value


def _boolean(row: Mapping[str, object], key: str) -> bool:
    value = row.get(key)
    if not isinstance(value, bool):
        raise ValueError(f"browser evidence {key} is invalid")
    return value


def _timestamp(row: Mapping[str, object], key: str) -> str:
    value = row.get(key)
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError(f"browser evidence {key} is invalid")
    return value.isoformat()


def _optional_timestamp(row: Mapping[str, object], key: str) -> str | None:
    if row.get(key) is None:
        return None
    return _timestamp(row, key)


__all__ = ["browser_evidence_projection"]
