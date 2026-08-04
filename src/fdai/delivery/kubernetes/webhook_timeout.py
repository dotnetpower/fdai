"""Deterministic cumulative admission webhook timeout candidates."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from typing import Any


def cumulative_webhook_timeout_findings(
    events: Sequence[Mapping[str, Any]],
    *,
    namespace: str,
    evidence_complete: bool,
    evidence_cutoff: datetime,
    window: timedelta = timedelta(minutes=5),
) -> tuple[dict[str, Any], ...]:
    """Correlate recent distinct webhook timeouts to one immutable resource identity."""

    if not evidence_complete or evidence_cutoff.tzinfo is None or window <= timedelta(0):
        return ()
    lower_bound = evidence_cutoff - window
    grouped: dict[tuple[str, str, str], dict[str, Any]] = {}
    for event in events:
        if event.get("code") != "admission_webhook_timeout" or event.get("namespace") != namespace:
            continue
        observed_at = _timestamp(event.get("last_seen"))
        webhook_name = event.get("webhook_name")
        regarding = event.get("regarding")
        if (
            observed_at is None
            or observed_at < lower_bound
            or observed_at > evidence_cutoff
            or not isinstance(webhook_name, str)
            or not webhook_name
            or not isinstance(regarding, Mapping)
        ):
            continue
        identity = (
            str(regarding.get("kind") or "")[:128],
            str(regarding.get("name") or "")[:253],
            str(regarding.get("uid") or "")[:128],
        )
        if not all(identity):
            continue
        group = grouped.setdefault(
            identity,
            {
                "webhook_names": set(),
                "event_names": set(),
                "last_seen": observed_at,
            },
        )
        group["webhook_names"].add(webhook_name[:253])
        event_name = event.get("name")
        if isinstance(event_name, str) and event_name:
            group["event_names"].add(event_name[:253])
        group["last_seen"] = max(group["last_seen"], observed_at)

    findings: list[dict[str, Any]] = []
    for identity, group in sorted(grouped.items()):
        webhook_names = sorted(group["webhook_names"])
        event_names = sorted(group["event_names"])
        if len(webhook_names) < 2 or len(event_names) < 2:
            continue
        findings.append(
            {
                "reason": "cumulative_admission_webhook_timeout_candidate",
                "resource": {
                    "kind": identity[0],
                    "name": identity[1],
                    "namespace": namespace,
                    "uid": identity[2],
                },
                "webhook_names": webhook_names,
                "event_names": event_names,
                "webhook_count": len(webhook_names),
                "window_seconds": int(window.total_seconds()),
                "last_seen": group["last_seen"].isoformat(),
                "evidence_strength": "recent_distinct_timeout_events",
                "causality": "candidate_only",
                "decision": "hold",
            }
        )
    return tuple(findings[:32])


def _timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


__all__ = ["cumulative_webhook_timeout_findings"]
