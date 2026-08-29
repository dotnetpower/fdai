"""Concrete startup probe adapter tests."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import UUID

import pytest
from fdai.core.readiness import ProbeStatus
from fdai.delivery.startup_probe import (
    AuditChainStartupProbe,
    AuditStartupProbe,
    CapabilityProofStartupProbe,
    CrossCheckModelStartupProbe,
    DestinationChainProbe,
    DestinationTarget,
    EmbeddingStartupProbe,
    EnvironmentInjectionStartupProbe,
    EventBusRoundTripStartupProbe,
    KillSwitchStartupProbe,
    OpaCompileStartupProbe,
    StateStoreStartupProbe,
    StreamingModelStartupProbe,
    WorkloadIdentityStartupProbe,
)
from fdai.shared.providers.local.event_bus import LocalEventBus
from fdai.shared.providers.local.identity import LocalWorkloadIdentity
from fdai.shared.providers.startup_probe import StartupProbeRequest
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai.shared.resilience.kill_switch import StateStoreKillSwitch
from fdai.shared.telemetry import current_correlation_id


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
        self.correlations: list[str | None] = []

    async def embed(self, text: str) -> list[float]:
        self.calls += 1
        self.correlations.append(current_correlation_id())
        return [0.1, 0.2, 0.3]


class _Streaming:
    def __init__(self) -> None:
        self.correlations: list[str | None] = []

    def stream_startup_sample(self, sample: int) -> AsyncIterator[str]:
        async def chunks() -> AsyncIterator[str]:
            self.correlations.append(current_correlation_id())
            yield "bounded"
            yield "startup output"

        return chunks()


class _CrossCheck:
    def __init__(self) -> None:
        self.calls = 0
        self.correlations: list[str | None] = []

    async def propose(self, candidate: Any) -> tuple[str, dict[str, int]]:
        self.calls += 1
        self.correlations.append(current_correlation_id())
        return "startup-readiness-probe", {"sample": self.calls}


async def test_state_store_probe_performs_read_only_operation() -> None:
    store = InMemoryStateStore()
    probe = StateStoreStartupProbe(probe_id="postgres.read", state_store=store)

    result = await probe.run(_request())

    assert result.evidence == {"read": True}


async def test_audit_chain_probe_rejects_corrupt_chain() -> None:
    store = InMemoryStateStore()
    await store.append_audit_entry({"event_id": "event-1"})
    store._audit[0]["entry_hash"] = "sha256:tampered"  # noqa: SLF001
    probe = AuditChainStartupProbe(probe_id="audit.chain", state_store=store)

    result = await probe.run(_request())
    repeated = await probe.run(_request())

    assert result.status is ProbeStatus.FAILED
    assert result.failure_class == "audit_chain_integrity_failed"
    assert result.evidence == {"audit_chain_verified": False, "previously_proven": False}
    assert repeated.status is ProbeStatus.FAILED
    assert repeated.failure_class == "audit_chain_integrity_failed"
    assert repeated.evidence == {"audit_chain_verified": False, "previously_proven": True}


async def test_audit_chain_probe_reuses_successful_process_proof() -> None:
    class _CountingStore(InMemoryStateStore):
        def __init__(self) -> None:
            super().__init__()
            self.verify_calls = 0

        async def verify_chain(self) -> bool:
            self.verify_calls += 1
            return await super().verify_chain()

    store = _CountingStore()
    probe = AuditChainStartupProbe(probe_id="audit.chain", state_store=store)

    first = await probe.run(_request())
    second = await probe.run(_request())

    assert store.verify_calls == 1
    assert first.evidence == {"audit_chain_verified": True, "previously_proven": False}
    assert second.evidence == {"audit_chain_verified": True, "previously_proven": True}


async def test_audit_chain_probe_coalesces_concurrent_verification() -> None:
    class _BlockingStore(InMemoryStateStore):
        def __init__(self) -> None:
            super().__init__()
            self.verify_calls = 0
            self.started = asyncio.Event()
            self.release = asyncio.Event()

        async def verify_chain(self) -> bool:
            self.verify_calls += 1
            self.started.set()
            await self.release.wait()
            return True

    store = _BlockingStore()
    probe = AuditChainStartupProbe(probe_id="audit.chain", state_store=store)
    first_task = asyncio.create_task(probe.run(_request()))
    second_task = asyncio.create_task(probe.run(_request()))
    await store.started.wait()

    store.release.set()
    first, second = await asyncio.gather(first_task, second_task)

    assert store.verify_calls == 1
    assert first.evidence["previously_proven"] is False
    assert second.evidence["previously_proven"] is True


async def test_audit_chain_probe_backs_off_after_cancelled_verification() -> None:
    class _BlockingStore(InMemoryStateStore):
        def __init__(self) -> None:
            super().__init__()
            self.verify_calls = 0
            self.started = asyncio.Event()
            self.release = asyncio.Event()

        async def verify_chain(self) -> bool:
            self.verify_calls += 1
            self.started.set()
            await self.release.wait()
            return True

    current_time = [100.0]
    store = _BlockingStore()
    probe = AuditChainStartupProbe(
        probe_id="audit.chain",
        state_store=store,
        retry_interval_seconds=300,
        monotonic=lambda: current_time[0],
    )
    cancelled = asyncio.create_task(probe.run(_request()))
    await store.started.wait()

    cancelled.cancel()
    with pytest.raises(asyncio.CancelledError):
        await cancelled
    deferred = await probe.run(_request())

    assert store.verify_calls == 1
    assert deferred.status is ProbeStatus.FAILED
    assert deferred.failure_class == "audit_chain_verification_deferred"

    current_time[0] += 300
    store.release.set()
    recovered = await probe.run(_request())

    assert store.verify_calls == 2
    assert recovered.status is ProbeStatus.PASSED


async def test_audit_chain_probe_retries_immediate_transient_failure() -> None:
    class _TransientStore(InMemoryStateStore):
        def __init__(self) -> None:
            super().__init__()
            self.verify_calls = 0

        async def verify_chain(self) -> bool:
            self.verify_calls += 1
            if self.verify_calls == 1:
                raise ConnectionError("transient")
            return True

    store = _TransientStore()
    probe = AuditChainStartupProbe(probe_id="audit.chain", state_store=store)

    with pytest.raises(ConnectionError, match="transient"):
        await probe.run(_request())
    recovered = await probe.run(_request())

    assert store.verify_calls == 2
    assert recovered.status is ProbeStatus.PASSED


async def test_event_bus_probe_round_trips_synthetic_record() -> None:
    probe = EventBusRoundTripStartupProbe(
        probe_id="kafka.round-trip",
        event_bus=LocalEventBus(),
        topic="runtime.startup.probe",
        consumer_settle_seconds=0,
    )

    result = await probe.run(_request(synthetic_scope=True))

    assert result.evidence == {"round_trip": True}


async def test_event_bus_probe_skips_records_from_concurrent_revisions() -> None:
    bus = LocalEventBus()
    probe = EventBusRoundTripStartupProbe(
        probe_id="kafka.round-trip",
        event_bus=bus,
        topic="runtime.startup.probe",
        consumer_settle_seconds=0.01,
    )

    async def publish_unrelated() -> None:
        await asyncio.sleep(0)
        await bus.publish(
            "runtime.startup.probe",
            "startup-other-revision",
            {"kind": "startup_probe", "probe_id": "kafka.round-trip"},
        )

    unrelated = asyncio.create_task(publish_unrelated())
    result = await probe.run(_request(synthetic_scope=True))
    await unrelated

    assert result.evidence == {"round_trip": True}


async def test_event_bus_probe_rejects_forged_current_record() -> None:
    bus = LocalEventBus()
    key = "startup-00000000000000000000000000000000"
    await bus.publish(
        "runtime.startup.probe",
        key,
        {"kind": "startup_probe", "probe_id": "forged"},
    )
    probe = EventBusRoundTripStartupProbe(
        probe_id="kafka.round-trip",
        event_bus=bus,
        topic="runtime.startup.probe",
        consumer_settle_seconds=0,
    )

    with patch("fdai.delivery.startup_probe.uuid4", return_value=UUID(int=0)):
        with pytest.raises(RuntimeError, match="payload mismatch"):
            await probe.run(_request(synthetic_scope=True))


async def test_embedding_probe_collects_two_shape_samples() -> None:
    model = _Embedding()
    probe = EmbeddingStartupProbe(probe_id="model.embedding", model=model)

    result = await probe.run(_request())

    assert model.calls == 2
    assert result.model_evidence is not None
    assert result.model_evidence.sample_count == 2
    assert result.model_evidence.embedding_dimensions == 3
    assert len(result.model_evidence.total_latency_ms) == 2
    assert model.correlations == [
        "startup-readiness:model.embedding",
        "startup-readiness:model.embedding",
    ]
    assert current_correlation_id() is None


async def test_streaming_probe_records_ttft_total_and_token_rate_per_sample() -> None:
    model = _Streaming()
    probe = StreamingModelStartupProbe(probe_id="model.stream", model=model)

    result = await probe.run(_request())

    assert result.model_evidence is not None
    assert len(result.model_evidence.ttft_ms) == 2
    assert len(result.model_evidence.total_latency_ms) == 2
    assert len(result.model_evidence.output_token_rate) == 2
    assert all(value >= 0 for value in result.model_evidence.ttft_ms)
    assert model.correlations == [
        "startup-readiness:model.stream",
        "startup-readiness:model.stream",
    ]
    assert current_correlation_id() is None


async def test_capability_probe_requires_every_bounded_sample_to_pass() -> None:
    calls = 0
    correlations: list[str | None] = []

    async def prove() -> bool:
        nonlocal calls
        calls += 1
        correlations.append(current_correlation_id())
        return True

    probe = CapabilityProofStartupProbe(
        probe_id="model.tools",
        prove=prove,
        capability="tool_calling",
    )

    result = await probe.run(_request())

    assert calls == 2
    assert correlations == [
        "startup-readiness:model.tools",
        "startup-readiness:model.tools",
    ]
    assert current_correlation_id() is None
    assert result.model_evidence is not None
    assert result.model_evidence.tool_calling_proven is True


async def test_cross_check_probe_collects_two_structured_output_samples() -> None:
    model = _CrossCheck()
    probe = CrossCheckModelStartupProbe(probe_id="model.cross-check", model=model)
    request = _request()
    observed_at = (
        datetime(2026, 8, 29, 1, 0, tzinfo=UTC),
        datetime(2026, 8, 29, 1, 5, tzinfo=UTC),
        datetime(2026, 8, 29, 1, 10, tzinfo=UTC),
    )

    with patch("fdai.delivery.startup_model_probe.datetime") as clock:
        clock.now.side_effect = observed_at
        result = await probe.run(request)
        refreshed = await probe.run(request)
        refreshed_again = await probe.run(request)

    assert model.calls == 2
    assert model.correlations == [
        "startup-readiness:model.cross-check",
        "startup-readiness:model.cross-check",
    ]
    assert current_correlation_id() is None
    assert result.model_evidence is not None
    assert result.model_evidence.sample_count == 2
    assert result.model_evidence.structured_output_proven is True
    assert result.evidence == {"sampled": True, "previously_proven": False}
    assert refreshed.model_evidence == refreshed_again.model_evidence == result.model_evidence
    assert (
        refreshed.evidence
        == refreshed_again.evidence
        == {
            "sampled": False,
            "previously_proven": True,
        }
    )
    assert (result.observed_at, refreshed.observed_at, refreshed_again.observed_at) == observed_at
    assert (result.expires_at, refreshed.expires_at, refreshed_again.expires_at) == tuple(
        instant + timedelta(seconds=request.evidence_ttl_seconds) for instant in observed_at
    )


async def test_cross_check_probe_retries_after_sampling_failure() -> None:
    model = _CrossCheck()
    propose = AsyncMock(
        side_effect=[
            RuntimeError("transient"),
            ("startup-readiness-probe", {"sample": 0}),
            ("startup-readiness-probe", {"sample": 1}),
        ]
    )
    probe = CrossCheckModelStartupProbe(probe_id="model.cross-check", model=model)

    with patch.object(model, "propose", propose):
        with pytest.raises(RuntimeError, match="transient"):
            await probe.run(_request())
        result = await probe.run(_request())
        refreshed = await probe.run(_request())

    assert propose.await_count == 3
    assert result.evidence == {"sampled": True, "previously_proven": False}
    assert refreshed.evidence == {"sampled": False, "previously_proven": True}


async def test_cross_check_probe_samples_once_across_concurrent_refreshes() -> None:
    model = _CrossCheck()
    probe = CrossCheckModelStartupProbe(probe_id="model.cross-check", model=model)

    first, second = await asyncio.gather(
        probe.run(_request()),
        probe.run(_request()),
    )

    assert model.calls == 2
    assert first.model_evidence == second.model_evidence
    assert {first.evidence["sampled"], second.evidence["sampled"]} == {False, True}


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


async def test_destination_chain_proves_dns_tcp_tls_auth_and_protocol(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: dict[str, Any] = {}

    class _Loop:
        async def getaddrinfo(self, host: str, port: int, *, type: int) -> list[tuple[Any, ...]]:
            calls["dns"] = (host, port, type)
            return [(2, 1, 6, "", ("10.0.0.4", port))]

    class _Writer:
        def close(self) -> None:
            calls["closed"] = True

        async def wait_closed(self) -> None:
            calls["wait_closed"] = True

    async def open_connection(host: str, port: int, **kwargs: Any) -> tuple[object, _Writer]:
        calls["connect"] = (host, port, kwargs)
        return object(), _Writer()

    async def protocol_operation() -> None:
        calls["protocol"] = True

    monkeypatch.setattr("fdai.delivery.startup_probe.asyncio.get_running_loop", lambda: _Loop())
    monkeypatch.setattr("fdai.delivery.startup_probe.asyncio.open_connection", open_connection)
    probe = DestinationChainProbe(
        probe_id="destination.chain",
        target=DestinationTarget(
            host="service.example.com",
            port=443,
            tls_server_name="service.example.com",
            auth_audience="api://service/.default",
        ),
        identity=LocalWorkloadIdentity(),
        protocol_operation=protocol_operation,
    )

    result = await probe.run(_request())

    assert result.evidence == {
        "dns": True,
        "tcp": True,
        "tls": True,
        "auth": True,
        "protocol": True,
    }
    assert calls["connect"][2]["server_hostname"] == "service.example.com"
    assert calls["protocol"] is True


async def test_workload_identity_probe_records_no_token_material() -> None:
    probe = WorkloadIdentityStartupProbe(
        probe_id="identity.token",
        identity=LocalWorkloadIdentity(),
        audience="api://startup/.default",
    )

    result = await probe.run(_request())

    assert result.evidence == {"audience_scoped": True}
    assert "fdai-local" not in result.model_dump_json()


async def test_environment_injection_probe_fails_without_exposing_secret_name() -> None:
    probe = EnvironmentInjectionStartupProbe(
        probe_id="secret.injection",
        environment={},
        required_names=("FDAI_STATE_STORE_DSN",),
    )

    with pytest.raises(RuntimeError, match="unavailable") as captured:
        await probe.run(_request())
    assert "FDAI_STATE_STORE_DSN" not in str(captured.value)


async def test_audit_probe_appends_once_per_process_only_in_synthetic_scope() -> None:
    store = InMemoryStateStore()
    probe = AuditStartupProbe(probe_id="audit.append", state_store=store)

    with pytest.raises(RuntimeError, match="synthetic scope"):
        await probe.run(_request())
    first = await probe.run(_request(synthetic_scope=True))
    refreshed = await probe.run(_request(synthetic_scope=True))

    assert first.evidence == {"append": True, "previously_proven": False}
    assert refreshed.evidence == {"append": False, "previously_proven": True}
    assert (
        sum(
            entry.get("entry", {}).get("kind") == "startup_readiness.audit_probe"
            for entry in store.audit_entries
        )
        == 1
    )


async def test_audit_probe_retries_after_append_failure() -> None:
    store = InMemoryStateStore()
    probe = AuditStartupProbe(probe_id="audit.append", state_store=store)
    append = AsyncMock(side_effect=[RuntimeError("transient"), None])

    with patch.object(store, "append_audit_entry", append):
        with pytest.raises(RuntimeError, match="transient"):
            await probe.run(_request(synthetic_scope=True))
        result = await probe.run(_request(synthetic_scope=True))

    assert result.evidence == {"append": True, "previously_proven": False}
    assert append.await_count == 2


async def test_opa_compile_probe_accepts_successful_binary(tmp_path: Path) -> None:
    binary = tmp_path / "opa"
    binary.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    binary.chmod(0o700)
    probe = OpaCompileStartupProbe(
        probe_id="policy.compile",
        policies_root=tmp_path,
        opa_binary=str(binary),
    )

    result = await probe.run(_request())

    assert result.evidence == {"compiled": True}


async def test_event_bus_round_trip_rejects_non_synthetic_scope() -> None:
    probe = EventBusRoundTripStartupProbe(
        probe_id="kafka.round-trip",
        event_bus=LocalEventBus(),
        topic="runtime.startup.probe",
        consumer_settle_seconds=0,
    )

    with pytest.raises(RuntimeError, match="synthetic scope"):
        await probe.run(_request())
