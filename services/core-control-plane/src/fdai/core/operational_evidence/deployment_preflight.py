"""Deployment preflight for the operational evidence verifier workload.

The verifier can start in a deployed venue only when its principal is outside the
complete executor-class anchor set. The set is built from explicit deployment
inputs; missing, empty, duplicate, or ambiguous inputs are refused rather than
silently shrinking the set.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass


class VerifierDeploymentPreflightError(RuntimeError):
    """The verifier workload deployment preflight failed closed."""


@dataclass(frozen=True, slots=True)
class ExecutorClassAnchorInputs:
    """Explicit executor-class principals supplied by deployment rendering."""

    core_runtime_executor: str
    isolated_executor: str
    dev_operations_gateway_executor: str
    vertical_effect_executors: tuple[str, ...]
    deploy_runner: str


def build_executor_class_anchor_set(inputs: ExecutorClassAnchorInputs) -> frozenset[str]:
    """Return the complete executor-class principal set or raise on ambiguity."""

    labeled: dict[str, str] = {
        "core_runtime_executor": inputs.core_runtime_executor,
        "isolated_executor": inputs.isolated_executor,
        "dev_operations_gateway_executor": inputs.dev_operations_gateway_executor,
        "deploy_runner": inputs.deploy_runner,
    }
    if not inputs.vertical_effect_executors:
        raise VerifierDeploymentPreflightError("vertical effect executor principals are missing")
    for index, principal in enumerate(inputs.vertical_effect_executors):
        labeled[f"vertical_effect_executor[{index}]"] = principal
    normalized: dict[str, str] = {}
    for label, principal in labeled.items():
        value = principal.strip()
        if not value:
            raise VerifierDeploymentPreflightError(f"{label} principal is missing")
        if value in normalized:
            raise VerifierDeploymentPreflightError(
                f"{label} duplicates {normalized[value]} principal"
            )
        normalized[value] = label
    return frozenset(normalized)


def assert_verifier_not_executor_class(
    *,
    verifier_principal: str,
    executor_class_principals: Iterable[str],
) -> None:
    """Refuse a verifier principal that equals any executor-class principal."""

    verifier = verifier_principal.strip()
    if not verifier:
        raise VerifierDeploymentPreflightError("verifier principal is missing")
    anchors = frozenset(principal.strip() for principal in executor_class_principals if principal)
    if verifier in anchors:
        raise VerifierDeploymentPreflightError(
            "operational evidence verifier principal equals an executor-class principal"
        )


def executor_class_anchor_report(inputs: ExecutorClassAnchorInputs) -> Mapping[str, str]:
    """Return a content-free report suitable for deployment preflight logs."""

    anchors = build_executor_class_anchor_set(inputs)
    return {
        "executor_class_anchor_count": str(len(anchors)),
        "core_runtime_executor": "bound",
        "isolated_executor": "bound",
        "dev_operations_gateway_executor": "bound",
        "vertical_effect_executors": str(len(inputs.vertical_effect_executors)),
        "deploy_runner": "bound",
    }


__all__ = [
    "ExecutorClassAnchorInputs",
    "VerifierDeploymentPreflightError",
    "assert_verifier_not_executor_class",
    "build_executor_class_anchor_set",
    "executor_class_anchor_report",
]
