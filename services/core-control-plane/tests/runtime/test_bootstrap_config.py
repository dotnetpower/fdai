from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from functools import partial
from pathlib import Path

import httpx
import pytest
from fdai.core.ontology_platform import MetricAggregation, MetricSemanticDefinition
from fdai.core.ontology_platform.metric_semantics import MetricSemanticRegistry
from fdai.core.ontology_platform.reconciliation_binding import (
    RECONCILIATION_OUTBOX_TOPIC,
    RECONCILIATION_REQUEST_TOPIC,
)
from fdai.core.readiness import (
    AuthorityCeiling,
    ReadinessDecision,
    reduce_startup_readiness,
)
from fdai.core.rule_semantic_generation import (
    RULE_GENERATION_ACTIVATION_COMMAND_TOPIC,
    RULE_GENERATION_ACTIVATION_RESULT_TOPIC,
    RuleGenerationActivationBinder,
    RuleGenerationOutboxPublisher,
    RuleGenerationPublishRetryableError,
)
from fdai.delivery.azure.dev_workload_identity import AsyncAzureCliWorkloadIdentity
from fdai.delivery.azure.workload_identity import ManagedIdentityWorkloadIdentity
from fdai.delivery.metric_window import ProviderMetricWindowReader
from fdai.delivery.persistence.postgres_topology_history import PostgresTopologyHistoryStore
from fdai.runtime.bootstrap import (
    _RUNTIME_LOGICAL_TOPICS,
    _schedule_semantic_turn_consumer,
)
from fdai.runtime.bootstrap_bindings import (
    RECONCILIATION_TOPICS,
    build_effect_reconciliation_request_binding,
    build_effect_reconciliation_worker,
    build_rule_generation_runtime_binding,
    semantic_query_providers,
)
from fdai.runtime.bootstrap_bindings import (
    build_runtime_workload_identity as _build_runtime_workload_identity,
)
from fdai.runtime.bootstrap_bindings import (
    case_history_identity_client_id as _case_history_identity_client_id,
)
from fdai.runtime.bootstrap_lifecycle import (
    build_runtime_saga as _build_runtime_saga,
)
from fdai.runtime.bootstrap_lifecycle import (
    build_semantic_turn_binding as _build_semantic_turn_binding,
)
from fdai.runtime.bootstrap_lifecycle import (
    log_rule_generation_outbox_exit,
    run_effect_reconciliation,
    run_rule_generation_outbox_publisher,
    runtime_process_lock,
)
from fdai.runtime.bootstrap_lifecycle import (
    raise_required_task_failure as _raise_required_task_failure,
)
from fdai.runtime.bootstrap_lifecycle import run_main as _run_main
from fdai.runtime.bootstrap_lifecycle import (
    semantic_turn_readiness_registration as _semantic_turn_readiness_registration,
)
from fdai.shared.config.runtime_flags import pantheon_start_enabled
from fdai.shared.providers.local.event_bus import LocalEventBus
from fdai.shared.providers.metric import MetricPoint, MetricQuery, NoopMetricProvider
from fdai.shared.providers.startup_probe import StartupProbeRequest
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai_service_contracts.semantic_turn import (
    SEMANTIC_PROJECTION_TOPIC,
    SEMANTIC_REQUEST_TOPIC,
)


def test_pantheon_starts_by_default() -> None:
    assert pantheon_start_enabled({}) is True


def test_runtime_multiplexes_startup_readiness_transitions() -> None:
    assert "runtime.readiness.transitions" in _RUNTIME_LOGICAL_TOPICS


def test_runtime_multiplexes_semantic_turn_channels() -> None:
    assert {SEMANTIC_REQUEST_TOPIC, SEMANTIC_PROJECTION_TOPIC}.issubset(_RUNTIME_LOGICAL_TOPICS)


def test_runtime_multiplexes_effect_reconciliation_channels() -> None:
    expected = {RECONCILIATION_REQUEST_TOPIC, RECONCILIATION_OUTBOX_TOPIC}
    assert RECONCILIATION_TOPICS == expected
    assert expected.issubset(_RUNTIME_LOGICAL_TOPICS)


def test_runtime_multiplexes_rule_generation_lifecycle_channels() -> None:
    expected = {
        RULE_GENERATION_ACTIVATION_COMMAND_TOPIC,
        RULE_GENERATION_ACTIVATION_RESULT_TOPIC,
    }
    assert expected.issubset(_RUNTIME_LOGICAL_TOPICS)


class _MetricProvider:
    async def query(self, _query: MetricQuery):
        if False:
            yield MetricPoint(
                metric_name="unused",
                value=0.0,
                at=datetime(2000, 1, 1, tzinfo=UTC),
            )


def _metric_registry() -> MetricSemanticRegistry:
    return MetricSemanticRegistry.build(
        (
            MetricSemanticDefinition(
                concept_id="metric.cpu.utilization",
                description="Average CPU utilization.",
                provider_metric="cpu.utilization",
                canonical_unit="percent",
                aggregation=MetricAggregation.AVERAGE,
            ),
        )
    )


def test_semantic_query_providers_bind_topology_only_with_state_store_dsn() -> None:
    topology, registry, window_provider = semantic_query_providers(
        state_store_dsn=" postgresql://state ",
        metric_provider=NoopMetricProvider(),
        metric_registry=_metric_registry(),
    )

    assert isinstance(topology, PostgresTopologyHistoryStore)
    assert registry is None
    assert window_provider is None


def test_semantic_query_providers_hide_incomplete_metric_binding() -> None:
    topology, registry, window_provider = semantic_query_providers(
        state_store_dsn=None,
        metric_provider=_MetricProvider(),
        metric_registry=None,
    )

    assert topology is None
    assert registry is None
    assert window_provider is None


def test_semantic_query_providers_bind_complete_metric_pair() -> None:
    expected_registry = _metric_registry()
    topology, registry, window_provider = semantic_query_providers(
        state_store_dsn=None,
        metric_provider=_MetricProvider(),
        metric_registry=expected_registry,
    )

    assert topology is None
    assert registry is expected_registry
    assert isinstance(window_provider, ProviderMetricWindowReader)


def test_effect_reconciliation_binding_requires_complete_evidence_providers() -> None:
    store = InMemoryStateStore()
    bus = LocalEventBus()

    assert (
        build_effect_reconciliation_worker(
            state_store=store,
            event_bus=bus,
            artifact_resolver=None,
            observation_verifier=None,
            environment={},
        )
        is None
    )
    with pytest.raises(RuntimeError, match="requires an observation verifier"):
        build_effect_reconciliation_worker(
            state_store=store,
            event_bus=bus,
            artifact_resolver=object(),  # type: ignore[arg-type]
            observation_verifier=None,
            environment={},
        )


def test_effect_reconciliation_binding_builds_configured_worker() -> None:
    worker = build_effect_reconciliation_worker(
        state_store=InMemoryStateStore(),
        event_bus=LocalEventBus(),
        artifact_resolver=object(),  # type: ignore[arg-type]
        observation_verifier=object(),  # type: ignore[arg-type]
        environment={"HOSTNAME": "core-a", "FDAI_EFFECT_RECONCILIATION_GROUP_ID": "group-a"},
    )

    assert worker is not None


def test_reconciliation_request_binding_requires_complete_producer_sources() -> None:
    store = InMemoryStateStore()
    bus = LocalEventBus()

    assert (
        build_effect_reconciliation_request_binding(
            state_store=store,
            event_bus=bus,
            artifact_source=None,
            observation_source=None,
            environment={},
        )
        is None
    )
    with pytest.raises(RuntimeError, match="requires artifact and observation sources"):
        build_effect_reconciliation_request_binding(
            state_store=store,
            event_bus=bus,
            artifact_source=object(),  # type: ignore[arg-type]
            observation_source=None,
            environment={},
        )


def test_reconciliation_request_binding_shares_one_durable_outbox() -> None:
    binding = build_effect_reconciliation_request_binding(
        state_store=InMemoryStateStore(),
        event_bus=LocalEventBus(),
        artifact_source=object(),  # type: ignore[arg-type]
        observation_source=object(),  # type: ignore[arg-type]
        environment={"HOSTNAME": "core-a"},
    )

    assert binding is not None
    assert binding.producer._outbox is binding.outbox_publisher._outbox


def test_rule_generation_binding_shares_one_ledger_when_index_is_available() -> None:
    binding = build_rule_generation_runtime_binding(
        state_store=InMemoryStateStore(),
        event_bus=LocalEventBus(),
        catalog_index=object(),  # type: ignore[arg-type]
        environment={"HOSTNAME": "core-a"},
    )

    assert isinstance(binding.activation_binder, RuleGenerationActivationBinder)
    assert isinstance(binding.outbox_publisher, RuleGenerationOutboxPublisher)
    assert binding.activation_binder._ledger is binding.ledger
    assert binding.outbox_publisher._ledger is binding.ledger


def test_rule_generation_binding_keeps_publisher_when_index_is_unavailable() -> None:
    binding = build_rule_generation_runtime_binding(
        state_store=InMemoryStateStore(),
        event_bus=LocalEventBus(),
        catalog_index=None,
        environment={},
    )

    assert binding.activation_binder is None
    assert isinstance(binding.outbox_publisher, RuleGenerationOutboxPublisher)
    assert binding.outbox_publisher._ledger is binding.ledger


@pytest.mark.parametrize("hostname", ["", "   "])
def test_rule_generation_binding_defaults_empty_claimant_identity(hostname: str) -> None:
    binding = build_rule_generation_runtime_binding(
        state_store=InMemoryStateStore(),
        event_bus=LocalEventBus(),
        catalog_index=None,
        environment={"HOSTNAME": hostname},
    )

    assert binding.outbox_publisher._claimant_id == "fdai-core"


async def test_effect_reconciliation_lifecycle_bounds_drain_and_cancels_subscriber() -> None:
    stop = asyncio.Event()

    class _Worker:
        def __init__(self) -> None:
            self.subscriber_cancelled = False
            self.drain_limits: list[int] = []

        async def run_subscriber(self) -> None:
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                self.subscriber_cancelled = True
                raise

        async def drain_pending(self, *, limit: int = 100) -> tuple[object, ...]:
            self.drain_limits.append(limit)
            stop.set()
            return ()

    worker = _Worker()

    await asyncio.wait_for(
        run_effect_reconciliation(
            worker=worker,  # type: ignore[arg-type]
            stop=stop,
            drain_interval_seconds=0.01,
            shutdown_timeout_seconds=0.1,
        ),
        timeout=0.5,
    )

    assert worker.drain_limits == [100]
    assert worker.subscriber_cancelled is True


async def test_rule_generation_outbox_lifecycle_bounds_drain_and_stops() -> None:
    stop = asyncio.Event()

    class _Publisher:
        def __init__(self) -> None:
            self.drain_limits: list[int] = []

        async def drain_pending(self, *, limit: int = 100) -> tuple[object, ...]:
            self.drain_limits.append(limit)
            stop.set()
            return ()

    publisher = _Publisher()

    await run_rule_generation_outbox_publisher(
        publisher=publisher,  # type: ignore[arg-type]
        stop=stop,
        drain_limit=17,
        drain_interval_seconds=0.01,
    )

    assert publisher.drain_limits == [17]


@pytest.mark.parametrize(
    ("drain_limit", "drain_interval_seconds"),
    [(0, 1.0), (1001, 1.0), (100, 0.0)],
)
async def test_rule_generation_outbox_lifecycle_rejects_invalid_bounds(
    drain_limit: int,
    drain_interval_seconds: float,
) -> None:
    with pytest.raises(ValueError, match="Rule generation outbox"):
        await run_rule_generation_outbox_publisher(
            publisher=object(),  # type: ignore[arg-type]
            stop=asyncio.Event(),
            drain_limit=drain_limit,
            drain_interval_seconds=drain_interval_seconds,
        )


async def test_rule_generation_outbox_lifecycle_propagates_transport_failure() -> None:
    class _Publisher:
        async def drain_pending(self, *, limit: int = 100) -> tuple[object, ...]:
            raise RuntimeError("broker unavailable")

    with pytest.raises(RuntimeError, match="broker unavailable"):
        await run_rule_generation_outbox_publisher(
            publisher=_Publisher(),  # type: ignore[arg-type]
            stop=asyncio.Event(),
            drain_interval_seconds=0.01,
        )


async def test_rule_generation_outbox_lifecycle_retries_released_publish_failure(
    caplog: pytest.LogCaptureFixture,
) -> None:
    stop = asyncio.Event()

    class _Publisher:
        def __init__(self) -> None:
            self.calls = 0

        async def drain_pending(self, *, limit: int = 100) -> tuple[object, ...]:
            self.calls += 1
            if self.calls == 1:
                raise RuleGenerationPublishRetryableError("broker_publish_failed")
            stop.set()
            return ()

    publisher = _Publisher()
    caplog.set_level("WARNING", logger="fdai.startup")

    await run_rule_generation_outbox_publisher(
        publisher=publisher,  # type: ignore[arg-type]
        stop=stop,
        drain_interval_seconds=0.001,
    )

    assert publisher.calls == 2
    assert "rule_generation_outbox_publish_retry_scheduled" in caplog.messages


async def test_rule_generation_outbox_fatal_exit_is_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def _fail() -> None:
        raise RuntimeError("broker unavailable")

    caplog.set_level("ERROR", logger="fdai.startup")
    task = asyncio.create_task(_fail())
    task.add_done_callback(log_rule_generation_outbox_exit)

    with pytest.raises(RuntimeError, match="broker unavailable"):
        await task
    await asyncio.sleep(0)

    assert "rule_generation_outbox_failed" in caplog.messages


async def test_rule_generation_outbox_clean_shutdown_is_not_warned(
    caplog: pytest.LogCaptureFixture,
) -> None:
    stop = asyncio.Event()
    stop.set()

    async def _exit() -> None:
        return None

    caplog.set_level("WARNING", logger="fdai.startup")
    task = asyncio.create_task(_exit())
    task.add_done_callback(partial(log_rule_generation_outbox_exit, stop=stop))

    await task
    await asyncio.sleep(0)

    assert "rule_generation_outbox_exited_early" not in caplog.messages


async def test_rule_generation_outbox_exit_without_shutdown_is_warned(
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def _exit() -> None:
        return None

    caplog.set_level("WARNING", logger="fdai.startup")
    task = asyncio.create_task(_exit())
    task.add_done_callback(partial(log_rule_generation_outbox_exit, stop=asyncio.Event()))

    await task
    await asyncio.sleep(0)

    assert "rule_generation_outbox_exited_early" in caplog.messages


async def test_semantic_turn_bootstrap_exposes_exact_missing_runtime_reason() -> None:
    binding = _build_semantic_turn_binding(
        state_store=InMemoryStateStore(),
        config={
            "FDAI_SEMANTIC_TURN_REQUEST_TOPIC": "operator.request",
            "FDAI_SEMANTIC_TURN_PROJECTION_TOPIC": "operator.projection",
            "FDAI_SEMANTIC_TURN_CONSUMER_GROUP_ID": "core-semantic",
        },
        unavailable_reason="semantic_ontology_store_unavailable",
    )

    assert binding is not None
    assert binding.request_topic == "operator.request"
    assert binding.projection_topic == "operator.projection"
    assert binding.group_id == "core-semantic"
    assert binding.available is False
    assert binding.unavailable_reason == "semantic_ontology_store_unavailable"

    specs, probes = _semantic_turn_readiness_registration(binding)
    now = datetime.now(UTC)
    result = await probes[0].run(
        StartupProbeRequest(
            deadline=now + timedelta(seconds=5),
            cost_limit_usd=0,
            model_sample_count=2,
            synthetic_scope=False,
        )
    )
    report = reduce_startup_readiness(specs, (result,), generated_at=now)

    assert report.decision is ReadinessDecision.DEGRADED
    assert report.authority_ceilings["semantic-query"] is AuthorityCeiling.DISABLED
    assert result.failure_class == "semantic_ontology_store_unavailable"


async def test_semantic_turn_bootstrap_reports_bound_runtime_available() -> None:
    binding = _build_semantic_turn_binding(
        state_store=InMemoryStateStore(),
        config={
            "FDAI_SEMANTIC_TURN_REQUEST_TOPIC": "operator.request",
            "FDAI_SEMANTIC_TURN_PROJECTION_TOPIC": "operator.projection",
        },
        runtime=object(),
    )

    assert binding is not None
    assert binding.available is True
    assert binding.unavailable_reason is None
    specs, probes = _semantic_turn_readiness_registration(binding)
    now = datetime.now(UTC)
    result = await probes[0].run(
        StartupProbeRequest(
            deadline=now + timedelta(seconds=5),
            cost_limit_usd=0,
            model_sample_count=2,
            synthetic_scope=False,
        )
    )
    report = reduce_startup_readiness(specs, (result,), generated_at=now)

    assert result.status.value == "passed"
    assert report.decision is ReadinessDecision.READY


async def test_semantic_turn_bootstrap_schedules_configured_binding() -> None:
    calls: list[tuple[LocalEventBus, asyncio.Event]] = []

    class _Binding:
        async def run(self, *, bus: LocalEventBus, stop: asyncio.Event) -> None:
            calls.append((bus, stop))

    class _Ready:
        async def run_when_ready(self, stop: asyncio.Event, operation: object) -> None:
            await operation()  # type: ignore[operator]

    bus = LocalEventBus()
    stop = asyncio.Event()
    task = _schedule_semantic_turn_consumer(
        binding=_Binding(),
        readiness=_Ready(),  # type: ignore[arg-type]
        bus=bus,
        stop=stop,
    )

    assert task is not None
    assert task.get_name() == "semantic-turn-consumer"
    await task
    assert calls == [(bus, stop)]


@pytest.mark.parametrize("value", ["0", "false", "NO", "off"])
def test_pantheon_requires_explicit_disable(value: str) -> None:
    assert pantheon_start_enabled({"FDAI_START_PANTHEON": value}) is False


@pytest.mark.parametrize("value", ["1", "true", "yes", "on"])
def test_pantheon_accepts_explicit_enable(value: str) -> None:
    assert pantheon_start_enabled({"FDAI_START_PANTHEON": value}) is True


async def test_dev_runtime_uses_explicit_azure_cli_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RUNTIME_ENV", "dev")
    monkeypatch.setenv("FDAI_RUNTIME_LOCAL_AZURE_CLI", "1")
    monkeypatch.setenv("AZURE_SUBSCRIPTION_ID", "subscription-a")
    monkeypatch.setenv("AZURE_TENANT_ID", "tenant-a")

    async with httpx.AsyncClient() as http_client:
        identity = _build_runtime_workload_identity(http_client)

    assert isinstance(identity, AsyncAzureCliWorkloadIdentity)
    assert identity.credential.subscription_id == "subscription-a"
    assert identity.credential.tenant_id == "tenant-a"


async def test_non_dev_runtime_keeps_managed_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RUNTIME_ENV", "production")
    monkeypatch.setenv("FDAI_RUNTIME_LOCAL_AZURE_CLI", "1")
    monkeypatch.setenv("IDENTITY_ENDPOINT", "http://127.0.0.1/identity")
    monkeypatch.setenv("IDENTITY_HEADER", "test-header")

    async with httpx.AsyncClient() as http_client:
        identity = _build_runtime_workload_identity(http_client)

    assert isinstance(identity, ManagedIdentityWorkloadIdentity)


async def test_case_history_runtime_requires_dedicated_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RUNTIME_ENV", "production")
    monkeypatch.setenv("IDENTITY_ENDPOINT", "https://identity.local/token")
    monkeypatch.setenv("IDENTITY_HEADER", "test-header")
    monkeypatch.delenv("FDAI_CASE_HISTORY_MI_CLIENT_ID", raising=False)

    async with httpx.AsyncClient() as http_client:
        with pytest.raises(RuntimeError, match="FDAI_CASE_HISTORY_MI_CLIENT_ID"):
            _build_runtime_workload_identity(
                http_client,
                client_id_env="FDAI_CASE_HISTORY_MI_CLIENT_ID",
                require_client_id=True,
            )


async def test_case_history_runtime_selects_dedicated_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200,
            json={"access_token": "token", "expires_on": "4102444800"},
        )

    monkeypatch.setenv("RUNTIME_ENV", "production")
    monkeypatch.setenv("IDENTITY_ENDPOINT", "https://identity.local/token")
    monkeypatch.setenv("IDENTITY_HEADER", "test-header")
    monkeypatch.setenv("FDAI_CASE_HISTORY_MI_CLIENT_ID", "case-history-client")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        identity = _build_runtime_workload_identity(
            http_client,
            client_id_env="FDAI_CASE_HISTORY_MI_CLIENT_ID",
            require_client_id=True,
        )
        await identity.get_token("https://storage.azure.com/")

    assert captured[0].url.params["client_id"] == "case-history-client"


def test_case_history_startup_requires_identity_before_runtime_branching() -> None:
    with pytest.raises(RuntimeError, match="FDAI_CASE_HISTORY_MI_CLIENT_ID"):
        _case_history_identity_client_id({"FDAI_CASE_HISTORY_CONTAINER_URL": "https://example"})


def test_case_history_startup_rejects_executor_identity_reuse() -> None:
    with pytest.raises(RuntimeError, match="MUST be distinct"):
        _case_history_identity_client_id(
            {
                "FDAI_CASE_HISTORY_MI_CLIENT_ID": "shared-client",
                "FDAI_MI_CLIENT_ID": "shared-client",
            }
        )


async def test_runtime_saga_uses_durable_state_store_audit() -> None:
    state_store = InMemoryStateStore()
    saga = _build_runtime_saga(state_store)
    assert saga.durable_audit is True

    await saga.on_typed_message(
        "object.forecast-outcome",
        {
            "producer_principal": "Heimdall",
            "correlation_id": "corr-forecast",
            "outcome_id": "outcome-1",
        },
    )

    assert len(tuple(state_store.audit_entries)) == 1


async def test_required_runtime_task_failure_is_not_swallowed() -> None:
    async def fail() -> None:
        raise RuntimeError("retention publisher unavailable")

    task = asyncio.create_task(fail(), name="case-history-retention-ticks")
    await asyncio.gather(task, return_exceptions=True)

    with pytest.raises(RuntimeError, match="case-history-retention-ticks") as captured:
        _raise_required_task_failure({task})
    assert isinstance(captured.value.__cause__, RuntimeError)
    assert str(captured.value.__cause__) == "retention publisher unavailable"


def test_runtime_main_returns_async_result() -> None:
    async def complete() -> int:
        return 7

    assert _run_main(complete) == 7


def test_runtime_main_maps_keyboard_interrupt_to_clean_exit() -> None:
    async def interrupted() -> int:
        raise KeyboardInterrupt

    assert _run_main(interrupted) == 0


def test_runtime_process_lock_rejects_duplicate_local_instance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FDAI_RUNTIME_LOCK_FILE", str(tmp_path / "runtime.lock"))

    with runtime_process_lock():
        with pytest.raises(RuntimeError, match="already active"):
            with runtime_process_lock():
                pass


def test_runtime_process_lock_defaults_for_local_azure_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("FDAI_RUNTIME_LOCK_FILE", raising=False)
    monkeypatch.setenv("RUNTIME_ENV", "dev")
    monkeypatch.setenv("FDAI_RUNTIME_LOCAL_AZURE_CLI", "1")

    with runtime_process_lock():
        assert (tmp_path / ".fdai/core-runtime.lock").is_file()
        with pytest.raises(RuntimeError, match="already active"):
            with runtime_process_lock():
                pass


def test_runtime_process_lock_remains_optional_outside_local_azure_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("FDAI_RUNTIME_LOCK_FILE", raising=False)
    monkeypatch.setenv("RUNTIME_ENV", "production")
    monkeypatch.setenv("FDAI_RUNTIME_LOCAL_AZURE_CLI", "1")

    with runtime_process_lock():
        with runtime_process_lock():
            pass
