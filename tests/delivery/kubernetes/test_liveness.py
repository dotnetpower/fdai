"""UID-grounded liveness probe failure candidate tests."""

from __future__ import annotations

import hashlib
from copy import deepcopy
from datetime import UTC, datetime, timedelta

from fdai.delivery.kubernetes.liveness import (
    is_liveness_probe_failure,
    liveness_probe_failure_findings,
)

_CUTOFF = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)


def test_liveness_classifier_requires_reviewed_unhealthy_phrase() -> None:
    assert is_liveness_probe_failure(reason="Unhealthy", message="Liveness probe failed: 404")
    assert not is_liveness_probe_failure(reason="Normal", message="Liveness probe failed: 404")
    assert not is_liveness_probe_failure(reason="Unhealthy", message="Readiness probe failed")


def test_liveness_failure_requires_recent_exact_uid_chain_and_common_probe() -> None:
    finding = liveness_probe_failure_findings(
        _resources(), _events(), evidence_complete=True, evidence_cutoff=_CUTOFF
    )[0]

    assert finding["resource"]["uid"] == "deployment-uid"
    assert finding["affected_pod"]["uid"] == "pod-uid"
    assert finding["container"] == "api"
    assert finding["probe"]["mechanism"] == "httpGet"
    assert finding["causality"] == "candidate_only"
    assert finding["decision"] == "hold"


def test_liveness_failure_abstains_on_truncated_or_stale_evidence() -> None:
    stale = _events()
    stale[0]["last_seen"] = "2026-08-04T11:40:00Z"
    assert not liveness_probe_failure_findings(
        _resources(), _events(), evidence_complete=False, evidence_cutoff=_CUTOFF
    )
    assert not liveness_probe_failure_findings(
        _resources(), stale, evidence_complete=True, evidence_cutoff=_CUTOFF
    )


def test_liveness_failure_abstains_on_uid_conflict_or_future_event() -> None:
    conflict = _events()
    conflict[0]["regarding"]["uid"] = "replacement-uid"  # type: ignore[index]
    future = _events()
    future[0]["last_seen"] = (_CUTOFF + timedelta(seconds=1)).isoformat()
    assert not liveness_probe_failure_findings(
        _resources(), conflict, evidence_complete=True, evidence_cutoff=_CUTOFF
    )
    assert not liveness_probe_failure_findings(
        _resources(), future, evidence_complete=True, evidence_cutoff=_CUTOFF
    )


def test_liveness_failure_abstains_on_probe_drift_or_ambiguity() -> None:
    drift = deepcopy(_resources())
    drift[1]["pod_template"]["containers"][0]["liveness_probe"][  # type: ignore[index]
        "definition_sha256"
    ] = _digest("changed")
    ambiguous = deepcopy(_resources())
    for resource in ambiguous:
        spec_key = "pod_spec" if resource["kind"] == "Pod" else "pod_template"
        resource[spec_key]["containers"].append(  # type: ignore[index]
            {"name": "sidecar", "liveness_probe": _probe("sidecar")}
        )
    assert not liveness_probe_failure_findings(
        drift, _events(), evidence_complete=True, evidence_cutoff=_CUTOFF
    )
    assert not liveness_probe_failure_findings(
        ambiguous, _events(), evidence_complete=True, evidence_cutoff=_CUTOFF
    )


def test_liveness_failure_is_metamorphic_to_order_and_namespace_rename() -> None:
    expected = liveness_probe_failure_findings(
        _resources(), _events(), evidence_complete=True, evidence_cutoff=_CUTOFF
    )
    resources = deepcopy(_resources())
    events = deepcopy(_events())
    for resource in resources:
        resource["namespace"] = "renamed-app"
    events[0]["namespace"] = "renamed-app"
    assert (
        liveness_probe_failure_findings(
            list(reversed(_resources())),
            list(reversed(_events())),
            evidence_complete=True,
            evidence_cutoff=_CUTOFF,
        )
        == expected
    )
    renamed = liveness_probe_failure_findings(
        resources, events, evidence_complete=True, evidence_cutoff=_CUTOFF
    )
    assert renamed[0]["resource"]["namespace"] == "renamed-app"


def _resources() -> list[dict[str, object]]:
    return [
        {
            "kind": "Pod",
            "namespace": "example-app",
            "name": "api-1",
            "uid": "pod-uid",
            "owner_reference_projection_complete": True,
            "owner_references": [
                {"kind": "ReplicaSet", "name": "api-rs", "uid": "rs-uid", "controller": True}
            ],
            "pod_spec": {
                "projection_complete": True,
                "containers": [{"name": "api", "liveness_probe": _probe("api")}],
            },
        },
        {
            "kind": "ReplicaSet",
            "namespace": "example-app",
            "name": "api-rs",
            "uid": "rs-uid",
            "owner_reference_projection_complete": True,
            "owner_references": [
                {"kind": "Deployment", "name": "api", "uid": "deployment-uid", "controller": True}
            ],
            "pod_template": {
                "projection_complete": True,
                "containers": [{"name": "api", "liveness_probe": _probe("api")}],
            },
        },
        {
            "kind": "Deployment",
            "namespace": "example-app",
            "name": "api",
            "uid": "deployment-uid",
            "desired": 1,
            "ready": 0,
            "pod_template": {
                "projection_complete": True,
                "containers": [{"name": "api", "liveness_probe": _probe("api")}],
            },
        },
    ]


def _events() -> list[dict[str, object]]:
    return [
        {
            "name": "liveness-1",
            "namespace": "example-app",
            "code": "liveness_probe_failed",
            "last_seen": "2026-08-04T11:59:00Z",
            "regarding": {"kind": "Pod", "name": "api-1", "uid": "pod-uid"},
        }
    ]


def _probe(value: str) -> dict[str, object]:
    return {
        "mechanism": "httpGet",
        "definition_sha256": _digest(value),
        "period_seconds": 10,
        "failure_threshold": 3,
    }


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()
