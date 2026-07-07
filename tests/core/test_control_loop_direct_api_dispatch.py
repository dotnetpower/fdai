"""Wave W2.3 composition wire - ControlLoop routes direct_api actions.

Verifies:

- When ``direct_api_executor`` is not wired, every action goes through
  the PR-native ``ShadowExecutor`` regardless of the ActionType's
  ``execution_path`` (backward-compatible default).
- When ``direct_api_executor`` IS wired AND the ActionType declares
  ``execution_path == direct_api``, the direct-API sibling receives the
  dispatch call.
- When ``direct_api_executor`` IS wired BUT the ActionType stays on
  ``execution_path == pr_native``, the PR sibling still receives it.
- ``_is_execution_success`` recognizes the direct-API success outcomes.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from aiopspilot.core.control_loop import ControlLoop, _is_execution_success
from aiopspilot.core.executor import ExecutionResult, ExecutorOutcome
from aiopspilot.core.executor.direct_api import (
    DirectApiExecutionOutcome,
    DirectApiExecutionResult,
)
from aiopspilot.shared.contracts.models import (
    Action,
    ActionBlastRadius,
    ActionInterface,
    BlastRadiusComputation,
    BlastRadiusScope,
    ExecutionPath,
    Mode,
    OntologyActionType,
    Operation,
    PromotionGate,
    RollbackKind,
    Rule,
)


def _action_type(
    *,
    name: str = "ops.scale-out",
    execution_path: ExecutionPath | None = ExecutionPath.DIRECT_API,
) -> OntologyActionType:
    return OntologyActionType(
        schema_version="1.0.0",
        name=name,
        version="1.0.0",
        operation=Operation.SCALE,
        interfaces=[ActionInterface.CONTROL_PLANE],
        rollback_contract=RollbackKind.STATE_FORWARD_ONLY,
        irreversible=True,
        promotion_gate=PromotionGate(
            min_shadow_days=1, min_samples=1, min_accuracy=0.9, max_policy_escapes=0
        ),
        blast_radius=ActionBlastRadius(
            computation=BlastRadiusComputation.STATIC_ENUM,
            static_bucket=BlastRadiusScope.RESOURCE,
        ),
        execution_path=execution_path,
    )


def _action(action_type_name: str = "ops.scale-out") -> Action:
    return Action.model_validate(
        {
            "schema_version": "1.0.0",
            "action_id": "00000000-0000-0000-0000-000000000010",
            "idempotency_key": "example-action-1",
            "event_id": "00000000-0000-0000-0000-000000000001",
            "action_type": action_type_name,
            "target_resource_ref": "resource:example/rg/vm-a",
            "operation": "scale",
            "params": {},
            "stop_condition": "provider_api_error_streak",
            "rollback_ref": {"kind": "state_forward_only"},
            "blast_radius": {"scope": "resource", "count": 1, "rate_per_minute": 5},
            "mode": "shadow",
            "citing_rules": ["example.rule.x"],
            "created_at": "2026-07-07T00:00:00Z",
        }
    )


def _rule() -> Rule:
    return Rule.model_validate(
        {
            "schema_version": "1.0.0",
            "id": "example.rule.x",
            "version": "1.0.0",
            "source": "custom",
            "severity": "low",
            "category": "config_drift",
            "resource_type": "compute.vm",
            "check_logic": {"kind": "rego", "reference": "policies/example/x.rego"},
            "remediation": {"template_ref": "remediations/example-x"},
            "remediates": "ops.scale-out",
            "provenance": {
                "source_url": "https://example.com/x",
                "resolved_ref": "0000000000000000000000000000000000000000",
                "content_hash": "sha256:example",
                "license": "MIT",
                "redistribution": "embeddable",
                "retrieved_at": "2026-07-05T00:00:00Z",
            },
        }
    )


def _make_loop(
    *,
    pr_executor: MagicMock,
    direct_api_executor: MagicMock | None = None,
    action_types_by_name: dict[str, OntologyActionType] | None = None,
) -> ControlLoop:
    return ControlLoop(
        event_ingest=MagicMock(),
        trust_router=MagicMock(),
        t0_engine=MagicMock(),
        action_builder=MagicMock(),
        executor=pr_executor,
        audit_store=MagicMock(),
        rules_by_id={"example.rule.x": _rule()},
        action_types_by_name=action_types_by_name,
        direct_api_executor=direct_api_executor,
    )


# ---------------------------------------------------------------------------
# _dispatch_action routing
# ---------------------------------------------------------------------------


async def test_default_uses_pr_executor_only() -> None:
    """No direct_api_executor wired -> every action goes to the PR path."""

    pr_result = ExecutionResult(
        action_id="00000000-0000-0000-0000-000000000010",
        outcome=ExecutorOutcome.PUBLISHED,
    )
    pr_exec = MagicMock()
    pr_exec.execute = AsyncMock(return_value=pr_result)

    loop = _make_loop(pr_executor=pr_exec, direct_api_executor=None)
    got = await loop._dispatch_action(action=_action(), rule=_rule())

    assert got is pr_result
    pr_exec.execute.assert_awaited_once()


async def test_direct_api_executor_selected_when_action_type_opts_in() -> None:
    pr_exec = MagicMock()
    pr_exec.execute = AsyncMock()

    da_result = DirectApiExecutionResult(
        action_id="00000000-0000-0000-0000-000000000010",
        outcome=DirectApiExecutionOutcome.DISPATCHED,
    )
    da_exec = MagicMock()
    da_exec.execute = AsyncMock(return_value=da_result)

    at = _action_type(execution_path=ExecutionPath.DIRECT_API)
    loop = _make_loop(
        pr_executor=pr_exec,
        direct_api_executor=da_exec,
        action_types_by_name={"ops.scale-out": at},
    )
    got = await loop._dispatch_action(action=_action(), rule=_rule())

    assert got is da_result
    da_exec.execute.assert_awaited_once()
    pr_exec.execute.assert_not_called()


async def test_direct_api_executor_bypassed_when_action_type_stays_pr_native() -> None:
    pr_result = ExecutionResult(
        action_id="00000000-0000-0000-0000-000000000010",
        outcome=ExecutorOutcome.PUBLISHED,
    )
    pr_exec = MagicMock()
    pr_exec.execute = AsyncMock(return_value=pr_result)

    da_exec = MagicMock()
    da_exec.execute = AsyncMock()

    at = _action_type(execution_path=ExecutionPath.PR_NATIVE)
    loop = _make_loop(
        pr_executor=pr_exec,
        direct_api_executor=da_exec,
        action_types_by_name={"ops.scale-out": at},
    )
    got = await loop._dispatch_action(action=_action(), rule=_rule())

    assert got is pr_result
    pr_exec.execute.assert_awaited_once()
    da_exec.execute.assert_not_called()


async def test_direct_api_executor_bypassed_when_action_type_missing_from_map() -> None:
    """An action whose ActionType is not registered falls through to PR-native.

    This mirrors the ``_evaluate_and_audit`` behaviour where an unknown
    ActionType skips the authority pipeline; the executor selection
    keeps the same conservative default.
    """

    pr_result = ExecutionResult(
        action_id="00000000-0000-0000-0000-000000000010",
        outcome=ExecutorOutcome.PUBLISHED,
    )
    pr_exec = MagicMock()
    pr_exec.execute = AsyncMock(return_value=pr_result)

    da_exec = MagicMock()
    da_exec.execute = AsyncMock()

    loop = _make_loop(
        pr_executor=pr_exec,
        direct_api_executor=da_exec,
        action_types_by_name={},  # empty map -> ActionType not found
    )
    got = await loop._dispatch_action(action=_action(), rule=_rule())

    assert got is pr_result
    da_exec.execute.assert_not_called()


async def test_direct_api_executor_bypassed_when_execution_path_absent() -> None:
    """An ActionType with ``execution_path=None`` (pre-F1 shape) stays on PR."""

    pr_result = ExecutionResult(
        action_id="00000000-0000-0000-0000-000000000010",
        outcome=ExecutorOutcome.PUBLISHED,
    )
    pr_exec = MagicMock()
    pr_exec.execute = AsyncMock(return_value=pr_result)

    da_exec = MagicMock()
    da_exec.execute = AsyncMock()

    at = _action_type(execution_path=None)
    loop = _make_loop(
        pr_executor=pr_exec,
        direct_api_executor=da_exec,
        action_types_by_name={"ops.scale-out": at},
    )
    got = await loop._dispatch_action(action=_action(), rule=_rule())

    assert got is pr_result
    da_exec.execute.assert_not_called()


# ---------------------------------------------------------------------------
# _is_execution_success matrix
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "outcome, expected",
    [
        (ExecutorOutcome.PUBLISHED, True),
        (ExecutorOutcome.ALREADY_EXISTED, True),
        (ExecutorOutcome.ABSTAINED_BLAST_RADIUS, False),
        (ExecutorOutcome.ABSTAINED_RENDER_ERROR, False),
        (ExecutorOutcome.REJECTED_MODE, False),
        (ExecutorOutcome.REJECTED_INVARIANT, False),
    ],
)
def test_is_execution_success_for_pr_native_outcomes(
    outcome: ExecutorOutcome, expected: bool
) -> None:
    result = ExecutionResult(action_id="a", outcome=outcome, mode=Mode.SHADOW)
    assert _is_execution_success(result) is expected


@pytest.mark.parametrize(
    "outcome, expected",
    [
        (DirectApiExecutionOutcome.DISPATCHED, True),
        (DirectApiExecutionOutcome.ALREADY_APPLIED, True),
        (DirectApiExecutionOutcome.ABSTAINED_BLAST_RADIUS, False),
        (DirectApiExecutionOutcome.ABSTAINED_PRECONDITION, False),
        (DirectApiExecutionOutcome.STOPPED, False),
        (DirectApiExecutionOutcome.FAILED, False),
        (DirectApiExecutionOutcome.REJECTED_MODE, False),
        (DirectApiExecutionOutcome.REJECTED_INVARIANT, False),
    ],
)
def test_is_execution_success_for_direct_api_outcomes(
    outcome: DirectApiExecutionOutcome, expected: bool
) -> None:
    result = DirectApiExecutionResult(action_id="a", outcome=outcome, mode=Mode.SHADOW)
    assert _is_execution_success(result) is expected


def test_is_execution_success_none_returns_false() -> None:
    assert _is_execution_success(None) is False


def test_is_execution_success_arbitrary_object_without_outcome_returns_false() -> None:
    class _Dummy:
        pass

    assert _is_execution_success(_Dummy()) is False  # type: ignore[arg-type]


# Kept to document the sole intended entry point for the routing method
# so tests / greppers can find it via a stable Any reference.
_ = Any
