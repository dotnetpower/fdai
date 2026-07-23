"""Concrete startup probe adapter tests."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from fdai.delivery.startup_probe import (
    CapabilityProofStartupProbe,
    CrossCheckModelStartupProbe,
    EmbeddingStartupProbe,
    EventBusRoundTripStartupProbe,
    KillSwitchStartupProbe,
    OpaCompileStartupProbe,
    StateStoreStartupProbe,
    StreamingModelStartupProbe,
)
from fdai.shared.providers.local.event_bus import LocalEventBus
from fdai.shared.providers.startup_probe import StartupProbeRequest
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai.shared.resilience.kill_switch import StateStoreKillSwitch


def _request(*, synthetic_scope: bool = False) -> StartupProbeRequest:
    return StartupProbeRequest(
        deadline=datetime.now(UTC) + timedelta(seconds=5),
        cost_limit_usd=0.01,
        model_sample_count=2,
        synthetic_scope=synthetic_scope,
    )


class _Embedding:
    def __init__(self) -> None:
        self.calls = 0

    async def embed(self, text: str) -> list[float]:
        self.calls += 1
        return [0.1, 0.2, 0.3]


class _Streaming:
    def stream_startup_sample(self, sample: int) -> AsyncIterator[str]:
        async def chunks() -> AsyncIterator[str]:
            yield "bounded"
            yield "startup output"

        return chunks()


class _CrossCheck:
    def __init__(self) -> None:
        self.calls = 0

    async def propose(self, candidate: Any) -> tuple[str, dict[str, int]]:
        self.calls += 1
        return "startup-readiness-probe", {"sample": self.calls}


async def test_state_store_probe_performs_read_only_operation() -> None:
    store = InMemoryStateStore()
    probe = StateStoreStartupProbe(probe_id="postgres.read", state_store=store)

    result = await probe.run(_request())

    assert result.evidence == {"read": True}


async def test_event_bus_probe_round_trips_synthetic_record() -> None:
    probe = EventBusRoundTripStartupProbe(
        probe_id="kafka.round-trip",
        event_bus=LocalEventBus(),
        topic="runtime.startup.probe",
        consumer_settle_seconds=0,
    )

    result = await probe.run(_request(synthetic_scope=True))

    assert result.evidence == {"round_trip": True}


async def test_embedding_probe_collects_two_shape_samples() -> None:
    model = _Embedding()
    probe = EmbeddingStartupProbe(probe_id="model.embedding", model=model)

    result = await probe.run(_request())

    assert model.calls == 2
    assert result.model_evidence is not None
    assert result.model_evidence.sample_count == 2
    assert result.model_evidence.embedding_dimensions == 3
    assert len(result.model_evidence.total_latency_ms) == 2


async def test_streaming_probe_records_ttft_total_and_token_rate_per_sample() -> None:
    probe = StreamingModelStartupProbe(probe_id="model.stream", model=_Streaming())

    result = await probe.run(_request())

    assert result.model_evidence is not None
    assert len(result.model_evidence.ttft_ms) == 2
    assert len(result.model_evidence.total_latency_ms) == 2
    assert len(result.model_evidence.output_token_rate) == 2
    assert all(value >= 0 for value in result.model_evidence.ttft_ms)


async def test_capability_probe_requires_every_bounded_sample_to_pass() -> None:
    calls = 0

    async def prove() -> bool:
        nonlocal calls
        calls += 1
        return True

    probe = CapabilityProofStartupProbe(
        probe_id="model.tools",
        prove=prove,
        capability="tool_calling",
    )

    result = await probe.run(_request())

    assert calls == 2
    assert result.model_evidence is not None
    assert result.model_evidence.tool_calling_proven is True


async def test_cross_check_probe_collects_two_structured_output_samples() -> None:
    model = _CrossCheck()
    probe = CrossCheckModelStartupProbe(probe_id="model.cross-check", model=model)

    result = await probe.run(_request())

    assert model.calls == 2
    assert result.model_evidence is not None
    assert result.model_evidence.sample_count == 2
    assert result.model_evidence.structured_output_proven is True


async def test_opa_compile_probe_reports_unavailable_binary_at_run_time(
    tmp_path: Path,
) -> None:
    probe = OpaCompileStartupProbe(
        probe_id="policy.compile",
        policies_root=tmp_path,
        opa_binary="fdai-opa-does-not-exist",
    )

    with pytest.raises(RuntimeError, match="unavailable"):
        await probe.run(_request())


async def test_kill_switch_probe_rejects_malformed_state() -> None:
    store = InMemoryStateStore()
    await store.write_state("system:kill-switch", {"engaged": "yes"})
    probe = KillSwitchStartupProbe(
        probe_id="kill-switch.read",
        refresh=StateStoreKillSwitch(store=store).refresh,
    )

    with pytest.raises(ValueError, match="boolean"):
        await probe.run(_request())
