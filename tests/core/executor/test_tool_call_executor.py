"""ToolCallShadowExecutor - safety-invariant contract tests.

Sibling of ``test_direct_api_executor.py`` for the ``tool_call``
execution path. Same six invariants apply:

- shadow-mode NEVER lets an enforce-mode Action reach the adapter.
- Every terminal path writes exactly one audit entry with
  ``action_kind`` starting with ``executor.tool_call.``.
- Idempotent by ``Action.idempotency_key`` at TWO layers (in-process
  dedupe + adapter ledger); the ALREADY_APPLIED outcome round-trips.
- Blast-radius over cap -> abstain + audit.
- Adapter error / STOPPED / precondition failure -> distinct outcomes;
  rollback_succeeded flows through to audit.
- Missing safety-invariant fields -> REJECTED_INVARIANT.
"""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID

import pytest

from fdai.core.executor import (
    ExecutorConfig,
    ResourceLockManager,
    ToolCallExecutionOutcome,
    ToolCallExecutionResult,
    ToolCallShadowExecutor,
)
from fdai.shared.contracts.models import (
    Action,
    BlastRadius,
    BlastRadiusScope,
    Mode,
    Operation,
    RollbackKind,
    RollbackRef,
)
from fdai.shared.providers.testing import (
    InMemoryStateStore,
    RecordingToolExecutor,
)
from fdai.shared.providers.tool import (
    ToolCallOutcome,
    ToolCallReceipt,
    ToolCallRequest,
    ToolError,
    ToolPreconditionError,
)


def _action(
    *,
    action_id: str = "00000000-0000-0000-0000-000000000010",
    idempotency_key: str = "example-idem",
    target: str = "document:reports/resilience/2026-07",
    mode: Mode = Mode.SHADOW,
    count: int | None = 1,
    rate: int | None = 5,
    citing_rules: tuple[str, ...] = ("tool.generate-pdf",),
    params: dict[str, Any] | None = None,
    stop_condition: str = "render_time_box_exceeded",
) -> Action:
    return Action(
        schema_version="1.0.0",
        action_id=UUID(action_id),
        idempotency_key=idempotency_key,
        event_id=UUID("00000000-0000-0000-0000-000000000011"),
        action_type="tool.generate-pdf",
        target_resource_ref=target,
        operation=Operation.CREATE,
        params=params or {"report_kind": "resilience_summary", "window_days": 30},
        stop_condition=stop_condition,
        rollback_ref=RollbackRef(kind=RollbackKind.STATE_FORWARD_ONLY, reference="delete-artifact"),
        blast_radius=BlastRadius(
            scope=BlastRadiusScope.RESOURCE, count=count, rate_per_minute=rate
        ),
        mode=mode,
        citing_rules=list(citing_rules),
        created_at="2026-07-05T08:00:00Z",  # type: ignore[arg-type]
    )


def _executor(
    **overrides: Any,
) -> tuple[ToolCallShadowExecutor, RecordingToolExecutor, InMemoryStateStore]:
    adapter = RecordingToolExecutor()
    audit = InMemoryStateStore()
    exec_ = ToolCallShadowExecutor(
        executor=adapter,
        audit_store=audit,
        resource_lock=ResourceLockManager(),
        config=ExecutorConfig(**overrides) if overrides else None,
    )
    return exec_, adapter, audit


def _unwrap(record: Any) -> dict[str, Any]:
    if isinstance(record, dict):
        inner = record.get("entry")
        if isinstance(inner, dict) and ("previous_hash" in record or "entry_hash" in record):
            return inner
        return record
    return dict(record)


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestHappyPath:
    @pytest.mark.asyncio
    async def test_dispatch_returns_dispatched_and_audits(self) -> None:
        exec_, _adapter, audit = _executor()
        result = await exec_.execute(action=_action())
        assert isinstance(result, ToolCallExecutionResult)
        assert result.outcome is ToolCallExecutionOutcome.DISPATCHED
        assert result.mode is Mode.SHADOW
        assert result.receipt_ref
        entries = list(audit.audit_entries)
        assert len(entries) == 1
        entry = _unwrap(entries[0])
        assert entry["action_kind"] == "executor.tool_call.dispatched"
        assert entry["execution_path"] == "tool_call"
        assert entry["outcome"] == "dispatched"
        assert entry["mode"] == "shadow"
        assert entry["tool_ref"] == "document:reports/resilience/2026-07"

    @pytest.mark.asyncio
    async def test_adapter_receives_shadow_labels_only(self) -> None:
        exec_, adapter, _ = _executor()
        await exec_.execute(action=_action())
        request = adapter.records[0]
        assert request.mode is Mode.SHADOW
        assert "shadow" in request.labels
        assert "enforce" not in request.labels

    @pytest.mark.asyncio
    async def test_action_params_forwarded_as_arguments(self) -> None:
        exec_, adapter, _ = _executor()
        await exec_.execute(action=_action(params={"report_kind": "cost_report", "window_days": 7}))
        request = adapter.records[0]
        assert request.arguments == {"report_kind": "cost_report", "window_days": 7}
        assert request.action_type_name == "tool.generate-pdf"
        assert request.tool_ref == "document:reports/resilience/2026-07"

    @pytest.mark.asyncio
    async def test_successful_receipt_observer_runs_before_terminal_success(self) -> None:
        observed: list[tuple[ToolCallRequest, ToolCallReceipt]] = []

        async def observer(request: ToolCallRequest, receipt: ToolCallReceipt) -> None:
            observed.append((request, receipt))

        adapter = RecordingToolExecutor()
        executor = ToolCallShadowExecutor(
            executor=adapter,
            audit_store=InMemoryStateStore(),
            resource_lock=ResourceLockManager(),
            receipt_observer=observer,
        )

        result = await executor.execute(action=_action())

        assert result.outcome is ToolCallExecutionOutcome.DISPATCHED
        assert len(observed) == 1

    @pytest.mark.asyncio
    async def test_receipt_observer_failure_retries_linkage_on_redelivery(self) -> None:
        calls = 0

        async def observer(request: ToolCallRequest, receipt: ToolCallReceipt) -> None:  # noqa: ARG001
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RuntimeError("injected linkage failure")

        adapter = RecordingToolExecutor()
        executor = ToolCallShadowExecutor(
            executor=adapter,
            audit_store=InMemoryStateStore(),
            resource_lock=ResourceLockManager(),
            receipt_observer=observer,
        )
        action = _action()

        first = await executor.execute(action=action)
        retried = await executor.execute(action=action)

        assert first.outcome is ToolCallExecutionOutcome.FAILED
        assert retried.outcome is ToolCallExecutionOutcome.ALREADY_APPLIED
        assert calls == 2

    @pytest.mark.asyncio
    async def test_explicit_enforce_executor_passes_enforce_request_to_adapter(self) -> None:
        adapter = RecordingToolExecutor()
        audit = InMemoryStateStore()
        executor = ToolCallShadowExecutor(
            executor=adapter,
            audit_store=audit,
            resource_lock=ResourceLockManager(),
            enforce=True,
        )

        result = await executor.execute(action=_action(mode=Mode.ENFORCE))

        assert result.outcome is ToolCallExecutionOutcome.DISPATCHED
        assert result.mode is Mode.ENFORCE
        assert adapter.records[0].mode is Mode.ENFORCE
        assert adapter.records[0].labels == ("enforce",)
        assert _unwrap(list(audit.audit_entries)[0])["mode"] == "enforce"


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


class TestIdempotency:
    @pytest.mark.asyncio
    async def test_second_call_returns_cached_without_hitting_adapter(self) -> None:
        exec_, adapter, audit = _executor()
        r1 = await exec_.execute(action=_action(idempotency_key="dup"))
        r2 = await exec_.execute(action=_action(idempotency_key="dup"))
        assert r2 is r1
        assert len(adapter.records) == 1
        assert len(list(audit.audit_entries)) == 1

    @pytest.mark.asyncio
    async def test_different_keys_dispatch_independently(self) -> None:
        exec_, adapter, audit = _executor()
        await exec_.execute(action=_action(idempotency_key="a"))
        await exec_.execute(action=_action(idempotency_key="b", target="document:reports/b"))
        assert len(adapter.records) == 2
        assert len(list(audit.audit_entries)) == 2

    @pytest.mark.asyncio
    async def test_durable_record_failure_does_not_populate_memory_cache(self) -> None:
        class FailOnceIdempotency:
            def __init__(self) -> None:
                self.records = 0
                self.payload: dict[str, Any] | None = None

            async def seen(self, key: str) -> dict[str, Any] | None:  # noqa: ARG002
                return self.payload

            async def record(self, key: str, result: dict[str, Any]) -> bool:  # noqa: ARG002
                self.records += 1
                if self.records == 1:
                    raise RuntimeError("injected durable write failure")
                self.payload = dict(result)
                return True

        adapter = RecordingToolExecutor()
        durable = FailOnceIdempotency()
        executor = ToolCallShadowExecutor(
            executor=adapter,
            audit_store=InMemoryStateStore(),
            resource_lock=ResourceLockManager(),
            idempotency=durable,
        )
        action = _action()

        with pytest.raises(RuntimeError, match="durable write failure"):
            await executor.execute(action=action)
        retried = await executor.execute(action=action)

        assert retried.outcome is ToolCallExecutionOutcome.ALREADY_APPLIED
        assert len(adapter.records) == 1
        assert durable.records == 2


# ---------------------------------------------------------------------------
# Shadow-mode + invariant refusals
# ---------------------------------------------------------------------------


class TestRefusals:
    @pytest.mark.asyncio
    async def test_enforce_mode_rejected_before_adapter(self) -> None:
        exec_, adapter, audit = _executor()
        result = await exec_.execute(action=_action(mode=Mode.ENFORCE))
        assert result.outcome is ToolCallExecutionOutcome.REJECTED_MODE
        assert len(adapter.records) == 0
        entry = _unwrap(list(audit.audit_entries)[0])
        assert entry["action_kind"] == "executor.tool_call.rejected_mode"

    @pytest.mark.asyncio
    async def test_missing_stop_condition_rejected_invariant(self) -> None:
        """Defense-in-depth: bypass pydantic via ``model_construct`` so the
        executor's own invariant guard is exercised (a valid Action can
        never carry an empty stop_condition)."""
        exec_, adapter, audit = _executor()
        valid = _action()
        bad = Action.model_construct(**{**valid.__dict__, "stop_condition": "  "})
        result = await exec_.execute(action=bad)
        assert result.outcome is ToolCallExecutionOutcome.REJECTED_INVARIANT
        assert len(adapter.records) == 0
        entry = _unwrap(list(audit.audit_entries)[0])
        assert entry["action_kind"] == "executor.tool_call.rejected_invariant"

    @pytest.mark.asyncio
    async def test_blast_radius_over_cap_abstains(self) -> None:
        exec_, adapter, audit = _executor(max_affected_resources=1)
        result = await exec_.execute(action=_action(count=50))
        assert result.outcome is ToolCallExecutionOutcome.ABSTAINED_BLAST_RADIUS
        assert len(adapter.records) == 0
        entry = _unwrap(list(audit.audit_entries)[0])
        assert entry["action_kind"] == "executor.tool_call.abstained_blast_radius"


# ---------------------------------------------------------------------------
# Adapter failure modes
# ---------------------------------------------------------------------------


class TestAdapterFailures:
    @pytest.mark.asyncio
    async def test_cancellation_is_audited_then_reraised(self) -> None:
        class CancelledToolExecutor:
            async def execute(self, request: ToolCallRequest) -> ToolCallReceipt:  # noqa: ARG002
                raise asyncio.CancelledError

        audit = InMemoryStateStore()
        executor = ToolCallShadowExecutor(
            executor=CancelledToolExecutor(),
            audit_store=audit,
            resource_lock=ResourceLockManager(),
        )

        with pytest.raises(asyncio.CancelledError):
            await executor.execute(action=_action())

        entry = _unwrap(list(audit.audit_entries)[0])
        assert entry["action_kind"] == "executor.tool_call.failed"
        assert entry["reason"] == "tool-call execution cancelled"

    @pytest.mark.asyncio
    async def test_precondition_error_abstains(self) -> None:
        exec_, adapter, audit = _executor()
        adapter.next_error(ToolPreconditionError("document target locked"))
        result = await exec_.execute(action=_action())
        assert result.outcome is ToolCallExecutionOutcome.ABSTAINED_PRECONDITION
        entry = _unwrap(list(audit.audit_entries)[0])
        assert entry["action_kind"] == "executor.tool_call.abstained_precondition"

    @pytest.mark.asyncio
    async def test_forced_stopped_records_rollback(self) -> None:
        exec_, adapter, audit = _executor()
        adapter.force_outcome(
            ToolCallOutcome.STOPPED, rollback_succeeded=True, detail="time box exceeded"
        )
        result = await exec_.execute(action=_action())
        assert result.outcome is ToolCallExecutionOutcome.STOPPED
        assert result.rollback_succeeded is True
        entry = _unwrap(list(audit.audit_entries)[0])
        assert entry["action_kind"] == "executor.tool_call.stopped"
        assert entry["rollback_succeeded"] is True

    @pytest.mark.asyncio
    async def test_forced_failed_outcome(self) -> None:
        exec_, adapter, audit = _executor()
        adapter.force_outcome(ToolCallOutcome.FAILED, rollback_succeeded=False)
        result = await exec_.execute(action=_action())
        assert result.outcome is ToolCallExecutionOutcome.FAILED
        entry = _unwrap(list(audit.audit_entries)[0])
        assert entry["action_kind"] == "executor.tool_call.failed"

    @pytest.mark.asyncio
    async def test_tool_error_fails_closed_with_manual_rollback_flag(self) -> None:
        exec_, adapter, audit = _executor()
        adapter.next_error(ToolError("transport", "registry unreachable"))
        result = await exec_.execute(action=_action())
        assert result.outcome is ToolCallExecutionOutcome.FAILED
        assert result.rollback_succeeded is False
        entry = _unwrap(list(audit.audit_entries)[0])
        assert entry["action_kind"] == "executor.tool_call.failed"
        assert entry["rollback_succeeded"] is False

    @pytest.mark.asyncio
    async def test_tool_error_is_audited_but_retries_adapter(self) -> None:
        exec_, adapter, audit = _executor()
        adapter.next_error(ToolError("transport", "registry unreachable"))
        action = _action()

        first = await exec_.execute(action=action)
        retried = await exec_.execute(action=action)

        assert first.outcome is ToolCallExecutionOutcome.FAILED
        assert retried.outcome is ToolCallExecutionOutcome.DISPATCHED
        assert len(adapter.records) == 1
        assert len(list(audit.audit_entries)) == 2

    @pytest.mark.asyncio
    async def test_failed_receipt_is_audited_but_retries_adapter(self) -> None:
        exec_, adapter, audit = _executor()
        adapter.force_outcome(ToolCallOutcome.FAILED, rollback_succeeded=False)
        action = _action()

        first = await exec_.execute(action=action)
        adapter.force_outcome(ToolCallOutcome.SUCCEEDED)
        retried = await exec_.execute(action=action)

        assert first.outcome is ToolCallExecutionOutcome.FAILED
        assert retried.outcome is ToolCallExecutionOutcome.DISPATCHED
        assert len(adapter.records) == 2
        assert len(list(audit.audit_entries)) == 2

    @pytest.mark.asyncio
    async def test_uncontrolled_adapter_error_fails_closed(self) -> None:
        exec_, adapter, audit = _executor()
        adapter.next_error(RuntimeError("boom"))
        result = await exec_.execute(action=_action())
        assert result.outcome is ToolCallExecutionOutcome.FAILED
        assert result.rollback_succeeded is False
        entry = _unwrap(list(audit.audit_entries)[0])
        assert entry["action_kind"] == "executor.tool_call.failed"
