"""Deployed verifier preflight refuses missing or ambiguous executor anchors."""

from __future__ import annotations

import pytest
from fdai.core.operational_evidence.deployment_preflight import (
    ExecutorClassAnchorInputs,
    VerifierDeploymentPreflightError,
    assert_verifier_not_executor_class,
    build_executor_class_anchor_set,
)


def _inputs(**overrides: object) -> ExecutorClassAnchorInputs:
    values = {
        "core_runtime_executor": "core-executor",
        "isolated_executor": "isolated-executor",
        "dev_operations_gateway_executor": "dev-gateway-executor",
        "vertical_effect_executors": ("change-executor", "resilience-executor", "finops-executor"),
        "deploy_runner": "deploy-runner",
    }
    values.update(overrides)
    return ExecutorClassAnchorInputs(**values)  # type: ignore[arg-type]


def test_build_executor_class_anchor_set_requires_every_explicit_input() -> None:
    anchors = build_executor_class_anchor_set(_inputs())
    assert anchors == {
        "core-executor",
        "isolated-executor",
        "dev-gateway-executor",
        "change-executor",
        "resilience-executor",
        "finops-executor",
        "deploy-runner",
    }
    with pytest.raises(VerifierDeploymentPreflightError, match="vertical effect"):
        build_executor_class_anchor_set(_inputs(vertical_effect_executors=()))
    with pytest.raises(VerifierDeploymentPreflightError, match="core_runtime_executor"):
        build_executor_class_anchor_set(_inputs(core_runtime_executor=""))
    with pytest.raises(VerifierDeploymentPreflightError, match="duplicates"):
        build_executor_class_anchor_set(_inputs(isolated_executor="core-executor"))


def test_verifier_principal_must_not_equal_any_executor_anchor() -> None:
    anchors = build_executor_class_anchor_set(_inputs())
    assert_verifier_not_executor_class(
        verifier_principal="operational-evidence-verifier",
        executor_class_principals=anchors,
    )
    with pytest.raises(VerifierDeploymentPreflightError, match="executor-class"):
        assert_verifier_not_executor_class(
            verifier_principal="deploy-runner",
            executor_class_principals=anchors,
        )
