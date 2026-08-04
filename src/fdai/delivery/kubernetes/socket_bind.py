"""Secret-safe application socket bind conflict candidates."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from typing import Any, Final

_SOCKET_BIND_CONFLICT: Final = re.compile(
    r"\b(?:eaddrinuse|address[\s_-]+already[\s_-]+in[\s_-]+use|errno[\s_-]*98)\b",
    re.IGNORECASE,
)


def socket_bind_conflict_findings(
    records: Sequence[Mapping[str, Any]],
    *,
    evidence_complete: bool,
    evidence_cutoff: datetime,
    window: timedelta = timedelta(minutes=5),
) -> tuple[dict[str, Any], ...]:
    """Reduce recent exact-Pod log records without exposing raw log bodies."""

    if not evidence_complete or evidence_cutoff.tzinfo is None or window <= timedelta(0):
        return ()
    lower_bound = evidence_cutoff - window
    grouped: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for record in records:
        body = record.get("body")
        observed_at = _timestamp(record.get("observed_at"))
        identity = (
            str(record.get("namespace") or ""),
            str(record.get("pod") or ""),
            str(record.get("pod_uid") or ""),
            str(record.get("container") or ""),
        )
        if (
            not isinstance(body, str)
            or not body
            or len(body) > 1_024
            or _SOCKET_BIND_CONFLICT.search(body) is None
            or observed_at is None
            or observed_at < lower_bound
            or observed_at > evidence_cutoff
            or not all(identity)
        ):
            continue
        group = grouped.setdefault(identity, {"occurrence_count": 0, "last_seen": observed_at})
        group["occurrence_count"] += 1
        group["last_seen"] = max(group["last_seen"], observed_at)

    return tuple(
        {
            "reason": "application_socket_bind_conflict_candidate",
            "resource": {
                "kind": "Pod",
                "namespace": identity[0],
                "name": identity[1],
                "uid": identity[2],
            },
            "container": identity[3][:253],
            "failure_class": "socket_bind_conflict",
            "occurrence_count": group["occurrence_count"],
            "last_seen": group["last_seen"].isoformat(),
            "evidence_strength": "recent_exact_pod_log_signature",
            "causality": "candidate_only",
            "decision": "hold",
        }
        for identity, group in sorted(grouped.items())[:32]
    )


def _timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


__all__ = ["socket_bind_conflict_findings"]
