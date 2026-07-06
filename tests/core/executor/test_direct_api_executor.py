"""DirectApiShadowExecutor - safety-invariant contract tests (W2.3 glue).

Mirrors ``test_executor.py`` (PR-native path) but for the direct_api
execution path. Same six invariants apply:

- shadow-mode NEVER lets an enforce-mode Action reach the adapter.
- Every terminal path writes exactly one audit entry with
  ``action_kind`` starting with ``executor.direct_api.``.
- Idempotent by ``Action.idempotency_key`` at TWO layers (in-process
  dedupe + adapter ledger); the ALREADY_APPLIED outcome round-trips
  through both.
- Blast-radius over cap -> abstain + audit.
- Adapter error / STOPPED / precondition failure -> distinct outcomes;
  rollback_succeeded flows through to audit.
- Missing safety-invariant fields -> REJECTED_INVARIANT (defense in
  depth against a caller that produced an Action via replace()).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest

from aiopspilot.core.executor import (
    DirectApiExecutionOutcome,
    DirectApiExecutionResult,
    DirectApiShadowExecutor,
    ExecutorConfig,
    ResourceLockManager,
)
from aiopspilot.shared.contracts.models import (
    Action,
    BlastRadius,
    BlastRadiusScope,
    Mode,
    Operation,
    RollbackKind,
    RollbackRef,
)
from aiopspilot.shared.providers.direct_api import (
    DirectApiOutcome,
    DirectApiPreconditionError,
    DirectApiPromotionError,
)
from aiopspilot.shared.providers.testing import (
    InMemoryStateStore,
    RecordingDirectApiExecutor,
)


def _action(
    *,
    action_id: str = "00000000-0000-0000-0000-000000000010",
    idempotency_key: str = "example-idem",
    target: str = "resource:example/rg/vm1",
    mode: Mode = Mode.SHADOW,
    count: int | None = 1,
    rate: int | None = 5,
    citing_rules: tuple[str, ...] = ("ops.restart-service",),
    params: dict[str, Any] | None = None,
    stop_condition: str = "target_not_healthy",
) -> Action:
    return Action(
        schema_version="1.0.0",
        action_id=UUID(action_id),
        idempotency_key=idempotency_key,
        event_id=UUID("00000000-0000-0000-0000-000000000011"),
        action_type="ops.restart-service",
        target_resource_ref=target,
        operation=Operation.RESTART,
        params=params or {"cooldown_seconds": 30},
        stop_condition=stop_condition,
        rollback_ref=RollbackRef(kind=RollbackKind.SCRIPTED, reference="rb-99"),
        blast_radius=BlastRadius(
            scope=BlastRadiusScope.RESOURCE, count=count, rate_per_minute=rate
        ),
        mode=mode,
        citing_rules=list(citing_rules),
        created_at="2026-07-05T08:00:00Z",  # type: ignore[arg-type]
    )


def _executor(
    **overrides: Any,
) -> tuple[
    DirectApiShadowExecutor,
    RecordingDirectApiExecutor,
    InMemoryStateStore,
]:
    adapter = RecordingDirectApiExecutor()
    audit = InMemoryStateStore()
    exec_ = DirectApiShadowExecutor(
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
        exec_, adapter, audit = _executor()
        result = await exec_.execute(action=_action())
        assert isinstance(result, DirectApiExecutionResult)
        assert result.outcome is DirectApiExecutionOutcome.DISPATCHED
        assert result.mode is Mode.SHADOW
        assert result.receipt_ref
        entries = list(audit.audit_entries)
        assert len(entries) == 1
        entry = _unwrap(entries[0])
        assert entry["action_kind"] == "executor.direct_api.dispatched"
        assert entry["execution_path"] == "direct_api"
        assert entry["outcome"] == "dispatched"
        assert entry["mode"] == "shadow"

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
        await exec_.execute(action=_action(params={"cooldown_seconds": 60, "region": "krc"}))
        request = adapter.records[0]
        assert request.arguments == {"cooldown_seconds": 60, "region": "krc"}
        assert request.action_type_name == "ops.restart-service"


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


class TestIdempotency:
    @pytest.mark.asyncio
    async def test_second_call_returns_cached_without_hitting_adapter(self) -> None:
        exec_, adapter, audit = _executor()
        r1 = await exec_.execute(action=_action(idempotency_key="dup"))
        r2 = await exec_.execute(action=_action(idempotency_key="dup"))
        # Same object identity via in-process dedupe.
        assert r2 is r1
        # Adapter saw exactly ONE request.
        assert len(adapter.records) == 1
        # Audit saw exactly ONE entry (dedupe short-circuited before audit).
        assert len(list(audit.audit_entries)) == 1

    @pytest.mark.asyncio
    async def test_different_keys_dispatch_independently(self) -> None:
        exec_, adapter, audit = _executor()
        await exec_.execute(action=_action(idempotency_key="a"))
        await exec_.execute(action=_action(idempotency_key="b", target="vm2"))
        assert len(adapter.records) == 2
        assert len(list(audit.audit_entries)) == 2

    @pytest.mark.asyncio
    async def test_adapter_already_applied_reported_as_outcome(self) -> None:
        """When the adapter's ledger short-circuits (e.g. after a
        process restart wiped in-process dedupe), the executor MUST
        surface ALREADY_APPLIED and audit distinctly."""
        exec_, adapter, audit = _executor()
        adapter.force_outcome(DirectApiOutcome.ALREADY_APPLIED, detail="prior receipt reused")
        result = await exec_.execute(action=_action(idempotency_key="k"))
        assert result.outcome is DirectApiExecutionOutcome.ALREADY_APPLIED
        entry = _unwrap(list(audit.audit_entries)[0])
        assert entry["action_kind"] == "executor.direct_api.already_applied"


# ---------------------------------------------------------------------------
# Safety-invariant refusals
# ---------------------------------------------------------------------------


class TestSafetyRefusals:
    @pytest.mark.asyncio
    async def test_enforce_mode_refused_before_lock(self) -> None:
        exec_, adapter, audit = _executor()
        result = await exec_.execute(action=_action(mode=Mode.ENFORCE))
        assert result.outcome is DirectApiExecutionOutcome.REJECTED_MODE
        # Adapter NEVER saw the request.
        assert adapter.records == ()
        entry = _unwrap(list(audit.audit_entries)[0])
        assert entry["action_kind"] == "executor.direct_api.rejected_mode"

    @pytest.mark.asyncio
    async def test_missing_stop_condition_rejects(self) -> None:
        """Defense-in-depth: bypass pydantic via ``model_construct`` so
        the executor's own invariant guard is exercised. Use direct
        attribute swap so nested BlastRadius/RollbackRef stay real."""
        exec_, adapter, audit = _executor()
        valid = _action()
        fields = {**valid.__dict__, "stop_condition": "  "}
        bad = Action.model_construct(**fields)
        result = await exec_.execute(action=bad)
        assert result.outcome is DirectApiExecutionOutcome.REJECTED_INVARIANT
        assert adapter.records == ()
        entry = _unwrap(list(audit.audit_entries)[0])
        assert entry["action_kind"] == "executor.direct_api.rejected_invariant"

    @pytest.mark.asyncio
    async def test_missing_citing_rules_rejects(self) -> None:
        exec_, adapter, _ = _executor()
        valid = _action()
        fields = {**valid.__dict__, "citing_rules": []}
        bad = Action.model_construct(**fields)
        result = await exec_.execute(action=bad)
        assert result.outcome is DirectApiExecutionOutcome.REJECTED_INVARIANT
        assert adapter.records == ()

    @pytest.mark.asyncio
    async def test_adapter_promotion_error_maps_to_rejected_mode(self) -> None:
        """Defense-in-depth: even if the caller somehow bypassed our
        Mode check, the adapter's promotion check catches it and we
        surface REJECTED_MODE."""
        exec_, adapter, _ = _executor()
        adapter.next_error(DirectApiPromotionError("promotion refused"))
        result = await exec_.execute(action=_action())
        assert result.outcome is DirectApiExecutionOutcome.REJECTED_MODE


# ---------------------------------------------------------------------------
# Blast-radius cap
# ---------------------------------------------------------------------------


class TestBlastRadius:
    @pytest.mark.asyncio
    async def test_count_over_cap_abstains(self) -> None:
        exec_, adapter, audit = _executor(max_affected_resources=1)
        result = await exec_.execute(action=_action(count=5))
        assert result.outcome is DirectApiExecutionOutcome.ABSTAINED_BLAST_RADIUS
        assert adapter.records == ()
        entry = _unwrap(list(audit.audit_entries)[0])
        assert entry["outcome"] == "abstained_blast_radius"

    @pytest.mark.asyncio
    async def test_rate_over_cap_abstains(self) -> None:
        exec_, adapter, _ = _executor(max_rate_per_minute=1)
        result = await exec_.execute(action=_action(rate=99))
        assert result.outcome is DirectApiExecutionOutcome.ABSTAINED_BLAST_RADIUS
        assert adapter.records == ()

    @pytest.mark.asyncio
    async def test_count_and_rate_none_never_trips_cap(self) -> None:
        exec_, adapter, _ = _executor(max_affected_resources=1, max_rate_per_minute=1)
        result = await exec_.execute(action=_action(count=None, rate=None))
        assert result.outcome is DirectApiExecutionOutcome.DISPATCHED
        assert len(adapter.records) == 1


# ---------------------------------------------------------------------------
# Adapter outcomes / errors
# ---------------------------------------------------------------------------


class TestAdapterOutcomes:
    @pytest.mark.asyncio
    async def test_stopped_flows_rollback_flag_through(self) -> None:
        exec_, adapter, audit = _executor()
        adapter.force_outcome(
            DirectApiOutcome.STOPPED,
            rollback_succeeded=True,
            detail="blast radius tripped mid-flight",
        )
        result = await exec_.execute(action=_action())
        assert result.outcome is DirectApiExecutionOutcome.STOPPED
        assert result.rollback_succeeded is True
        entry = _unwrap(list(audit.audit_entries)[0])
        assert entry["rollback_succeeded"] is True

    @pytest.mark.asyncio
    async def test_failed_with_no_rollback_surfaces_false(self) -> None:
        exec_, adapter, audit = _executor()
        adapter.force_outcome(
            DirectApiOutcome.FAILED,
            rollback_succeeded=False,
            detail="upstream 500",
        )
        result = await exec_.execute(action=_action())
        assert result.outcome is DirectApiExecutionOutcome.FAILED
        assert result.rollback_succeeded is False
        entry = _unwrap(list(audit.audit_entries)[0])
        assert entry["rollback_succeeded"] is False

    @pytest.mark.asyncio
    async def test_adapter_precondition_error_maps_to_abstain(self) -> None:
        exec_, adapter, _ = _executor()
        adapter.next_error(DirectApiPreconditionError("resource state has moved on"))
        result = await exec_.execute(action=_action())
        assert result.outcome is DirectApiExecutionOutcome.ABSTAINED_PRECONDITION

    @pytest.mark.asyncio
    async def test_precondition_failed_receipt_maps_to_abstain(self) -> None:
        exec_, adapter, _ = _executor()
        adapter.force_outcome(DirectApiOutcome.PRECONDITION_FAILED)
        result = await exec_.execute(action=_action())
        assert result.outcome is DirectApiExecutionOutcome.ABSTAINED_PRECONDITION

    @pytest.mark.asyncio
    async def test_uncontrolled_adapter_exception_fails_closed(self) -> None:
        exec_, adapter, audit = _executor()
        adapter.next_error(RuntimeError("network partition"))
        result = await exec_.execute(action=_action())
        assert result.outcome is DirectApiExecutionOutcome.FAILED
        assert result.rollback_succeeded is False
        assert "uncontrolled adapter error" in (result.reason or "")

    @pytest.mark.asyncio
    async def test_generic_direct_api_error_maps_to_failed(self) -> None:
        from aiopspilot.shared.providers.direct_api import DirectApiError

        exec_, adapter, _ = _executor()
        adapter.next_error(DirectApiError("transient", "network hiccup"))
        result = await exec_.execute(action=_action())
        assert result.outcome is DirectApiExecutionOutcome.FAILED


# ---------------------------------------------------------------------------
# Ordering: per-resource serialisation, cross-resource parallelism
# ---------------------------------------------------------------------------


class TestOrdering:
    @pytest.mark.asyncio
    async def test_actions_on_different_resources_dispatch_in_parallel(self) -> None:
        import asyncio

        exec_, adapter, _ = _executor()
        await asyncio.gather(
            exec_.execute(action=_action(idempotency_key="a", target="vm-a")),
            exec_.execute(action=_action(idempotency_key="b", target="vm-b")),
        )
        assert len(adapter.records) == 2

    @pytest.mark.asyncio
    async def test_actions_on_same_resource_serialize(self) -> None:
        """Two concurrent calls on the same target both succeed but
        the second one waits for the first's lock; the dedupe cache
        catches the identical-key case."""
        import asyncio

        exec_, adapter, _ = _executor()
        results = await asyncio.gather(
            exec_.execute(action=_action(idempotency_key="k", target="vm-x")),
            exec_.execute(action=_action(idempotency_key="k", target="vm-x")),
        )
        assert results[0] is results[1]
        # Adapter saw one request (dedupe short-circuited the second).
        assert len(adapter.records) == 1
