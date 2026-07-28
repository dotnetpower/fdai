"""CyberGym e2e and patch-only acceptance through the concrete FDAI host."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Any

import pytest
from fdai_bench_cybergym import CyberGymAdapter, CyberGymMode, CyberGymTaskConfig
from fdai_evaluation_sdk import (
    ArtifactPolicy,
    ArtifactRef,
    AuthorityCeiling,
    EvaluationRunner,
    EvaluationTask,
    SideEffectClass,
)

from fdai.core.control_loop import ControlLoopOutcome, ControlLoopResult
from fdai.evaluation.artifacts import InMemoryArtifactBroker, InMemoryArtifactCustodySink
from fdai.evaluation.capabilities import AuthorityAxes, CapabilityAxes
from fdai.evaluation.host import (
    EvaluationHostPolicy,
    FdaiEvaluationHost,
    InMemoryExternalValidationSink,
)
from fdai.shared.contracts.models import Event

_NOW = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)


class _Processor:
    async def process(self, event: Event | Mapping[str, Any]) -> ControlLoopResult:
        assert isinstance(event, Event)
        return ControlLoopResult(
            outcome=ControlLoopOutcome.EXECUTED,
            tier="t2",
            decision="patch",
            resource_type="source.workspace",
            citing_rule_ids=("workspace.patch",),
        )


class _Collector:
    def __init__(self, broker: InMemoryArtifactBroker, policy: ArtifactPolicy) -> None:
        self._broker = broker
        self._policy = policy

    async def collect(
        self,
        *,
        task: EvaluationTask,
        control_result: ControlLoopResult,
    ) -> tuple[ArtifactRef, ...]:
        assert control_result.outcome is ControlLoopOutcome.EXECUTED
        outputs: list[ArtifactRef] = []
        for spec in task.expected_outputs:
            content = b"poc" if spec.name == "poc.bin" else b"diff --git a/a b/a\n"

            async def chunks(value: bytes = content) -> AsyncIterator[bytes]:
                yield value

            outputs.append(
                await self._broker.publish(
                    session_id=task.session_id,
                    task_id=task.task_id,
                    spec=spec,
                    declared_outputs=task.expected_outputs,
                    chunks=chunks(),
                    policy=self._policy,
                    ttl_seconds=spec.ttl_seconds,
                )
            )
        return tuple(outputs)


def _input_artifact(name: str, media_type: str) -> ArtifactRef:
    digest = sha256(name.encode()).hexdigest()
    return ArtifactRef(
        artifact_id=f"sha256:{digest}",
        session_id="session-1",
        task_id="task-1",
        name=name,
        media_type=media_type,
        size_bytes=1,
        sha256=digest,
        expires_at=_NOW + timedelta(hours=1),
    )


@pytest.mark.parametrize("mode", (CyberGymMode.E2E, CyberGymMode.PATCH_ONLY))
async def test_cybergym_mode_completes_through_concrete_host(mode: CyberGymMode) -> None:
    inputs = (
        {
            "crash_log": _input_artifact("crash.log", "text/plain"),
            "supplied_poc": _input_artifact("input-poc.bin", "application/octet-stream"),
        }
        if mode is CyberGymMode.PATCH_ONLY
        else {}
    )
    adapter = CyberGymAdapter(
        CyberGymTaskConfig(
            session_id="session-1",
            task_id="task-1",
            mode=mode,
            source_workspace_ref="workspace-1",
            deadline=_NOW + timedelta(hours=1),
            **inputs,
        )
    )
    request = await adapter.start()
    catalog = {
        capability.capability_id: SideEffectClass.WORKSPACE
        for capability in request.requested_capabilities
    }
    allowed = frozenset(catalog)
    authority = AuthorityAxes(*((AuthorityCeiling.SHADOW,) * 6))
    broker = InMemoryArtifactBroker(
        custody_sink=InMemoryArtifactCustodySink(),
        clock=lambda: _NOW,
    )
    host = FdaiEvaluationHost(
        processor=_Processor(),
        artifact_broker=broker,
        validation_sink=InMemoryExternalValidationSink(),
        output_collector=_Collector(broker, request.artifact_policy),
        policy=EvaluationHostPolicy(
            capability_catalog=catalog,
            capability_axes=CapabilityAxes(*((allowed,) * 6)),
            authority_axes=authority,
        ),
        clock=lambda: _NOW,
    )

    summary = await EvaluationRunner(adapter=adapter, host=host).run()

    assert summary.task_count == 1
    assert summary.completed_count == 1
