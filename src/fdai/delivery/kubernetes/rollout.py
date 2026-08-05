"""Kubernetes rolling update availability candidates."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


def zero_availability_rollout_findings(
    resources: Sequence[Mapping[str, Any]], *, evidence_complete: bool
) -> tuple[dict[str, Any], ...]:
    """Identify degraded rollouts whose declared strategy permits zero availability."""

    if not evidence_complete:
        return ()
    findings: list[dict[str, Any]] = []
    for deployment in sorted(resources, key=_identity):
        strategy = deployment.get("strategy")
        desired = _integer(deployment.get("desired"))
        ready = _integer(deployment.get("ready"))
        available = _integer(deployment.get("available"))
        if (
            deployment.get("kind") != "Deployment"
            or deployment.get("strategy_projection_complete") is not True
            or not isinstance(strategy, Mapping)
            or strategy.get("type") != "RollingUpdate"
            or desired <= 0
            or ready >= desired
            or available != 0
            or not _covers_all(strategy.get("max_unavailable"), desired)
            or not _zero(strategy.get("max_surge"))
        ):
            continue
        findings.append(
            {
                "reason": "deployment_zero_availability_rollout_candidate",
                "resource": {
                    "kind": "Deployment",
                    "namespace": str(deployment.get("namespace") or "")[:253],
                    "name": str(deployment.get("name") or "")[:253],
                },
                "desired": desired,
                "ready": ready,
                "available": available,
                "max_unavailable": strategy.get("max_unavailable"),
                "max_surge": strategy.get("max_surge"),
                "source_paths": [
                    "/spec/strategy/rollingUpdate/maxSurge",
                    "/spec/strategy/rollingUpdate/maxUnavailable",
                ],
                "evidence_strength": "complete_strategy_and_degraded_rollout",
                "causality": "candidate_only",
                "decision": "hold",
            }
        )
    return tuple(findings[:32])


def _covers_all(value: object, desired: int) -> bool:
    if isinstance(value, int) and not isinstance(value, bool):
        return value >= desired
    if isinstance(value, str) and value.endswith("%") and value[:-1].isdigit():
        return int(value[:-1]) >= 100
    return False


def _zero(value: object) -> bool:
    return value == 0 or value == "0" or value == "0%"


def _integer(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else -1


def _identity(value: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        str(value.get("kind") or ""),
        str(value.get("namespace") or ""),
        str(value.get("name") or ""),
    )


__all__ = ["zero_availability_rollout_findings"]
