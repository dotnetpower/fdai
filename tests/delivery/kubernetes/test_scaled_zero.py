"""Scaled-to-zero backend candidate tests."""

from __future__ import annotations

from copy import deepcopy

from fdai.delivery.kubernetes.scaled_zero import scaled_zero_backend_findings


def test_scaled_zero_requires_complete_endpoint_and_exact_selector_join() -> None:
    finding = scaled_zero_backend_findings(_resources(), evidence_complete=True)[0]
    assert finding["reason"] == "service_backend_scaled_to_zero_candidate"
    assert finding["decision"] == "hold"


def test_scaled_zero_abstains_on_truncated_or_ready_endpoint_evidence() -> None:
    ready = deepcopy(_resources())
    ready[0]["ready_endpoints"] = 1
    assert not scaled_zero_backend_findings(_resources(), evidence_complete=False)
    assert not scaled_zero_backend_findings(ready, evidence_complete=True)


def test_scaled_zero_abstains_on_selector_mismatch_or_nonzero_replicas() -> None:
    mismatch = deepcopy(_resources())
    mismatch[1]["pod_template"]["labels"] = {"app": "other"}  # type: ignore[index]
    running = deepcopy(_resources())
    running[1]["desired"] = 1
    assert not scaled_zero_backend_findings(mismatch, evidence_complete=True)
    assert not scaled_zero_backend_findings(running, evidence_complete=True)


def test_scaled_zero_abstains_on_ambiguous_or_incomplete_projection() -> None:
    ambiguous = deepcopy(_resources())
    ambiguous.append(deepcopy(ambiguous[1]))
    incomplete = deepcopy(_resources())
    incomplete[0]["endpoint_projection_complete"] = False
    assert not scaled_zero_backend_findings(ambiguous, evidence_complete=True)
    assert not scaled_zero_backend_findings(incomplete, evidence_complete=True)


def test_scaled_zero_is_metamorphic_to_order_and_namespace_rename() -> None:
    expected = scaled_zero_backend_findings(_resources(), evidence_complete=True)
    renamed = deepcopy(_resources())
    for resource in renamed:
        resource["namespace"] = "renamed-app"
    assert (
        scaled_zero_backend_findings(list(reversed(_resources())), evidence_complete=True)
        == expected
    )
    assert (
        scaled_zero_backend_findings(renamed, evidence_complete=True)[0]["resource"]["namespace"]
        == "renamed-app"
    )


def _resources() -> list[dict[str, object]]:
    return [
        {
            "kind": "Service",
            "namespace": "example-app",
            "name": "api",
            "service_type": "ClusterIP",
            "selector_projection_complete": True,
            "selector": {"app": "api"},
            "endpoint_projection_complete": True,
            "ready_endpoints": 0,
        },
        {
            "kind": "Deployment",
            "namespace": "example-app",
            "name": "api",
            "desired": 0,
            "pod_template": {"label_projection_complete": True, "labels": {"app": "api"}},
        },
    ]
