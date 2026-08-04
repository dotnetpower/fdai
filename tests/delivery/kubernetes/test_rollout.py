"""Rolling update availability candidate tests."""

from __future__ import annotations

from copy import deepcopy

from fdai.delivery.kubernetes.rollout import zero_availability_rollout_findings


def test_zero_availability_rollout_requires_complete_degraded_strategy() -> None:
    finding = zero_availability_rollout_findings([_deployment()], evidence_complete=True)[0]
    assert finding["reason"] == "deployment_zero_availability_rollout_candidate"
    assert finding["decision"] == "hold"


def test_zero_availability_rollout_abstains_on_truncated_or_healthy_evidence() -> None:
    healthy = _deployment()
    healthy["ready"] = 2
    healthy["available"] = 2
    assert not zero_availability_rollout_findings([_deployment()], evidence_complete=False)
    assert not zero_availability_rollout_findings([healthy], evidence_complete=True)


def test_zero_availability_rollout_abstains_on_safe_or_incomplete_strategy() -> None:
    safe = _deployment()
    safe["strategy"] = {"type": "RollingUpdate", "max_unavailable": 1, "max_surge": 1}
    incomplete = _deployment()
    incomplete["strategy_projection_complete"] = False
    assert not zero_availability_rollout_findings([safe], evidence_complete=True)
    assert not zero_availability_rollout_findings([incomplete], evidence_complete=True)


def test_zero_availability_rollout_handles_percent_and_rejects_malformed_values() -> None:
    percent = _deployment()
    percent["strategy"] = {"type": "RollingUpdate", "max_unavailable": "100%", "max_surge": "0%"}
    malformed = _deployment()
    malformed["strategy"] = {"type": "RollingUpdate", "max_unavailable": "all", "max_surge": 0}
    assert zero_availability_rollout_findings([percent], evidence_complete=True)
    assert not zero_availability_rollout_findings([malformed], evidence_complete=True)


def test_zero_availability_rollout_is_metamorphic_to_order_and_namespace_rename() -> None:
    noise = {"kind": "Service", "namespace": "example-app", "name": "api"}
    expected = zero_availability_rollout_findings([_deployment(), noise], evidence_complete=True)
    renamed = deepcopy(_deployment())
    renamed["namespace"] = "renamed-app"
    assert (
        zero_availability_rollout_findings([noise, _deployment()], evidence_complete=True)
        == expected
    )
    assert (
        zero_availability_rollout_findings([renamed], evidence_complete=True)[0]["resource"][
            "namespace"
        ]
        == "renamed-app"
    )


def _deployment() -> dict[str, object]:
    return {
        "kind": "Deployment",
        "namespace": "example-app",
        "name": "api",
        "desired": 2,
        "ready": 1,
        "available": 0,
        "strategy_projection_complete": True,
        "strategy": {"type": "RollingUpdate", "max_unavailable": 2, "max_surge": 0},
    }
