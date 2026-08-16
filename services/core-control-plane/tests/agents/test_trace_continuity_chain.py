"""Trace discontinuity finding to Incident lifecycle integration."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from fdai.agents.heimdall import Heimdall
from fdai.agents.huginn import Huginn
from fdai.core.detection.trace_continuity import (
    TraceSpanObservation,
    TraceTopologyObservation,
)
from fdai.core.incident import IncidentLifecycleWorkflow, IncidentRegistry
from fdai.delivery.azure.trace_continuity import TraceTopologyTarget
from fdai.delivery.trace_continuity_tick import TraceContinuityTickRunner
from fdai.shared.contracts.models import IncidentSeverity
from fdai.shared.providers.testing.state_store import InMemoryStateStore

_START = datetime(2026, 8, 17, 3, 0, tzinfo=UTC)
_HOPS = ("application", "agent", "api-gateway", "model-endpoint")


class _WindowSource:
    async def collect(
        self,
        targets: tuple[TraceTopologyTarget, ...],
        *,
        window_seconds: int,
        window_bucket: str,
    ) -> tuple[TraceTopologyObservation, ...]:
        del window_seconds
        target = targets[0]
        return (
            TraceTopologyObservation(
                topology_ref=target.topology_ref,
                scenario_id="stable-trace-episode",
                resource_ref=target.resource_ref,
                window_bucket=window_bucket,
                expected_hops=target.expected_hops,
                spans=tuple(
                    TraceSpanObservation(
                        trace_id=("trace-front" if sequence < 2 else "trace-back"),
                        span_id=f"{window_bucket}-{sequence}",
                        hop=hop,
                        sequence=sequence,
                        observed_at=_START + timedelta(seconds=sequence),
                        evidence_ref=f"appinsights:{window_bucket}-{sequence}",
                    )
                    for sequence, hop in enumerate(_HOPS)
                ),
                completed=True,
            ),
        )


class _RecordingBus:
    def __init__(self) -> None:
        self.published: list[dict[str, object]] = []

    async def publish(self, topic: str, key: str, payload: dict[str, object]) -> None:
        del topic, key
        self.published.append(payload)


@pytest.mark.asyncio
async def test_repeated_trace_discontinuity_opens_one_incident() -> None:
    target = TraceTopologyTarget(
        topology_ref="synthetic-agent-request",
        resource_ref="trace-topology/synthetic-agent-request",
        expected_hops=_HOPS,
    )
    bus = _RecordingBus()
    tick = {"index": 0}
    runner = TraceContinuityTickRunner(
        source=_WindowSource(),
        event_bus=bus,  # type: ignore[arg-type]
        window_seconds=60,
        clock=lambda: _START + timedelta(seconds=tick["index"] * 60),
    )
    incident_registry = IncidentRegistry(state_store=InMemoryStateStore())
    workflow = IncidentLifecycleWorkflow(
        registry=incident_registry,
        allowed_agent_principals={"Heimdall"},
    )
    candidates: list[dict[str, object]] = []

    async def open_candidate(candidate: dict[str, object]) -> bool:
        candidates.append(candidate)
        evidence_keys = tuple(str(item) for item in candidate["evidence_keys"])
        await workflow.open_from_agent(
            producer_principal=str(candidate["producer_principal"]),
            correlation_keys=(f"trace:{candidate['correlation_id']}",),
            severity=IncidentSeverity.SEV2,
            member_event_ids=tuple(UUID(item) for item in evidence_keys),
            reason=str(candidate["reason_code"]),
        )
        return True

    huginn = Huginn()
    heimdall = Heimdall(
        rate_threshold=5,
        rate_window=300,
        incident_candidate_hook=open_candidate,
        clock=lambda: float(tick["index"] * 60),
    )

    for index in range(5):
        tick["index"] = index
        report = await runner.run_once((target,))
        assert report.published == 1
        raw_event = bus.published[-1]
        raw_payload = raw_event["payload"]
        assert isinstance(raw_payload, dict)
        raw_payload["forged_action"] = "ops.restart-service"
        normalized = await huginn.ingest(raw_event)
        assert normalized is not None
        trace_evidence = normalized["attributes"]["trace_continuity"]
        assert trace_evidence["reason_code"] == "trace_context_regenerated"
        assert trace_evidence["disconnected_boundaries"] == ["agent->api-gateway"]
        assert "forged_action" not in trace_evidence
        await heimdall.on_typed_message("object.event", normalized)

    incidents = tuple(incident_registry.snapshot().values())
    assert len(incidents) == 1
    assert incidents[0].severity is IncidentSeverity.SEV2
    assert len(incidents[0].member_event_ids) == 5
    assert candidates[0]["reason_code"] == "trace_context_regenerated"
    assert candidates[0]["trace_continuity"] == trace_evidence
    assert heimdall.behavior_snapshot()["incident_candidate"] == 1
