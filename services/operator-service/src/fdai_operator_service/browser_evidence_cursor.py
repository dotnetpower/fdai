"""Opaque drift-aware cursor codec for Browser evidence pages."""

from __future__ import annotations

import base64
import binascii
import json
import re
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Final

from fdai_service_contracts import BrowserEvidenceWorkspaceQuery

_CURSOR_TTL: Final = timedelta(minutes=15)


def encode_browser_evidence_cursor(
    row: Mapping[str, object],
    *,
    query: BrowserEvidenceWorkspaceQuery,
) -> str:
    """Bind one page position to normalized filters without granting authority."""

    captured_at = row.get("captured_at")
    artifact_id = row.get("artifact_id")
    attention_rank = row.get("attention_rank")
    observed_at = row.get("observed_at")
    if (
        not isinstance(captured_at, datetime)
        or captured_at.tzinfo is None
        or not isinstance(observed_at, datetime)
        or observed_at.tzinfo is None
        or not isinstance(artifact_id, str)
        or re.fullmatch(r"sha256:[0-9a-f]{64}", artifact_id) is None
        or isinstance(attention_rank, bool)
        or not isinstance(attention_rank, int)
        or not 0 <= attention_rank <= 4
    ):
        raise ValueError("browser evidence cursor row is invalid")
    payload = json.dumps(
        {
            "v": 1,
            "issued_at": observed_at.astimezone(UTC).isoformat(),
            "attention_rank": attention_rank,
            "captured_at": captured_at.astimezone(UTC).isoformat(),
            "artifact_id": artifact_id,
            "query": _query_identity(query),
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return base64.urlsafe_b64encode(payload).rstrip(b"=").decode("ascii")


def decode_browser_evidence_cursor(
    value: str | None,
    *,
    query: BrowserEvidenceWorkspaceQuery,
    now: datetime,
) -> tuple[int, datetime, str] | None:
    """Reject malformed, expired, or filter-mismatched cursors."""

    if not value:
        return None
    if now.tzinfo is None:
        raise ValueError("browser evidence cursor clock MUST include timezone")
    try:
        padded = value + "=" * (-len(value) % 4)
        payload = json.loads(base64.b64decode(padded, altchars=b"-_", validate=True).decode())
        if not isinstance(payload, Mapping) or frozenset(payload) != {
            "v",
            "issued_at",
            "attention_rank",
            "captured_at",
            "artifact_id",
            "query",
        }:
            raise ValueError
        issued_at = _timestamp(payload["issued_at"])
        captured_at = _timestamp(payload["captured_at"])
        attention_rank = payload["attention_rank"]
        artifact_id = payload["artifact_id"]
        if (
            payload["v"] != 1
            or payload["query"] != _query_identity(query)
            or issued_at > now.astimezone(UTC) + timedelta(minutes=1)
            or now.astimezone(UTC) - issued_at > _CURSOR_TTL
            or isinstance(attention_rank, bool)
            or not isinstance(attention_rank, int)
            or not 0 <= attention_rank <= 4
            or not isinstance(artifact_id, str)
            or re.fullmatch(r"sha256:[0-9a-f]{64}", artifact_id) is None
        ):
            raise ValueError
    except (
        binascii.Error,
        KeyError,
        TypeError,
        UnicodeDecodeError,
        ValueError,
        json.JSONDecodeError,
    ) as exc:
        raise ValueError("invalid or expired Browser evidence cursor") from exc
    return attention_rank, captured_at, artifact_id


def _query_identity(query: BrowserEvidenceWorkspaceQuery) -> dict[str, object]:
    return {
        "artifact_id": query.artifact_id,
        "host": query.host,
        "host_scope": query.host_scope,
        "policy_id": query.policy_id,
        "policy_version": query.policy_version,
        "captured_from": (
            None if query.captured_from is None else query.captured_from.astimezone(UTC).isoformat()
        ),
        "captured_before": (
            None
            if query.captured_before is None
            else query.captured_before.astimezone(UTC).isoformat()
        ),
        "retention": query.retention,
        "finding": query.finding,
        "custody_ref": query.custody_ref,
        "sort": query.sort,
    }


def _timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError
    return parsed.astimezone(UTC)


__all__ = ["decode_browser_evidence_cursor", "encode_browser_evidence_cursor"]
