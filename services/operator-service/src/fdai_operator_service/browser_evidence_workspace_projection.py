"""Strict versioned projection for the payload-free Browser evidence workspace."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from fdai_service_contracts import JsonObject, JsonValue

_RETENTION_STATES = frozenset({"held", "expired_pending_purge", "expiring", "retained"})
_AUDIT_LINK_STATES = frozenset(
    {"exact", "missing", "malformed", "ambiguous", "unsupported_sequence"}
)
_SUMMARY_FIELDS = (
    "observed_at",
    "source_observed_at",
    "snapshot_total_count",
    "snapshot_admitted_count",
    "snapshot_withheld_count",
    "withheld_invalid_metadata_count",
    "withheld_trust_invalid_count",
    "withheld_isolation_unverified_count",
    "matching_admitted_count",
    "security_finding_count",
    "legal_hold_count",
    "expiring_count",
    "expired_pending_purge_count",
    "retained_count",
)
_MAX_SAFE_SEQUENCE = 9_007_199_254_740_991


@dataclass(frozen=True, slots=True)
class _WorkspaceSummary:
    observed_at: datetime
    source_observed_at: datetime | None
    snapshot_total_count: int
    snapshot_admitted_count: int
    snapshot_withheld_count: int
    withheld_invalid_metadata_count: int
    withheld_trust_invalid_count: int
    withheld_isolation_unverified_count: int
    matching_admitted_count: int
    security_finding_count: int
    legal_hold_count: int
    expiring_count: int
    expired_pending_purge_count: int
    retained_count: int


def browser_evidence_workspace_projection(
    rows: Sequence[Mapping[str, object]],
    *,
    limit: int,
    next_cursor: str | None,
) -> JsonObject:
    """Decode one database observation and expose only admitted scalar metadata."""

    if not rows:
        raise ValueError("browser evidence workspace query returned no summary row")
    if not 1 <= limit <= 500:
        raise ValueError("browser evidence workspace projection limit is invalid")
    summary = _summary(rows[0])
    if any(_summary(row) != summary for row in rows[1:]):
        raise ValueError("browser evidence workspace summary changed within one response")

    raw_items = [row for row in rows if row.get("artifact_id") is not None]
    has_more = len(raw_items) > limit
    visible = raw_items[:limit]
    if has_more != (next_cursor is not None):
        raise ValueError("browser evidence workspace cursor presence is inconsistent")
    if not has_more and next_cursor is not None:
        raise ValueError("browser evidence workspace returned an unexpected cursor")
    if has_more and len(visible) >= summary.matching_admitted_count:
        raise ValueError("browser evidence workspace cursor exceeds matching records")

    projected_items = [_item(row, observed_at=summary.observed_at) for row in visible]
    artifact_ids = [str(item["artifact_id"]) for item in projected_items]
    if len(set(artifact_ids)) != len(artifact_ids):
        raise ValueError("browser evidence workspace contains duplicate artifacts")
    _validate_summary(summary, loaded_count=len(projected_items))
    items: list[JsonValue] = list(projected_items)
    return {
        "schema_version": "2.0.0",
        "surface": "browser-evidence-workspace",
        "consistency": "drift_aware",
        "summary_scope": "filtered_and_snapshot",
        "observed_at": summary.observed_at.isoformat(),
        "source_observed_at": (
            None if summary.source_observed_at is None else summary.source_observed_at.isoformat()
        ),
        "loaded_count": len(projected_items),
        "matching_admitted_count": summary.matching_admitted_count,
        "snapshot_total_count": summary.snapshot_total_count,
        "snapshot_admitted_count": summary.snapshot_admitted_count,
        "snapshot_withheld_count": summary.snapshot_withheld_count,
        "withheld_reasons": {
            "invalid_metadata": summary.withheld_invalid_metadata_count,
            "trust_invalid": summary.withheld_trust_invalid_count,
            "isolation_unverified": summary.withheld_isolation_unverified_count,
        },
        "summary": {
            "security_finding_count": summary.security_finding_count,
            "legal_hold_count": summary.legal_hold_count,
            "expiring_count": summary.expiring_count,
            "expired_pending_purge_count": summary.expired_pending_purge_count,
            "retained_count": summary.retained_count,
        },
        "has_more": has_more,
        "next_cursor": next_cursor,
        "page_complete": not has_more,
        "items": items,
    }


def _summary(row: Mapping[str, object]) -> _WorkspaceSummary:
    observed_at = _timestamp(row, "observed_at")
    source_observed_at = _optional_timestamp(row, "source_observed_at")
    if source_observed_at is not None and source_observed_at > observed_at:
        raise ValueError("browser evidence source observation is in the future")
    values = {
        field: _nonnegative_integer(row, field)
        for field in _SUMMARY_FIELDS
        if field not in {"observed_at", "source_observed_at"}
    }
    return _WorkspaceSummary(
        observed_at=observed_at,
        source_observed_at=source_observed_at,
        snapshot_total_count=values["snapshot_total_count"],
        snapshot_admitted_count=values["snapshot_admitted_count"],
        snapshot_withheld_count=values["snapshot_withheld_count"],
        withheld_invalid_metadata_count=values["withheld_invalid_metadata_count"],
        withheld_trust_invalid_count=values["withheld_trust_invalid_count"],
        withheld_isolation_unverified_count=values["withheld_isolation_unverified_count"],
        matching_admitted_count=values["matching_admitted_count"],
        security_finding_count=values["security_finding_count"],
        legal_hold_count=values["legal_hold_count"],
        expiring_count=values["expiring_count"],
        expired_pending_purge_count=values["expired_pending_purge_count"],
        retained_count=values["retained_count"],
    )


def _validate_summary(summary: _WorkspaceSummary, *, loaded_count: int) -> None:
    withheld_sum = (
        summary.withheld_invalid_metadata_count
        + summary.withheld_trust_invalid_count
        + summary.withheld_isolation_unverified_count
    )
    if summary.snapshot_withheld_count != withheld_sum:
        raise ValueError("browser evidence withheld reasons do not reconcile")
    if summary.snapshot_total_count != (
        summary.snapshot_admitted_count + summary.snapshot_withheld_count
    ):
        raise ValueError("browser evidence snapshot counts do not reconcile")
    matching = summary.matching_admitted_count
    if matching > summary.snapshot_admitted_count or loaded_count > matching:
        raise ValueError("browser evidence loaded counts do not reconcile")
    retention_total = (
        summary.legal_hold_count
        + summary.expiring_count
        + summary.expired_pending_purge_count
        + summary.retained_count
    )
    if retention_total != matching:
        raise ValueError("browser evidence retention counts do not reconcile")


def _item(row: Mapping[str, object], *, observed_at: datetime) -> JsonObject:
    artifact_id = _text(row, "artifact_id", maximum=71)
    if re.fullmatch(r"sha256:[0-9a-f]{64}", artifact_id) is None:
        raise ValueError("browser evidence artifact id is invalid")
    source_host = _hostname(row, "source_host")
    final_host = _hostname(row, "final_host")
    captured_at = _timestamp(row, "captured_at")
    expires_at = _timestamp(row, "expires_at")
    if captured_at >= expires_at:
        raise ValueError("browser evidence retention window is invalid")
    legal_hold = _boolean(row, "legal_hold")
    legal_hold_ref = _optional_text(row, "legal_hold_ref", maximum=512)
    legal_hold_at = _optional_timestamp(row, "legal_hold_at")
    if legal_hold != (legal_hold_ref is not None and legal_hold_at is not None):
        raise ValueError("browser evidence legal hold is inconsistent")
    retention_state = _text(row, "retention_state", maximum=32)
    if retention_state not in _RETENTION_STATES:
        raise ValueError("browser evidence retention state is invalid")
    expected_retention = _retention_state(
        legal_hold=legal_hold,
        expires_at=expires_at,
        observed_at=observed_at,
    )
    if retention_state != expected_retention:
        raise ValueError("browser evidence retention state is inconsistent")
    audit = _audit(row)
    item: JsonObject = {
        "artifact_id": artifact_id,
        "policy_id": _text(row, "policy_id", maximum=256),
        "policy_version": _positive_integer(row, "policy_version"),
        "source_host": source_host,
        "final_host": final_host,
        "redirected": source_host != final_host,
        "captured_at": captured_at.isoformat(),
        "expires_at": expires_at.isoformat(),
        "selector_count": _nonnegative_integer(row, "selector_count"),
        "redaction_count": _nonnegative_integer(row, "redaction_count"),
        "prompt_injection_finding_count": _nonnegative_integer(
            row, "prompt_injection_finding_count"
        ),
        "digest_presence": {
            "screenshot": _boolean(row, "has_screenshot_digest"),
            "text": _boolean(row, "has_text_digest"),
            "accessibility_snapshot": _boolean(row, "has_snapshot_digest"),
        },
        "browser_version": _text(row, "browser_version", maximum=256),
        "custody_audit_ref": _text(row, "chain_of_custody_audit_ref", maximum=512),
        "retention_state": retention_state,
        "legal_hold": legal_hold,
        "legal_hold_ref": legal_hold_ref,
        "legal_hold_at": None if legal_hold_at is None else legal_hold_at.isoformat(),
        "audit": audit,
        "isolation_verified": True,
        "untrusted": True,
        "can_authorize_action": False,
    }
    return item


def _audit(row: Mapping[str, object]) -> JsonObject:
    state = _text(row, "audit_link_state", maximum=32)
    if state not in _AUDIT_LINK_STATES:
        raise ValueError("browser evidence audit link state is invalid")
    sequence = _optional_text(row, "audit_sequence", maximum=19)
    correlation_id = _optional_text(row, "audit_correlation_id", maximum=256)
    if state == "exact":
        if sequence is None or re.fullmatch(r"[1-9][0-9]{0,18}", sequence) is None:
            raise ValueError("browser evidence exact audit sequence is invalid")
        if int(sequence) > _MAX_SAFE_SEQUENCE:
            raise ValueError("browser evidence audit sequence exceeds Console range")
    elif sequence is not None or correlation_id is not None:
        raise ValueError("browser evidence non-exact audit link exposes identity")
    return {
        "state": state,
        "sequence": sequence,
        "correlation_id": correlation_id,
    }


def _retention_state(*, legal_hold: bool, expires_at: datetime, observed_at: datetime) -> str:
    if legal_hold:
        return "held"
    if expires_at <= observed_at:
        return "expired_pending_purge"
    if expires_at <= observed_at + timedelta(days=7):
        return "expiring"
    return "retained"


def _hostname(row: Mapping[str, object], key: str) -> str:
    value = _text(row, key, maximum=253)
    if value != value.lower() or any(character.isspace() for character in value):
        raise ValueError(f"browser evidence {key} is not canonical")
    try:
        canonical = value.encode("idna").decode("ascii").lower()
    except UnicodeError as exc:
        raise ValueError(f"browser evidence {key} is not valid IDNA") from exc
    if canonical != value:
        raise ValueError(f"browser evidence {key} is not canonical")
    return value


def _text(row: Mapping[str, object], key: str, *, maximum: int) -> str:
    value = row.get(key)
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= maximum
        or value != value.strip()
        or any(ord(character) < 32 for character in value)
    ):
        raise ValueError(f"browser evidence {key} is invalid")
    return value


def _optional_text(row: Mapping[str, object], key: str, *, maximum: int) -> str | None:
    return None if row.get(key) is None else _text(row, key, maximum=maximum)


def _positive_integer(row: Mapping[str, object], key: str) -> int:
    value = _nonnegative_integer(row, key)
    if value < 1:
        raise ValueError(f"browser evidence {key} is invalid")
    return value


def _nonnegative_integer(row: Mapping[str, object], key: str) -> int:
    value = row.get(key)
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < 0
        or value > _MAX_SAFE_SEQUENCE
    ):
        raise ValueError(f"browser evidence {key} is invalid")
    return value


def _boolean(row: Mapping[str, object], key: str) -> bool:
    value = row.get(key)
    if not isinstance(value, bool):
        raise ValueError(f"browser evidence {key} is invalid")
    return value


def _timestamp(row: Mapping[str, object], key: str) -> datetime:
    value = row.get(key)
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError(f"browser evidence {key} is invalid")
    return value


def _optional_timestamp(row: Mapping[str, object], key: str) -> datetime | None:
    return None if row.get(key) is None else _timestamp(row, key)


__all__ = ["browser_evidence_workspace_projection"]
