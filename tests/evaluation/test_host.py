"""Public evaluation host lifecycle, correlation, and isolation tests."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import AsyncIterator, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fdai_evaluation_sdk import (
    ArtifactPolicy,
    ArtifactRef,
    ArtifactSpec,
    AuthorityCeiling,
    Capability,
    EvaluationHost,
    EvaluationRequest,
    EvaluationSession,
    EvaluationStatus,
    EvaluationTask,
    ExternalValidationReceipt,
    ExternalValidationStage,
    ResourceLimits,
    SideEffectClass,
    TargetRef,
    WorkspaceOperation,
    WorkspacePolicy,
)

from fdai.core.control_loop import ControlLoopOutcome, ControlLoopResult
from fdai.evaluation.artifacts import InMemoryArtifactBroker, InMemoryArtifactCustodySink
from fdai.evaluation.capabilities import AuthorityAxes, CapabilityAxes
from fdai.evaluation.host import (
    EvaluationHostError,
    EvaluationHostPolicy,
    FdaiEvaluationHost,
    InMemoryExternalValidationSink,
)
from fdai.evaluation.public import EvaluationHost as PublicHost
from fdai.shared.contracts.models import Event

_NOW = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)
_CAPABILITY_ID = "workspace.edit"


class _Processor:
    def __init__(
        self,
        outcome: ControlLoopOutcome = ControlLoopOutcome.EXECUTED,
    ) -> None:
        self.events: list[Event] = []
        self.calls = 0
        self.outcome = outcome

    async def process(self, event: Event | Mapping[str, Any]) -> ControlLoopResult:
        assert isinstance(event, Event)
        self.events.append(event)
        self.calls += 1
        return ControlLoopResult(
            outcome=self.outcome,
            tier="t0",
            decision="patch",
            resource_type="workspace",
            citing_rule_ids=("workspace.patch",),
        )


def _request(**overrides: object) -> EvaluationRequest:
    capability = Capability(
        capability_id=_CAPABILITY_ID,
        side_effect_class=SideEffectClass.WORKSPACE,
    )
    values: dict[str, object] = {
        "session_id": "session-1",
        "requester_id": "driver-1",
        "purpose": "Evaluate one bounded source repair.",
        "requested_capabilities": (capability,),
        "authority_ceiling": AuthorityCeiling.SHADOW,
        "task_count_limit": 2,
        "concurrency_limit": 1,
        "deadline": _NOW + timedelta(hours=1),
        "workspace_policy": WorkspacePolicy(operations=(WorkspaceOperation.EDIT,)),
        "artifact_policy": ArtifactPolicy(
            allowed_media_types=("text/x-diff",),
            max_artifact_bytes=4_096,
        ),
    }
    values.update(overrides)
    return EvaluationRequest.model_validate(values)


def _task(**overrides: object) -> EvaluationTask:
    values: dict[str, object] = {
        "session_id": "session-1",
        "task_id": "task-1",
        "phase": "patch",
        "objective": "Produce a bounded source patch.",
        "target": TargetRef(kind="workspace", value="source-1"),
        "expected_outputs": (),
        "requested_capabilities": (
            Capability(
                capability_id=_CAPABILITY_ID,
                side_effect_class=SideEffectClass.WORKSPACE,
            ),
        ),
        "deadline": _NOW + timedelta(minutes=30),
        "resource_limits": ResourceLimits(
            cpu_seconds=60,
            memory_bytes=268_435_456,
            process_count=16,
            output_bytes=1_048_576,
            wall_clock_seconds=120,
        ),
    }
    values.update(overrides)
    return EvaluationTask.model_validate(values)


def _artifact_task(**overrides: object) -> EvaluationTask:
    return _task(
        expected_outputs=(
            ArtifactSpec(name="fix.patch", media_type="text/x-diff", max_bytes=4_096),
        ),
        **overrides,
    )


def _host(
    *,
    host_authority: AuthorityCeiling = AuthorityCeiling.SHADOW,
    outcome: ControlLoopOutcome = ControlLoopOutcome.EXECUTED,
):
    allowed = frozenset({_CAPABILITY_ID})
    processor = _Processor(outcome)
    custody = InMemoryArtifactCustodySink()
    broker = InMemoryArtifactBroker(custody_sink=custody, clock=lambda: _NOW)
    host = FdaiEvaluationHost(
        processor=processor,
        artifact_broker=broker,
        validation_sink=InMemoryExternalValidationSink(),
        policy=EvaluationHostPolicy(
            capability_catalog={_CAPABILITY_ID: SideEffectClass.WORKSPACE},
            capability_axes=CapabilityAxes(
                host_allowlist=allowed,
                session_scope=allowed,
                rbac_allowed=allowed,
                promotion_allowed=allowed,
                risk_allowed=allowed,
                approval_allowed=allowed,
            ),
            authority_axes=AuthorityAxes(
                host=host_authority,
                session=host_authority,
                rbac=host_authority,
                promotion=host_authority,
                risk=host_authority,
                approval=host_authority,
            ),
        ),
        clock=lambda: _NOW,
    )
    return host, processor, custody


def test_public_spi_exposes_only_sdk_protocols() -> None:
    import fdai.evaluation.public as public

    assert PublicHost is EvaluationHost
    assert set(public.__all__) == {"EVALUATION_API_VERSION", "EvaluationHost", "EvaluationSession"}
    assert all(
        forbidden not in vars(public)
        for forbidden in ("Container", "ControlLoop", "StateStore", "_build_control_loop")
    )


async def test_open_attenuates_adapter_authority_and_rejects_unknown_capability() -> None:
    host, processor, _ = _host()
    assert isinstance(host, EvaluationHost)
    session = await host.open(_request(authority_ceiling=AuthorityCeiling.ENFORCE))
    result = await session.execute(_task())
    assert result.decision_receipt.authority_ceiling is AuthorityCeiling.SHADOW
    assert processor.events[0].mode.value == "shadow"
    untrusted = Capability(
        capability_id="action.kubernetes.patch",
        side_effect_class=SideEffectClass.SUBSTRATE,
    )
    with pytest.raises(EvaluationHostError, match="cannot be satisfied"):
        await host.open(_request(requested_capabilities=(untrusted,)))


async def test_execute_correlates_ingress_and_reuses_idempotent_result() -> None:
    host, processor, _ = _host()
    session = await host.open(_request())
    assert isinstance(session, EvaluationSession)

    first = await session.execute(_task())
    second = await session.execute(_task())

    assert first is second
    assert first.status is EvaluationStatus.COMPLETED
    assert processor.calls == 1
    event = processor.events[0]
    assert event.source == "evaluation.host"
    assert event.event_type == "evaluation.task.requested"
    assert event.correlation_id == "session-1"
    assert event.payload["input_artifact_refs"] == []
    assert not any(isinstance(value, bytes) for value in event.payload.values())


async def test_retry_with_same_id_and_different_content_is_rejected() -> None:
    host, _, _ = _host()
    session = await host.open(_request())
    await session.execute(_task())

    with pytest.raises(EvaluationHostError, match="conflicts"):
        await session.execute(_task(objective="Produce a different patch."))


async def test_task_cannot_escape_session_capability_or_deadline() -> None:
    host, _, _ = _host()
    session = await host.open(_request())
    substrate = Capability(
        capability_id="action.kubernetes.patch",
        side_effect_class=SideEffectClass.SUBSTRATE,
    )
    with pytest.raises(EvaluationHostError, match="unavailable capabilities"):
        await session.execute(_task(requested_capabilities=(substrate,)))
    with pytest.raises(EvaluationHostError, match="deadline"):
        await session.execute(_task(task_id="task-2", deadline=_NOW + timedelta(hours=2)))


async def test_close_is_idempotent_and_cleans_session_artifacts() -> None:
    host, _, custody = _host(outcome=ControlLoopOutcome.HIL)
    session = await host.open(_request())
    task = _artifact_task()
    await session.execute(task)

    async def chunks() -> AsyncIterator[bytes]:
        yield b"patch"

    await session.publish_artifact(
        task_id=task.task_id,
        spec=task.expected_outputs[0],
        chunks=chunks(),
    )
    await session.close()
    await session.close()

    assert custody.records[-1].operation == "cleanup"
    with pytest.raises(EvaluationHostError, match="closed"):
        await session.execute(_task(task_id="task-2"))


async def test_cancellation_releases_concurrency_slot() -> None:
    entered = asyncio.Event()

    class _CancellingProcessor(_Processor):
        async def process(self, event: Event | Mapping[str, Any]) -> ControlLoopResult:
            entered.set()
            await asyncio.Event().wait()
            raise AssertionError("unreachable")

    host, _, _ = _host()
    host._processor = _CancellingProcessor()  # noqa: SLF001
    session = await host.open(_request())
    execution = asyncio.create_task(session.execute(_task()))
    await entered.wait()
    execution.cancel()
    with pytest.raises(asyncio.CancelledError):
        await execution

    assert session._inflight == 0  # noqa: SLF001


async def test_close_waits_for_inflight_artifact_publication() -> None:
    host, _, custody = _host(outcome=ControlLoopOutcome.HIL)
    session = await host.open(_request())
    task = _artifact_task()
    await session.execute(task)
    entered = asyncio.Event()
    release = asyncio.Event()

    async def delayed_chunks() -> AsyncIterator[bytes]:
        entered.set()
        await release.wait()
        yield b"patch"

    publication = asyncio.create_task(
        session.publish_artifact(
            task_id=task.task_id,
            spec=task.expected_outputs[0],
            chunks=delayed_chunks(),
        )
    )
    await entered.wait()
    closing = asyncio.create_task(session.close())
    await asyncio.sleep(0)
    assert closing.done() is False

    release.set()
    await publication
    await closing

    assert custody.records[-1].operation == "cleanup"


async def test_external_validation_records_after_close_idempotently() -> None:
    host, _, _ = _host()
    session = await host.open(_request())
    task = _task()
    await session.execute(task)
    await session.close()
    spec = ArtifactSpec(name="validation.json", media_type="application/json", max_bytes=1_024)
    reference = ArtifactRef(
        artifact_id="sha256:" + "a" * 64,
        session_id=task.session_id,
        task_id=task.task_id,
        name=spec.name,
        media_type=spec.media_type,
        size_bytes=1,
        sha256="a" * 64,
        expires_at=_NOW + timedelta(minutes=1),
    )
    receipt = ExternalValidationReceipt(
        session_id=task.session_id,
        task_id=task.task_id,
        stages=(
            ExternalValidationStage(
                stage_id="project_tests_pass",
                passed=True,
                receipt_ref=reference,
            ),
        ),
    )

    await host.record_external_validation(receipt)
    await host.record_external_validation(receipt)

    assert len(host._validation_sink.receipts) == 1  # type: ignore[attr-defined]  # noqa: SLF001
    conflicting = receipt.model_copy(
        update={"stages": (receipt.stages[0].model_copy(update={"stage_id": "different-stage"}),)}
    )
    with pytest.raises(EvaluationHostError, match="conflicts"):
        await host.record_external_validation(conflicting)


async def test_external_validation_rejects_expired_stage_evidence() -> None:
    host, _, _ = _host()
    session = await host.open(_request())
    task = _task()
    await session.execute(task)
    await session.close()
    spec = ArtifactSpec(name="validation.json", media_type="application/json", max_bytes=1_024)
    reference = ArtifactRef(
        artifact_id="sha256:" + "a" * 64,
        session_id=task.session_id,
        task_id=task.task_id,
        name=spec.name,
        media_type=spec.media_type,
        size_bytes=1,
        sha256="a" * 64,
        expires_at=_NOW,
    )
    receipt = ExternalValidationReceipt(
        session_id=task.session_id,
        task_id=task.task_id,
        stages=(
            ExternalValidationStage(
                stage_id="project_tests_pass",
                passed=True,
                receipt_ref=reference,
            ),
        ),
    )

    with pytest.raises(EvaluationHostError, match="expired or cross-task"):
        await host.record_external_validation(receipt)


def test_host_constructor_has_no_container_or_private_builder_parameter() -> None:
    parameters = inspect.signature(FdaiEvaluationHost).parameters
    assert "container" not in parameters
    assert "control_loop" not in parameters
    assert "state_store" not in parameters
