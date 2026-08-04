"""Secret-safe bounded application log signal candidates."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from typing import Any, Final

_SIGNALS: Final = {
    "message_decode_failure": re.compile(
        r"\b(?:json[_-]?decode[_-]?error|deserializ\w*|malformed[_ -](?:message|payload))\b",
        re.IGNORECASE,
    ),
    "stream_progress_blocked": re.compile(
        r"\b(?:offset|partition|checkpoint|cursor)\b.*\b(?:stuck|stalled|not advancing)\b",
        re.IGNORECASE,
    ),
    "application_failure": re.compile(r"\b(?:exception|failed|error)\b", re.IGNORECASE),
}


def bounded_log_signal_findings(
    records: Sequence[Mapping[str, Any]],
    *,
    evidence_complete: bool,
    evidence_cutoff: datetime,
    minimum_occurrences: int = 2,
    window: timedelta = timedelta(minutes=5),
) -> tuple[dict[str, Any], ...]:
    """Aggregate reviewed recent signals without retaining raw bodies."""

    if (
        not evidence_complete
        or evidence_cutoff.tzinfo is None
        or not 1 <= minimum_occurrences <= 100
        or window <= timedelta(0)
    ):
        return ()
    lower_bound = evidence_cutoff - window
    counts: dict[tuple[str, str, str, str, str], int] = {}
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
            or observed_at is None
            or not lower_bound <= observed_at <= evidence_cutoff
            or not all(identity)
        ):
            continue
        signal = next((name for name, pattern in _SIGNALS.items() if pattern.search(body)), None)
        if signal:
            key = (*identity, signal)
            counts[key] = counts.get(key, 0) + 1
    return tuple(
        {
            "reason": "bounded_application_log_signal_candidate",
            "resource": {"kind": "Pod", "namespace": key[0], "name": key[1], "uid": key[2]},
            "container": key[3],
            "signal_class": key[4],
            "occurrence_count": count,
            "evidence_strength": "repeated_recent_exact_pod_log_signature",
            "causality": "candidate_only",
            "decision": "hold",
        }
        for key, count in sorted(counts.items())
        if count >= minimum_occurrences
    )[:32]


def _timestamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


__all__ = ["bounded_log_signal_findings"]
