"""ControlLoop routes tool_call actions to the ToolCallShadowExecutor.

Sibling of ``test_control_loop_direct_api_dispatch.py``. Verifies:

- When ``tool_executor`` is not wired, every action goes through the
  PR-native ``ShadowExecutor`` regardless of ``execution_path``.
- When ``tool_executor`` IS wired AND the ActionType declares
  ``execution_path == tool_call``, the tool-call sibling receives it.
- When ``tool_executor`` IS wired BUT the ActionType stays on
  ``pr_native``, the PR sibling still receives it.
- ``_is_execution_success`` recognizes the tool-call success outcomes.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from fdai.core.control_loop import ControlLoop, _is_execution_success
from fdai.core.executor import ExecutionResult, ExecutorOutcome
from fdai.core.executor.tool_call import (
    ToolCallExecutionOutcome,
    ToolCallExecutionResult,
)
from fdai.shared.contracts.models import (
    Action,
    ActionBlastRadius,
    ActionInterface,
    BlastRadiusComputation,
    BlastRadiusScope,
    ExecutionPath,
    OntologyActionType,
    Operation,
    PromotionGate,
    RollbackKind,
    Rule,
)


def _action_type(
    *,
    name: str = "tool.generate-pdf",
    execution_path: ExecutionPath | None = ExecutionPath.TOOL_CALL,
) -> OntologyActionType:
    return OntologyActionType(
        schema_version="1.0.0",
        name=name,
        version="1.0.0",
        operation=Operation.CREATE,
        interfaces=[ActionInterface.IDEMPOTENT_BY_KEY],
        rollback_contract=RollbackKind.STATE_FORWARD_ONLY,
        irreversible=False,
        promotion_gate=PromotionGate(
            min_shadow_days=1, min_samples=1, min_accuracy=0.9, max_policy_escapes=0
        ),
        blast_radius=ActionBlastRadius(
            computation=BlastRadiusComputation.STATIC_ENUM,
            static_bucket=BlastRadiusScope.RESOURCE,
        ),
        execution_path=execution_path,
    )


def _action(action_type_name: str = "tool.generate-pdf") -> Action:
    return Action.model_validate(
        {
            "schema_version": "1.0.0",
            "action_id": "00000000-0000-0000-0000-000000000010",
            "idempotency_key": "example-action-1",
            "event_id": "00000000-0000-0000-0000-000000000001",
            "action_type": action_type_name,
            "target_resource_ref": "document:reports/example",
            "operation": "create",
            "params": {},
            "stop_condition": "render_time_box_exceeded",
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
            "remediates": "tool.generate-pdf",
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
    tool_executor: MagicMock | None = None,
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
        tool_executor=tool_executor,
    )


async def test_default_uses_pr_executor_when_no_tool_executor() -> None:
    pr_result = ExecutionResult(
        action_id="00000000-0000-0000-0000-000000000010",
        outcome=ExecutorOutcome.PUBLISHED,
    )
    pr_exec = MagicMock()
    pr_exec.execute = AsyncMock(return_value=pr_result)

    loop = _make_loop(pr_executor=pr_exec, tool_executor=None)
    got = await loop._dispatch_action(action=_action(), rule=_rule())

    assert got is pr_result
    pr_exec.execute.assert_awaited_once()


async def test_tool_executor_selected_when_action_type_opts_in() -> None:
    pr_exec = MagicMock()
    pr_exec.execute = AsyncMock()

    tc_result = ToolCallExecutionResult(
        action_id="00000000-0000-0000-0000-000000000010",
        outcome=ToolCallExecutionOutcome.DISPATCHED,
    )
    tc_exec = MagicMock()
    tc_exec.execute = AsyncMock(return_value=tc_result)

    at = _action_type(execution_path=ExecutionPath.TOOL_CALL)
    loop = _make_loop(
        pr_executor=pr_exec,
        tool_executor=tc_exec,
        action_types_by_name={"tool.generate-pdf": at},
    )
    got = await loop._dispatch_action(action=_action(), rule=_rule())

    assert got is tc_result
    tc_exec.execute.assert_awaited_once()
    pr_exec.execute.assert_not_called()


async def test_tool_executor_bypassed_when_action_type_stays_pr_native() -> None:
    pr_result = ExecutionResult(
        action_id="00000000-0000-0000-0000-000000000010",
        outcome=ExecutorOutcome.PUBLISHED,
    )
    pr_exec = MagicMock()
    pr_exec.execute = AsyncMock(return_value=pr_result)

    tc_exec = MagicMock()
    tc_exec.execute = AsyncMock()

    at = _action_type(execution_path=ExecutionPath.PR_NATIVE)
    loop = _make_loop(
        pr_executor=pr_exec,
        tool_executor=tc_exec,
        action_types_by_name={"tool.generate-pdf": at},
    )
    got = await loop._dispatch_action(action=_action(), rule=_rule())

    assert got is pr_result
    pr_exec.execute.assert_awaited_once()
    tc_exec.execute.assert_not_called()


async def test_tool_call_action_without_executor_warns_and_falls_back(caplog) -> None:
    """A tool_call ActionType with no tool executor wired falls back to
    the PR path and logs a warning so the mismatch is observable."""
    import logging

    pr_result = ExecutionResult(
        action_id="00000000-0000-0000-0000-000000000010",
        outcome=ExecutorOutcome.PUBLISHED,
    )
    pr_exec = MagicMock()
    pr_exec.execute = AsyncMock(return_value=pr_result)

    at = _action_type(execution_path=ExecutionPath.TOOL_CALL)
    loop = _make_loop(
        pr_executor=pr_exec,
        tool_executor=None,
        action_types_by_name={"tool.generate-pdf": at},
    )
    with caplog.at_level(logging.WARNING):
        got = await loop._dispatch_action(action=_action(), rule=_rule())

    assert got is pr_result
    pr_exec.execute.assert_awaited_once()
    assert any("no matching executor is wired" in r.message for r in caplog.records)


def test_is_execution_success_for_tool_call_outcomes() -> None:
    for outcome in (
        ToolCallExecutionOutcome.DISPATCHED,
        ToolCallExecutionOutcome.ALREADY_APPLIED,
    ):
        result = ToolCallExecutionResult(action_id="x", outcome=outcome)
        assert _is_execution_success(result) is True
    for outcome in (
        ToolCallExecutionOutcome.ABSTAINED_BLAST_RADIUS,
        ToolCallExecutionOutcome.REJECTED_MODE,
        ToolCallExecutionOutcome.FAILED,
    ):
        result = ToolCallExecutionResult(action_id="x", outcome=outcome)
        assert _is_execution_success(result) is False
