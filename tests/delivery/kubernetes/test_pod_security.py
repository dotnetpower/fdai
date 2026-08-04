"""UID-grounded Pod Security mismatch candidate tests."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta

from fdai.delivery.kubernetes.pod_security import pod_security_mismatch_findings

_CUTOFF = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)


def test_pod_security_mismatch_requires_recent_exact_uid_owner_chain() -> None:
    finding = pod_security_mismatch_findings(
        _resources(), _events(), evidence_complete=True, evidence_cutoff=_CUTOFF
    )[0]

    assert finding["resource"]["uid"] == "deployment-uid"
    assert finding["affected_resource"]["uid"] == "rs-uid"
    assert finding["pod_security_violations"] == ["allow_privilege_escalation"]
    assert finding["causality"] == "candidate_only"
    assert finding["decision"] == "hold"


def test_pod_security_mismatch_abstains_on_truncated_or_stale_evidence() -> None:
    stale = _events()
    stale[0]["last_seen"] = "2026-08-04T11:40:00Z"
    assert not pod_security_mismatch_findings(
        _resources(), _events(), evidence_complete=False, evidence_cutoff=_CUTOFF
    )
    assert not pod_security_mismatch_findings(
        _resources(), stale, evidence_complete=True, evidence_cutoff=_CUTOFF
    )


def test_pod_security_mismatch_abstains_on_uid_conflict_or_future_event() -> None:
    conflict = _events()
    conflict[0]["regarding"]["uid"] = "replacement-uid"  # type: ignore[index]
    future = _events()
    future[0]["last_seen"] = (_CUTOFF + timedelta(seconds=1)).isoformat()
    assert not pod_security_mismatch_findings(
        _resources(), conflict, evidence_complete=True, evidence_cutoff=_CUTOFF
    )
    assert not pod_security_mismatch_findings(
        _resources(), future, evidence_complete=True, evidence_cutoff=_CUTOFF
    )


def test_pod_security_mismatch_abstains_on_unknown_violation_or_healthy_owner() -> None:
    unknown = _events()
    unknown[0]["pod_security_violations"] = ["unknown"]
    healthy = deepcopy(_resources())
    healthy[1]["ready"] = 2
    assert not pod_security_mismatch_findings(
        _resources(), unknown, evidence_complete=True, evidence_cutoff=_CUTOFF
    )
    assert not pod_security_mismatch_findings(
        healthy, _events(), evidence_complete=True, evidence_cutoff=_CUTOFF
    )


def test_pod_security_mismatch_is_metamorphic_to_order_and_namespace_rename() -> None:
    expected = pod_security_mismatch_findings(
        _resources(), _events(), evidence_complete=True, evidence_cutoff=_CUTOFF
    )
    resources = deepcopy(_resources())
    events = deepcopy(_events())
    for resource in resources:
        resource["namespace"] = "renamed-app"
    events[0]["namespace"] = "renamed-app"
    assert (
        pod_security_mismatch_findings(
            list(reversed(_resources())),
            list(reversed(_events())),
            evidence_complete=True,
            evidence_cutoff=_CUTOFF,
        )
        == expected
    )
    renamed = pod_security_mismatch_findings(
        resources, events, evidence_complete=True, evidence_cutoff=_CUTOFF
    )
    assert renamed[0]["resource"]["namespace"] == "renamed-app"


def _resources() -> list[dict[str, object]]:
    return [
        {
            "kind": "ReplicaSet",
            "namespace": "example-app",
            "name": "api-1",
            "uid": "rs-uid",
            "owner_reference_projection_complete": True,
            "owner_references": [
                {"kind": "Deployment", "name": "api", "uid": "deployment-uid", "controller": True}
            ],
        },
        {
            "kind": "Deployment",
            "namespace": "example-app",
            "name": "api",
            "uid": "deployment-uid",
            "desired": 2,
            "ready": 1,
        },
    ]


def _events() -> list[dict[str, object]]:
    return [
        {
            "name": "admission-1",
            "namespace": "example-app",
            "code": "pod_security_admission_rejected",
            "pod_security_profile": "restricted",
            "pod_security_version": "latest",
            "pod_security_violations": ["allow_privilege_escalation"],
            "last_seen": "2026-08-04T11:59:00Z",
            "regarding": {"kind": "ReplicaSet", "name": "api-1", "uid": "rs-uid"},
        }
    ]
