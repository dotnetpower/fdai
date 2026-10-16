from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.executor.lock import ResourceLockManager
from fdai.core.rca import (
    DEFAULT_TELEMETRY_RECIPE_CATALOG,
    TelemetryEvidenceDisposition,
    build_telemetry_evidence_receipt,
)
from fdai.runtime.adaptive_telemetry import (
    ADAPTIVE_TELEMETRY_CONFIG_VERSION,
    AdaptiveTelemetryRuntimeConfig,
    build_adaptive_telemetry_investigator,
)
from fdai.shared.ontology.release import build_ontology_release
from fdai.shared.providers.testing.process_runtime import InMemoryProcessRuntimeStore


class _CompleteProvider:
    def __init__(self) -> None:
        self.calls = 0

    async def gather(self, need):
        self.calls += 1
        recipe = DEFAULT_TELEMETRY_RECIPE_CATALOG.get(need.recipe_id, need.recipe_version)
        return build_telemetry_evidence_receipt(
            need=need,
            observed_until=need.evidence_cutoff,
            disposition=TelemetryEvidenceDisposition.COMPLETE,
            route_count=1,
            queried_route_count=1,
            row_count=1,
            latency_ms=2,
            estimated_cost_units=recipe.estimated_cost_units,
            actual_cost_units=recipe.estimated_cost_units,
            fact_tokens=(f"mechanism:{recipe.mechanism.value}", "signal_count_band:low"),
            complete=True,
            truncated=False,
        )


def _build(
    provider,
    store,
    environment,
    *,
    clock: Callable[[], datetime] | None = None,
    resource_lock=None,
):
    return build_adaptive_telemetry_investigator(
        provider=provider,
        process_store=store,
        ontology_release=build_ontology_release(),
        object_types=(),
        link_types=(),
        action_types=(),
        interface_types=(),
        function_types=(),
        environment=environment,
        clock=clock,
        resource_lock=resource_lock or ResourceLockManager(),
    )


@pytest.mark.asyncio
async def test_enabled_runtime_persists_process_and_returns_bounded_complete_citation() -> None:
    provider = _CompleteProvider()
    store = InMemoryProcessRuntimeStore()
    investigator = _build(
        provider,
        store,
        {
            "FDAI_RCA_ADAPTIVE_TELEMETRY_ENABLED": "true",
            "FDAI_RCA_ADAPTIVE_TELEMETRY_MAX_ROUNDS": "2",
            "FDAI_RCA_ADAPTIVE_TELEMETRY_MAX_QUERIES": "2",
            "FDAI_RCA_ADAPTIVE_TELEMETRY_MAX_COST_UNITS": "80",
        },
    )
    assert investigator is not None
    evidence_cutoff = datetime.now(UTC)

    result = await investigator.investigate(
        incident_id="incident:one",
        resource_ref="resource:one",
        event_type="http.429.detected",
        resource_type="application",
        evidence_cutoff=evidence_cutoff,
        correlation_id="correlation:one",
    )

    assert provider.calls == 1
    assert result.investigation.used_queries == 1
    assert result.investigation.used_cost_units == 10
    assert result.investigation.execution_authority is False
    assert len(result.citations) == 1
    assert result.citations[0].ref.startswith("telemetry-receipt:sha256:")
    assert "disposition:complete" in result.citations[0].facts
    assert any(item.startswith("mechanism:") for item in result.citations[0].facts)
    snapshot = await store.get(result.investigation.session_id)
    assert snapshot is not None
    assert snapshot.status.terminal is True

    replayed = await investigator.investigate(
        incident_id="incident:one",
        resource_ref="resource:one",
        event_type="http.429.detected",
        resource_type="application",
        evidence_cutoff=evidence_cutoff,
        correlation_id="correlation:one",
    )
    assert provider.calls == 1
    assert replayed.investigation == result.investigation
    assert replayed.citations == result.citations


def test_available_provider_defaults_on_but_explicit_disable_or_missing_provider_holds() -> None:
    store = InMemoryProcessRuntimeStore()
    release = build_ontology_release()

    assert (
        build_adaptive_telemetry_investigator(
            provider=_CompleteProvider(),
            process_store=store,
            ontology_release=release,
            object_types=(),
            link_types=(),
            action_types=(),
            interface_types=(),
            function_types=(),
            environment={},
            resource_lock=ResourceLockManager(),
        )
        is not None
    )
    assert (
        build_adaptive_telemetry_investigator(
            provider=_CompleteProvider(),
            process_store=store,
            ontology_release=release,
            object_types=(),
            link_types=(),
            action_types=(),
            interface_types=(),
            function_types=(),
            environment={"FDAI_RCA_ADAPTIVE_TELEMETRY_ENABLED": "false"},
            resource_lock=ResourceLockManager(),
        )
        is None
    )
    assert (
        build_adaptive_telemetry_investigator(
            provider=None,
            process_store=store,
            ontology_release=release,
            object_types=(),
            link_types=(),
            action_types=(),
            interface_types=(),
            function_types=(),
            environment={"FDAI_RCA_ADAPTIVE_TELEMETRY_ENABLED": "true"},
            resource_lock=ResourceLockManager(),
        )
        is None
    )


def test_runtime_config_rejects_malformed_or_excessive_bounds() -> None:
    with pytest.raises(ValueError, match="MUST be a boolean"):
        AdaptiveTelemetryRuntimeConfig.from_environment(
            {"FDAI_RCA_ADAPTIVE_TELEMETRY_ENABLED": "sometimes"}
        )
    with pytest.raises(ValueError, match="max_rounds"):
        AdaptiveTelemetryRuntimeConfig.from_environment(
            {"FDAI_RCA_ADAPTIVE_TELEMETRY_MAX_ROUNDS": "9"}
        )


def test_runtime_policy_digest_is_versioned_stable_and_bound_sensitive() -> None:
    baseline = AdaptiveTelemetryRuntimeConfig(enabled=True)

    assert ADAPTIVE_TELEMETRY_CONFIG_VERSION == "1.1.0"
    assert baseline.policy_digest == AdaptiveTelemetryRuntimeConfig(enabled=True).policy_digest
    assert (
        baseline.policy_digest
        != AdaptiveTelemetryRuntimeConfig(
            enabled=True,
            max_cost_units=121,
        ).policy_digest
    )


@pytest.mark.parametrize("delay", [timedelta(minutes=1), timedelta(days=30)])
async def test_delayed_event_receives_a_new_execution_budget_and_replays_without_io(delay):
    now = datetime(2026, 10, 16, tzinfo=UTC)
    provider = _CompleteProvider()
    store = InMemoryProcessRuntimeStore()
    investigator = _build(provider, store, {}, clock=lambda: now)
    assert investigator is not None
    cutoff = now - delay
    arguments = {
        "incident_id": "incident:delayed",
        "resource_ref": "resource:one",
        "event_type": "http.429.detected",
        "resource_type": "application",
        "evidence_cutoff": cutoff,
        "correlation_id": "correlation:delayed",
    }

    result = await investigator.investigate(**arguments)

    assert provider.calls == 1
    assert result.investigation.budget.deadline_at == now + timedelta(seconds=4)
    assert result.investigation.used_queries == 1
    assert len(result.citations) == 1
    now += timedelta(hours=1)
    replayed = await investigator.investigate(**arguments)
    assert provider.calls == 1
    assert replayed.investigation == result.investigation


async def test_future_evidence_cutoff_is_rejected_before_io_or_process_creation():
    now = datetime(2026, 10, 16, tzinfo=UTC)
    provider = _CompleteProvider()
    investigator = _build(provider, InMemoryProcessRuntimeStore(), {}, clock=lambda: now)
    assert investigator is not None
    with pytest.raises(ValueError, match="MUST NOT be in the future"):
        await investigator.investigate(
            incident_id="incident:future",
            resource_ref="resource:one",
            event_type="http.429.detected",
            resource_type="application",
            evidence_cutoff=now + timedelta(seconds=1),
            correlation_id="correlation:future",
        )
    assert provider.calls == 0


async def test_concurrent_duplicate_sessions_share_the_winning_deadline_and_single_read():
    now = datetime(2026, 10, 16, tzinfo=UTC)
    entered, release = asyncio.Event(), asyncio.Event()

    class _BlockingProvider(_CompleteProvider):
        async def gather(self, need):
            entered.set()
            await release.wait()
            return await super().gather(need)

    provider = _BlockingProvider()
    store, lock = InMemoryProcessRuntimeStore(), ResourceLockManager()
    first = _build(provider, store, {}, clock=lambda: now, resource_lock=lock)
    second = _build(
        provider,
        store,
        {},
        clock=lambda: now + timedelta(milliseconds=1),
        resource_lock=lock,
    )
    assert first is not None and second is not None
    arguments = {
        "incident_id": "incident:concurrent",
        "resource_ref": "resource:one",
        "event_type": "http.429.detected",
        "resource_type": "application",
        "evidence_cutoff": now - timedelta(minutes=1),
        "correlation_id": "correlation:concurrent",
    }
    first_task = asyncio.create_task(first.investigate(**arguments))
    await entered.wait()
    second_task = asyncio.create_task(second.investigate(**arguments))
    await asyncio.sleep(0)
    release.set()
    one, two = await asyncio.gather(first_task, second_task)
    assert provider.calls == 1
    assert one.investigation == two.investigation
    assert one.investigation.budget.deadline_at == now + timedelta(seconds=4)


async def test_session_lock_wait_is_inside_the_execution_deadline():
    class _BlockedLock(ResourceLockManager):
        @asynccontextmanager
        async def acquire(self, resource_id):
            await asyncio.Event().wait()
            yield

    now = datetime(2026, 10, 16, tzinfo=UTC)
    provider = _CompleteProvider()
    investigator = _build(
        provider,
        InMemoryProcessRuntimeStore(),
        {"FDAI_RCA_ADAPTIVE_TELEMETRY_DEADLINE_SECONDS": "1"},
        clock=lambda: now,
        resource_lock=_BlockedLock(),
    )
    assert investigator is not None
    with pytest.raises(TimeoutError):
        await investigator.investigate(
            incident_id="incident:lock",
            resource_ref="resource:one",
            event_type="http.429.detected",
            resource_type="application",
            evidence_cutoff=now,
            correlation_id="correlation:lock",
        )
    assert provider.calls == 0


async def test_active_query_timeout_persists_a_replayable_terminal_result():
    class _NeverCompletingProvider(_CompleteProvider):
        async def gather(self, need):
            self.calls += 1
            await asyncio.Event().wait()
            raise AssertionError("unreachable")

    provider = _NeverCompletingProvider()
    investigator = _build(
        provider,
        InMemoryProcessRuntimeStore(),
        {"FDAI_RCA_ADAPTIVE_TELEMETRY_DEADLINE_SECONDS": "1"},
    )
    assert investigator is not None
    arguments = {
        "incident_id": "incident:blocked-query",
        "resource_ref": "resource:one",
        "event_type": "http.429.detected",
        "resource_type": "application",
        "evidence_cutoff": datetime.now(UTC) - timedelta(minutes=1),
        "correlation_id": "correlation:blocked-query",
    }
    result = await investigator.investigate(**arguments)
    replayed = await investigator.investigate(**arguments)
    assert result.investigation.disposition.value == "timed_out"
    assert replayed.investigation == result.investigation
    assert provider.calls == 1
