from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from fdai.core.control_loop._rca import ControlLoopRcaMixin
from fdai.core.rca.runtime import CausalRuntimeOutcome, CausalRuntimeResult
from fdai.shared.contracts.models import Event


class _Audit:
    def __init__(self) -> None:
        self.entries: list[dict[str, Any]] = []

    async def append_audit_entry(self, entry: dict[str, Any]) -> None:
        self.entries.append(entry)


class _Coordinator:
    def __init__(self, *, raises: bool = False) -> None:
        self.raises = raises
        self.calls: list[tuple[str, str]] = []

    async def analyze(self, *, event: Event, incident_id: str) -> CausalRuntimeResult:
        self.calls.append((str(event.event_id), incident_id))
        if self.raises:
            raise RuntimeError("provider failed")
        return CausalRuntimeResult(CausalRuntimeOutcome.NO_EVIDENCE)


@dataclass
class _Host(ControlLoopRcaMixin):
    _audit_store: Any
    _causal_runtime_coordinator: Any


def _event() -> Event:
    return Event.model_validate(
        {
            "schema_version": "1.0.0",
            "event_id": "00000000-0000-0000-0000-000000000001",
            "idempotency_key": "event-1",
            "source": "example",
            "event_type": "anomaly",
            "detected_at": "2026-08-01T00:00:00Z",
            "ingested_at": "2026-08-01T00:00:01Z",
            "mode": "shadow",
            "payload": {},
        }
    )


async def test_control_loop_audits_temporal_causal_no_evidence() -> None:
    audit = _Audit()
    coordinator = _Coordinator()
    host = _Host(audit, coordinator)

    await host._analyze_and_audit_temporal_causality(
        event=_event(),
        incident_id="incident-1",
    )

    assert coordinator.calls == [("00000000-0000-0000-0000-000000000001", "incident-1")]
    assert audit.entries[0]["action_kind"] == "rca.temporal_causality"
    assert audit.entries[0]["causal_runtime_outcome"] == "no_evidence"
    assert audit.entries[0]["mode"] == "shadow"


async def test_temporal_causal_provider_failure_does_not_escape_side_path() -> None:
    audit = _Audit()
    host = _Host(audit, _Coordinator(raises=True))

    await host._analyze_and_audit_temporal_causality(
        event=_event(),
        incident_id="incident-1",
    )

    assert audit.entries == []


async def test_temporal_causal_runtime_is_not_called_without_incident() -> None:
    audit = _Audit()
    coordinator = _Coordinator()
    host = _Host(audit, coordinator)

    await host._analyze_and_audit_temporal_causality(event=_event(), incident_id=None)

    assert coordinator.calls == []
    assert audit.entries == []


async def test_temporal_causal_runtime_timeout_does_not_block_decision_path() -> None:
    class _BlockingCoordinator:
        async def analyze(self, *, event: Event, incident_id: str) -> CausalRuntimeResult:
            await asyncio.Event().wait()
            raise AssertionError("unreachable")

    audit = _Audit()
    host = _Host(audit, _BlockingCoordinator())
    host._rca_side_path_timeout_seconds = 0.001

    await host._analyze_and_audit_temporal_causality(
        event=_event(),
        incident_id="incident-1",
    )

    assert audit.entries == []
