"""Kubernetes host-port conflict candidate tests."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta

from fdai.delivery.kubernetes.host_port import host_port_conflict_findings

_CUTOFF = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)


def test_host_port_conflict_requires_recent_exact_uid_event_and_projected_port() -> None:
    findings = host_port_conflict_findings(
        _resources(),
        _events(),
        evidence_complete=True,
        evidence_cutoff=_CUTOFF,
    )

    assert findings == (
        {
            "reason": "pod_host_port_conflict_candidate",
            "resource": {
                "kind": "Pod",
                "name": "api-1",
                "namespace": "example-app",
                "uid": "pod-uid",
            },
            "source_paths": ["/spec/containers/0/ports/1/hostPort"],
            "requested_host_ports": [{"container": "api", "host_port": 9100, "protocol": "TCP"}],
            "event_names": ["scheduler-1"],
            "last_seen": "2026-08-04T11:59:00+00:00",
            "evidence_strength": "recent_scheduler_event_and_exact_pod_uid",
            "causality": "candidate_only",
            "decision": "hold",
        },
    )


def test_host_port_conflict_abstains_on_truncated_or_stale_evidence() -> None:
    stale = deepcopy(_events())
    stale[0]["last_seen"] = "2026-08-04T11:40:00Z"

    assert not host_port_conflict_findings(
        _resources(), _events(), evidence_complete=False, evidence_cutoff=_CUTOFF
    )
    assert not host_port_conflict_findings(
        _resources(), stale, evidence_complete=True, evidence_cutoff=_CUTOFF
    )


def test_host_port_conflict_abstains_on_uid_conflict_or_future_event() -> None:
    conflict = deepcopy(_events())
    conflict[0]["regarding"]["uid"] = "replacement-uid"  # type: ignore[index]
    future = deepcopy(_events())
    future[0]["last_seen"] = (_CUTOFF + timedelta(seconds=1)).isoformat()

    assert not host_port_conflict_findings(
        _resources(), conflict, evidence_complete=True, evidence_cutoff=_CUTOFF
    )
    assert not host_port_conflict_findings(
        _resources(), future, evidence_complete=True, evidence_cutoff=_CUTOFF
    )


def test_host_port_conflict_abstains_on_missing_or_malformed_port_projection() -> None:
    missing = deepcopy(_resources())
    missing[0]["pod_spec"]["containers"][0].pop("host_ports")  # type: ignore[index]
    malformed = deepcopy(_resources())
    malformed[0]["pod_spec"]["containers"][0][  # type: ignore[index]
        "host_port_projection_complete"
    ] = False

    assert not host_port_conflict_findings(
        missing, _events(), evidence_complete=True, evidence_cutoff=_CUTOFF
    )
    assert not host_port_conflict_findings(
        malformed, _events(), evidence_complete=True, evidence_cutoff=_CUTOFF
    )


def test_host_port_conflict_is_metamorphic_to_input_order_and_namespace_rename() -> None:
    expected = host_port_conflict_findings(
        _resources(), _events(), evidence_complete=True, evidence_cutoff=_CUTOFF
    )
    renamed_resources = deepcopy(_resources())
    renamed_events = deepcopy(_events())
    renamed_resources[0]["namespace"] = "renamed-app"
    renamed_events[0]["namespace"] = "renamed-app"

    assert (
        host_port_conflict_findings(
            list(reversed(_resources())),
            list(reversed(_events())),
            evidence_complete=True,
            evidence_cutoff=_CUTOFF,
        )
        == expected
    )
    renamed = host_port_conflict_findings(
        renamed_resources,
        renamed_events,
        evidence_complete=True,
        evidence_cutoff=_CUTOFF,
    )
    assert renamed[0]["resource"]["namespace"] == "renamed-app"


def _resources() -> list[dict[str, object]]:
    return [
        {
            "kind": "Pod",
            "name": "api-1",
            "namespace": "example-app",
            "uid": "pod-uid",
            "pod_spec": {
                "projection_complete": True,
                "containers": [
                    {
                        "name": "api",
                        "host_port_projection_complete": True,
                        "host_ports": [{"host_port": 9100, "protocol": "TCP", "source_index": 1}],
                    }
                ],
            },
        }
    ]


def _events() -> list[dict[str, object]]:
    return [
        {
            "name": "scheduler-1",
            "namespace": "example-app",
            "code": "host_port_conflict",
            "last_seen": "2026-08-04T11:59:00Z",
            "regarding": {"kind": "Pod", "name": "api-1", "uid": "pod-uid"},
        }
    ]
