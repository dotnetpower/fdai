"""Strict query parsing for the Browser evidence workspace."""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Literal, cast

from fdai_service_contracts import BrowserEvidenceWorkspaceQuery

_ALLOWED_PARAMETERS = frozenset(
    {
        "artifact",
        "before",
        "cursor",
        "custody",
        "finding",
        "from",
        "host",
        "host_scope",
        "limit",
        "policy",
        "policy_version",
        "retention",
        "sort",
    }
)
_RFC3339 = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?"
    r"(?:Z|[+-]\d{2}:\d{2})$"
)


def parse_browser_evidence_workspace_query(
    items: Sequence[tuple[str, str]],
) -> BrowserEvidenceWorkspaceQuery:
    """Reject unknown or duplicate parameters before constructing the typed query."""

    values: dict[str, str] = {}
    for key, value in items:
        if key not in _ALLOWED_PARAMETERS:
            raise ValueError(f"unknown browser evidence query parameter: {key}")
        if key in values:
            raise ValueError(f"duplicate browser evidence query parameter: {key}")
        if value == "":
            raise ValueError(f"browser evidence query parameter {key} MUST be non-empty")
        values[key] = value

    return BrowserEvidenceWorkspaceQuery(
        limit=_integer(values.get("limit", "50"), "limit"),
        cursor=values.get("cursor"),
        artifact_id=values.get("artifact"),
        host=values.get("host"),
        host_scope=cast(
            Literal["requested", "final", "either"],
            values.get("host_scope", "either"),
        ),
        policy_id=values.get("policy"),
        policy_version=_optional_integer(values.get("policy_version"), "policy_version"),
        captured_from=_optional_timestamp(values.get("from"), "from"),
        captured_before=_optional_timestamp(values.get("before"), "before"),
        retention=cast(
            Literal["held", "expired_pending_purge", "expiring", "retained"] | None,
            values.get("retention"),
        ),
        finding=cast(Literal["present", "clear"] | None, values.get("finding")),
        custody_ref=values.get("custody"),
        sort=cast(Literal["attention", "newest"], values.get("sort", "attention")),
    )


def _integer(value: str, label: str) -> int:
    if re.fullmatch(r"[1-9][0-9]*", value) is None:
        raise ValueError(f"browser evidence {label} MUST be a positive integer")
    return int(value)


def _optional_integer(value: str | None, label: str) -> int | None:
    return None if value is None else _integer(value, label)


def _optional_timestamp(value: str | None, label: str) -> datetime | None:
    if value is None:
        return None
    if _RFC3339.fullmatch(value) is None:
        raise ValueError(f"browser evidence {label} MUST be RFC 3339")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"browser evidence {label} MUST be RFC 3339") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"browser evidence {label} MUST include timezone")
    return parsed.astimezone(UTC)


__all__ = ["parse_browser_evidence_workspace_query"]
