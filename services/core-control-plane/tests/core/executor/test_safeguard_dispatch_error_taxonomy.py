"""Adapter-failure taxonomy for the three shared safeguard dispatch adapters.

Every provider failure that crosses the shared lifecycle has to land on one
distinct, audited terminal outcome. A collapsed taxonomy would let a policy
denial read like a retryable blip, or let a cancelled dispatch report a clean
completion. These tests drive the real executors through the real coordinator
so the mapping is proven at the call site, not at the helper.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from fdai.core.executor import (
    DirectApiExecutionOutcome,
    DirectApiShadowExecutor,
    ExecutorConfig,
    ExecutorOutcome,
    ShadowExecutor,
    TemplateRenderer,
    ToolCallExecutionOutcome,
    ToolCallShadowExecutor,
)
from fdai.shared.contracts.models import Action, ExecutionPath
from fdai.shared.providers.direct_api import (
    DirectApiAuthenticationError,
    DirectApiError,
    DirectApiNetworkDeniedError,
    DirectApiPermissionDeniedError,
    DirectApiPolicyDeniedError,
    DirectApiPreconditionError,
    DirectApiPromotionError,
    DirectApiRetryableError,
)
from fdai.shared.providers.remediation_pr import (
    PublishReceipt,
    RemediationPr,
    RemediationPrPublisher,
)
from fdai.shared.providers.testing import (
    InMemoryStateStore,
    RecordingDirectApiExecutor,
    RecordingRemediationPrPublisher,
    RecordingToolExecutor,
)
from fdai.shared.providers.tool import ToolError, ToolPreconditionError, ToolPromotionError

from tests.core.executor.test_direct_api_executor import _action as _direct_action
from tests.core.executor.test_executor import _action as _pr_action
from tests.core.executor.test_executor import _rule
from tests.core.executor.test_safeguard_lifecycle_coordinator import _coordinator
from tests.core.executor.test_tool_call_executor import _action as _tool_action

_ROOT = Path(__file__).resolve().parents[5]


def _unwrap(record: Any) -> dict[str, Any]:
    if isinstance(record, dict):
        inner = record.get("entry")
        if isinstance(inner, dict) and ("previous_hash" in record or "entry_hash" in record):
            return inner
        return record
    return dict(record)


def _terminal(audit: InMemoryStateStore) -> dict[str, Any]:
    entries = [_unwrap(record) for record in audit.audit_entries]
    terminal = [entry for entry in entries if entry.get("audit_phase") != "intent"]
    assert terminal, "no terminal audit entry was written"
    return terminal[-1]


def _without_idempotency_key(action: Action) -> Action:
    """Return an action that passes the invariant guard but has no dedupe key."""

    return Action.model_construct(**{**action.__dict__, "idempotency_key": "  "})


class _FailingPrPublisher(RemediationPrPublisher):
    """Refuse every publish so the PR path sees an unknown sink outcome."""

    def __init__(self, error: BaseException) -> None:
        self._error = error
        self.calls = 0

    async def publish(self, pr: RemediationPr) -> PublishReceipt:
        del pr
        self.calls += 1
        raise self._error


def _direct_executor() -> tuple[
    DirectApiShadowExecutor,
    RecordingDirectApiExecutor,
    InMemoryStateStore,
]:
    audit = InMemoryStateStore()
    coordinator, lock = _coordinator(audit)
    adapter = RecordingDirectApiExecutor()
    executor = DirectApiShadowExecutor(
        executor=adapter,
        audit_store=audit,
        resource_lock=lock,
        safeguard_coordinator=coordinator,
    )
    return executor, adapter, audit


def _tool_executor() -> tuple[
    ToolCallShadowExecutor,
    RecordingToolExecutor,
    InMemoryStateStore,
]:
    audit = InMemoryStateStore()
    coordinator, lock = _coordinator(audit)
    adapter = RecordingToolExecutor()
    executor = ToolCallShadowExecutor(
        executor=adapter,
        audit_store=audit,
        resource_lock=lock,
        safeguard_coordinator=coordinator,
    )
    return executor, adapter, audit


class TestDirectApiErrorTaxonomy:
    """Each adapter refusal maps to exactly one audited direct-API outcome."""

    @pytest.mark.parametrize(
        ("error", "outcome", "reason_fragment"),
        [
            (
                DirectApiPromotionError("promotion is not granted"),
                DirectApiExecutionOutcome.REJECTED_MODE,
                "adapter refused promotion",
            ),
            (
                DirectApiPreconditionError("resource is already stopped"),
                DirectApiExecutionOutcome.ABSTAINED_PRECONDITION,
                "resource is already stopped",
            ),
            (
                DirectApiAuthenticationError("credential is expired"),
                DirectApiExecutionOutcome.AUTHENTICATION_FAILED,
                "credential is expired",
            ),
            (
                DirectApiPermissionDeniedError("role assignment is missing"),
                DirectApiExecutionOutcome.PERMISSION_DENIED,
                "role assignment is missing",
            ),
            (
                DirectApiPolicyDeniedError("deny assignment blocked the write"),
                DirectApiExecutionOutcome.POLICY_DENIED,
                "deny assignment blocked the write",
            ),
            (
                DirectApiNetworkDeniedError("private endpoint is unreachable"),
                DirectApiExecutionOutcome.NETWORK_DENIED,
                "private endpoint is unreachable",
            ),
            (
                DirectApiRetryableError("throttled"),
                DirectApiExecutionOutcome.FAILED,
                "retryable adapter error",
            ),
            (
                DirectApiError(kind="unclassified", message="substrate returned 500"),
                DirectApiExecutionOutcome.FAILED,
                "adapter error [unclassified]",
            ),
        ],
    )
    async def test_each_adapter_error_maps_to_one_outcome(
        self,
        error: DirectApiError,
        outcome: DirectApiExecutionOutcome,
        reason_fragment: str,
    ) -> None:
        executor, adapter, audit = _direct_executor()
        adapter.next_error(error)

        result = await executor.execute(action=_direct_action())

        assert result.outcome is outcome
        assert reason_fragment in (result.reason or "")
        assert result.rollback_succeeded is False
        assert adapter.records == ()
        assert _terminal(audit)["outcome"] == outcome.value

    async def test_an_uncontrolled_adapter_error_never_reports_success(self) -> None:
        executor, adapter, audit = _direct_executor()
        adapter.next_error(RuntimeError("adapter exploded"))

        result = await executor.execute(action=_direct_action())

        assert result.outcome is DirectApiExecutionOutcome.FAILED
        assert "uncontrolled adapter error" in (result.reason or "")
        assert result.rollback_succeeded is False
        assert _terminal(audit)["outcome"] == "failed"

    async def test_a_cancelled_dispatch_audits_then_propagates(self) -> None:
        executor, adapter, audit = _direct_executor()
        adapter.next_error(asyncio.CancelledError())  # type: ignore[arg-type]

        with pytest.raises(asyncio.CancelledError):
            await executor.execute(action=_direct_action())

        terminal = _terminal(audit)
        assert terminal["outcome"] == "failed"
        assert "cancelled" in str(terminal.get("reason", ""))

    async def test_a_refused_safeguard_never_reaches_the_adapter(self) -> None:
        executor, adapter, _ = _direct_executor()

        result = await executor.execute(action=_without_idempotency_key(_direct_action()))

        assert result.outcome is DirectApiExecutionOutcome.REJECTED_INVARIANT
        assert "idempotency_key MUST NOT be empty" in (result.reason or "")
        assert adapter.records == ()

    async def test_blast_radius_abstains_before_the_lifecycle_starts(self) -> None:
        audit = InMemoryStateStore()
        coordinator, lock = _coordinator(audit)
        adapter = RecordingDirectApiExecutor()
        executor = DirectApiShadowExecutor(
            executor=adapter,
            audit_store=audit,
            resource_lock=lock,
            config=ExecutorConfig(max_affected_resources=1),
            safeguard_coordinator=coordinator,
        )

        result = await executor.execute(action=_direct_action(count=5))

        assert result.outcome is DirectApiExecutionOutcome.ABSTAINED_BLAST_RADIUS
        assert result.safeguard_bundle_digest is None
        assert adapter.records == ()


class TestToolCallErrorTaxonomy:
    """Each tool refusal maps to exactly one audited tool-call outcome."""

    @pytest.mark.parametrize(
        ("error", "outcome", "reason_fragment"),
        [
            (
                ToolPromotionError("promotion is not granted"),
                ToolCallExecutionOutcome.REJECTED_MODE,
                "adapter refused promotion",
            ),
            (
                ToolPreconditionError("input document is missing"),
                ToolCallExecutionOutcome.ABSTAINED_PRECONDITION,
                "input document is missing",
            ),
            (
                ToolError(kind="unclassified", message="tool host crashed"),
                ToolCallExecutionOutcome.FAILED,
                "adapter error [unclassified]",
            ),
        ],
    )
    async def test_each_tool_error_maps_to_one_outcome(
        self,
        error: ToolError,
        outcome: ToolCallExecutionOutcome,
        reason_fragment: str,
    ) -> None:
        executor, adapter, audit = _tool_executor()
        adapter.next_error(error)

        result = await executor.execute(action=_tool_action())

        assert result.outcome is outcome
        assert reason_fragment in (result.reason or "")
        assert result.rollback_succeeded is False
        assert adapter.records == ()
        assert _terminal(audit)["outcome"] == outcome.value

    async def test_an_uncontrolled_tool_error_never_reports_success(self) -> None:
        executor, adapter, audit = _tool_executor()
        adapter.next_error(RuntimeError("tool exploded"))

        result = await executor.execute(action=_tool_action())

        assert result.outcome is ToolCallExecutionOutcome.FAILED
        assert "uncontrolled adapter error" in (result.reason or "")
        assert _terminal(audit)["outcome"] == "failed"

    async def test_a_cancelled_tool_dispatch_audits_then_propagates(self) -> None:
        executor, adapter, audit = _tool_executor()
        adapter.next_error(asyncio.CancelledError())  # type: ignore[arg-type]

        with pytest.raises(asyncio.CancelledError):
            await executor.execute(action=_tool_action())

        terminal = _terminal(audit)
        assert terminal["outcome"] == "failed"
        assert "cancelled" in str(terminal.get("reason", ""))

    async def test_a_refused_safeguard_never_reaches_the_tool(self) -> None:
        executor, adapter, _ = _tool_executor()

        result = await executor.execute(action=_without_idempotency_key(_tool_action()))

        assert result.outcome is ToolCallExecutionOutcome.REJECTED_INVARIANT
        assert "idempotency_key MUST NOT be empty" in (result.reason or "")
        assert adapter.records == ()

    async def test_blast_radius_abstains_before_the_tool_lifecycle_starts(self) -> None:
        audit = InMemoryStateStore()
        coordinator, lock = _coordinator(audit)
        adapter = RecordingToolExecutor()
        executor = ToolCallShadowExecutor(
            executor=adapter,
            audit_store=audit,
            resource_lock=lock,
            config=ExecutorConfig(max_affected_resources=1),
            safeguard_coordinator=coordinator,
        )

        result = await executor.execute(action=_tool_action(count=5))

        assert result.outcome is ToolCallExecutionOutcome.ABSTAINED_BLAST_RADIUS
        assert result.safeguard_bundle_digest is None
        assert adapter.records == ()

    async def test_a_receipt_observer_only_runs_for_an_accepted_receipt(self) -> None:
        audit = InMemoryStateStore()
        coordinator, lock = _coordinator(audit)
        adapter = RecordingToolExecutor()
        seen: list[str] = []

        async def _observer(request: Any, receipt: Any) -> None:
            seen.append(f"{request.idempotency_key}:{receipt.outcome.value}")

        executor = ToolCallShadowExecutor(
            executor=adapter,
            audit_store=audit,
            resource_lock=lock,
            receipt_observer=_observer,
            safeguard_coordinator=coordinator,
        )

        result = await executor.execute(action=_tool_action())

        assert result.outcome is ToolCallExecutionOutcome.DISPATCHED
        assert seen == ["example-idem:succeeded"]


class TestPrPublishErrorTaxonomy:
    """A PR sink failure leaves an unknown-outcome audit and re-raises."""

    def _pr_executor(
        self,
        publisher: RemediationPrPublisher,
        *,
        config: ExecutorConfig | None = None,
    ) -> tuple[ShadowExecutor, InMemoryStateStore]:
        audit = InMemoryStateStore()
        coordinator, lock = _coordinator(audit)
        executor = ShadowExecutor(
            publisher=publisher,
            audit_store=audit,
            renderer=TemplateRenderer(remediation_root=_ROOT / "rule-catalog" / "remediation"),
            resource_lock=lock,
            config=config,
            safeguard_coordinator=coordinator,
        )
        return executor, audit

    async def test_a_publisher_failure_audits_unknown_then_propagates(self) -> None:
        publisher = _FailingPrPublisher(RuntimeError("github is unreachable"))
        executor, audit = self._pr_executor(publisher)

        with pytest.raises(RuntimeError, match="github is unreachable"):
            await executor.execute(action=_pr_action(), rule=_rule())

        assert publisher.calls == 1
        terminal = _terminal(audit)
        assert terminal["outcome"] == ExecutorOutcome.PUBLISH_OUTCOME_UNKNOWN.value
        assert "unknown after an adapter error" in str(terminal.get("reason", ""))

    async def test_a_cancelled_publish_audits_unknown_then_propagates(self) -> None:
        publisher = _FailingPrPublisher(asyncio.CancelledError())
        executor, audit = self._pr_executor(publisher)

        with pytest.raises(asyncio.CancelledError):
            await executor.execute(action=_pr_action(), rule=_rule())

        assert _terminal(audit)["outcome"] == ExecutorOutcome.PUBLISH_OUTCOME_UNKNOWN.value

    async def test_blast_radius_abstains_before_the_pr_lifecycle_starts(self) -> None:
        publisher = RecordingRemediationPrPublisher()
        executor, audit = self._pr_executor(
            publisher,
            config=ExecutorConfig(max_affected_resources=1),
        )

        result = await executor.execute(action=_pr_action(count=5), rule=_rule())

        assert result.outcome is ExecutorOutcome.ABSTAINED_BLAST_RADIUS
        assert publisher.records == ()
        assert _terminal(audit)["outcome"] == "abstained_blast_radius"

    async def test_a_refused_safeguard_never_reaches_the_publisher(self) -> None:
        publisher = RecordingRemediationPrPublisher()
        executor, _ = self._pr_executor(publisher)

        result = await executor.execute(
            action=_without_idempotency_key(_pr_action()),
            rule=_rule(),
            execution_path=ExecutionPath.PR_MANUAL,
        )

        assert result.outcome is ExecutorOutcome.REJECTED_INVARIANT
        assert "idempotency_key MUST NOT be empty" in (result.reason or "")
        assert publisher.records == ()
