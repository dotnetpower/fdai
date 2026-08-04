"""Cumulative admission webhook timeout candidate tests."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta

from fdai.delivery.kubernetes.webhook_timeout import cumulative_webhook_timeout_findings

_CUTOFF = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)


def test_cumulative_timeout_requires_recent_distinct_webhooks_and_events() -> None:
    findings = cumulative_webhook_timeout_findings(
        _events(),
        namespace="example-app",
        evidence_complete=True,
        evidence_cutoff=_CUTOFF,
    )

    assert findings == (
        {
            "reason": "cumulative_admission_webhook_timeout_candidate",
            "resource": {
                "kind": "ReplicaSet",
                "name": "api-1",
                "namespace": "example-app",
                "uid": "replica-uid",
            },
            "webhook_names": ["policy-a.example.io", "policy-b.example.io"],
            "event_names": ["timeout-a", "timeout-b"],
            "webhook_count": 2,
            "window_seconds": 300,
            "last_seen": "2026-08-04T11:59:00+00:00",
            "evidence_strength": "recent_distinct_timeout_events",
            "causality": "candidate_only",
            "decision": "hold",
        },
    )


def test_cumulative_timeout_abstains_on_truncated_or_stale_evidence() -> None:
    stale = deepcopy(_events())
    for event in stale:
        event["last_seen"] = "2026-08-04T11:40:00Z"

    assert not cumulative_webhook_timeout_findings(
        _events(),
        namespace="example-app",
        evidence_complete=False,
        evidence_cutoff=_CUTOFF,
    )
    assert not cumulative_webhook_timeout_findings(
        stale,
        namespace="example-app",
        evidence_complete=True,
        evidence_cutoff=_CUTOFF,
    )


def test_cumulative_timeout_abstains_on_duplicate_webhook_or_event() -> None:
    duplicate_webhook = deepcopy(_events())
    duplicate_webhook[1]["webhook_name"] = "policy-a.example.io"
    duplicate_event = deepcopy(_events())
    duplicate_event[1]["name"] = "timeout-a"

    assert not cumulative_webhook_timeout_findings(
        duplicate_webhook,
        namespace="example-app",
        evidence_complete=True,
        evidence_cutoff=_CUTOFF,
    )
    assert not cumulative_webhook_timeout_findings(
        duplicate_event,
        namespace="example-app",
        evidence_complete=True,
        evidence_cutoff=_CUTOFF,
    )


def test_cumulative_timeout_abstains_on_uid_conflict_or_future_event() -> None:
    uid_conflict = deepcopy(_events())
    uid_conflict[1]["regarding"]["uid"] = "replacement-uid"  # type: ignore[index]
    future = deepcopy(_events())
    future[1]["last_seen"] = (_CUTOFF + timedelta(seconds=1)).isoformat()

    assert not cumulative_webhook_timeout_findings(
        uid_conflict,
        namespace="example-app",
        evidence_complete=True,
        evidence_cutoff=_CUTOFF,
    )
    assert not cumulative_webhook_timeout_findings(
        future,
        namespace="example-app",
        evidence_complete=True,
        evidence_cutoff=_CUTOFF,
    )


def test_cumulative_timeout_ignores_malformed_evidence() -> None:
    malformed = deepcopy(_events())
    malformed[0]["last_seen"] = "not-a-timestamp"
    malformed[1]["regarding"] = {"kind": "ReplicaSet", "name": "api-1"}

    assert not cumulative_webhook_timeout_findings(
        malformed,
        namespace="example-app",
        evidence_complete=True,
        evidence_cutoff=_CUTOFF,
    )


def test_cumulative_timeout_is_invariant_to_event_order() -> None:
    expected = cumulative_webhook_timeout_findings(
        _events(),
        namespace="example-app",
        evidence_complete=True,
        evidence_cutoff=_CUTOFF,
    )

    assert (
        cumulative_webhook_timeout_findings(
            list(reversed(_events())),
            namespace="example-app",
            evidence_complete=True,
            evidence_cutoff=_CUTOFF,
        )
        == expected
    )


def _events() -> list[dict[str, object]]:
    return [
        {
            "name": "timeout-a",
            "namespace": "example-app",
            "code": "admission_webhook_timeout",
            "webhook_name": "policy-a.example.io",
            "last_seen": "2026-08-04T11:58:00Z",
            "regarding": {
                "kind": "ReplicaSet",
                "name": "api-1",
                "uid": "replica-uid",
            },
        },
        {
            "name": "timeout-b",
            "namespace": "example-app",
            "code": "admission_webhook_timeout",
            "webhook_name": "policy-b.example.io",
            "last_seen": "2026-08-04T11:59:00Z",
            "regarding": {
                "kind": "ReplicaSet",
                "name": "api-1",
                "uid": "replica-uid",
            },
        },
    ]
