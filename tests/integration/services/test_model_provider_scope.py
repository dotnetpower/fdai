"""Typed configured-role coverage survives Core collection and the existing Operator reader."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fdai.composition import LlmBindings
from fdai.core.notifications.matrix import load_matrix_from_yaml
from fdai.core.readiness.self_health import load_self_health_catalog
from fdai.core.readiness.self_health_runtime import SelfHealthRuntimeMonitor
from fdai.delivery.azure.llm import embeddings as embedding_module
from fdai.delivery.azure.llm.cross_check import (
    AzureOpenAICrossCheckModel,
    AzureOpenAICrossCheckModelConfig,
)
from fdai.delivery.azure.llm.embeddings import (
    AzureOpenAIEmbeddingModel,
    AzureOpenAIEmbeddingModelConfig,
)
from fdai.delivery.azure.llm.provider_observations import (
    ConfiguredModelProviderScope,
    EmbeddingProviderObservations,
)
from fdai.delivery.self_health_sources import runtime_self_health_registry
from fdai.runtime.bootstrap_readiness import build_runtime_model_provider_scope
from fdai.runtime.readiness import RuntimeReadinessState
from fdai.shared.providers.local.identity import LocalWorkloadIdentity
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai_operator_service import runtime_projection_reader as operator_module
from fdai_operator_service.families.operations import (
    ProjectionQuery,
    ProjectionUnavailableError,
)
from fdai_operator_service.runtime_projection_reader import (
    RuntimeProjectionReader,
    RuntimeProjectionReaderConfig,
)
from fdai_service_contracts import OperatorRole
from fdai_service_contracts.compatibility import canonical_digest
from fdai_service_contracts.model_provider_health import (
    ConfiguredModelBindingV1,
    ModelProviderHealth,
    ModelProviderScopeSnapshotV1,
)
from fdai_service_contracts.self_health import (
    OperationalStateSnapshotV1,
    SelfHealthSignalName,
    SelfHealthSignalStatus,
    SelfHealthSnapshotV1,
    operational_state_snapshot_digest,
    self_health_snapshot_digest,
)

ROOT = Path(__file__).resolve().parents[3]
NOW = datetime(2026, 10, 19, tzinfo=UTC)


def _catalog():
    matrix = load_matrix_from_yaml(ROOT / "config/notifications-matrix.yaml")
    return load_self_health_catalog(
        ROOT / "config/self-health-signals.yaml",
        route_fallbacks={name: route.on_all_fail.value for name, route in matrix.routes.items()},
    )


def _registry(store):
    state = RuntimeReadinessState()
    return runtime_self_health_registry(
        catalog=_catalog(),
        store=store,
        readiness=lambda now: state.is_ready(now=now),
        runtime_policy={"logging.level": "INFO"},
    )


def _container(model, other, *, revision="a", registered=True):
    bindings = LlmBindings(embedding_model=model, cross_check_models=(other,))
    return SimpleNamespace(
        require_llm_bindings=lambda: bindings,
        resolved_models=(
            SimpleNamespace(
                capabilities=(
                    SimpleNamespace(name="t1.embedding"),
                    SimpleNamespace(name="t2.reasoner.primary"),
                )
            )
            if registered
            else None
        ),
        resolved_models_artifact_digest=revision * 64 if registered else None,
    )


def _other(client):
    return AzureOpenAICrossCheckModel(
        identity=LocalWorkloadIdentity(),
        http_client=client,
        config=AzureOpenAICrossCheckModelConfig(
            endpoint="https://example.openai.azure.com",
            deployment="configured-reasoner",
            system_prompt="test-only binding",
        ),
    )


def _embedding(client, *, deployment="embedding"):
    return AzureOpenAIEmbeddingModel(
        identity=LocalWorkloadIdentity(),
        http_client=client,
        config=AzureOpenAIEmbeddingModelConfig(
            endpoint="https://example.openai.azure.com",
            deployment=deployment,
            dim=2,
        ),
    )


@pytest.fixture(autouse=True)
def _clock(monkeypatch):
    factory = EmbeddingProviderObservations
    monkeypatch.setattr(
        embedding_module,
        "EmbeddingProviderObservations",
        lambda **kwargs: factory(clock=lambda: NOW, **kwargs),
    )
    monkeypatch.setattr(operator_module, "_model_scope_read_now", lambda: NOW)


class Fallback:
    async def read(self, query):
        raise AssertionError("runtime-state must use its real typed reader")


async def _operator(store, monkeypatch):
    async def fetch(self, statement, parameters=()):
        assert parameters == ("runtime:operational-state",)
        value = await store.read_state(parameters[0])
        return [{"value": value}]

    monkeypatch.setattr(RuntimeProjectionReader, "_fetch_all", fetch)
    reader = RuntimeProjectionReader(
        RuntimeProjectionReaderConfig("postgresql://example.invalid/fdai"),
        Fallback(),
    )
    return await reader.read(
        ProjectionQuery(
            operation="runtime.operational-state",
            principal_id="reader",
            path={},
            params={},
            limit=100,
            cursor=None,
            roles=frozenset({OperatorRole.READER}),
        )
    )


@pytest.mark.parametrize("observed", [False, True])
async def test_configured_second_role_remains_unknown_through_actual_collector_and_reader(
    monkeypatch, observed
) -> None:
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"data": [{"embedding": [0.1, 0.2]}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        model = _embedding(client)
        scope_source = build_runtime_model_provider_scope(
            _container(model, _other(client)), _catalog()
        )
        if observed:
            await model.embed("ordinary invocation")
        store = InMemoryStateStore()
        monitor = SelfHealthRuntimeMonitor(
            registry=_registry(store),
            store=store,
            model_provider_scope=scope_source,
        )
        snapshot = await monitor.collect_and_persist(now=NOW)
        global_adapter = next(
            row
            for row in snapshot.self_health.signals
            if row.signal is SelfHealthSignalName.ADAPTER_HEALTHCHECK
        )
        assert global_adapter.status is SelfHealthSignalStatus.UNAVAILABLE
        assert global_adapter.value is None
        result = await _operator(store, monkeypatch)
        assert OperationalStateSnapshotV1.model_validate(result["snapshot"]) == snapshot
        scope = ModelProviderScopeSnapshotV1.model_validate(result["model_provider_scope"])
        assert scope.scope_kind == "process_configured_model_roles"
        assert [row.role for row in scope.configured_bindings] == [
            "t1.embedding",
            "t2.reasoner.primary",
        ]
        assert scope.coverage_complete is False
        assert scope.health is ModelProviderHealth.UNKNOWN
        assert scope.observations[0].health is (
            ModelProviderHealth.HEALTHY if observed else ModelProviderHealth.UNKNOWN
        )
        assert scope.observations[1].health is ModelProviderHealth.UNKNOWN
        assert len(calls) == int(observed)
        assert await store.verify_chain()


async def test_reconfigured_binding_cannot_consume_old_positive_observation(monkeypatch) -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json={"data": [{"embedding": [0.1, 0.2]}]})
        )
    ) as client:
        old = _embedding(client)
        await old.embed("old binding")
        current = _embedding(client, deployment="replacement")
        old_source = old.model_provider_observations(maximum_age_seconds=120)
        current_source = current.model_provider_observations(maximum_age_seconds=120)
        scope_source = ConfiguredModelProviderScope(
            configured_bindings=(
                ConfiguredModelBindingV1(
                    role="t1.embedding", binding_digest=current_source.binding_digest
                ),
                ConfiguredModelBindingV1(role="t2.reasoner.primary"),
            ),
            registration_digest=canonical_digest({"new-config": True}),
            sources={"t1.embedding": old_source},
            maximum_age_seconds=120,
        )
        store = InMemoryStateStore()
        snapshot = await SelfHealthRuntimeMonitor(
            registry=_registry(store),
            store=store,
            model_provider_scope=scope_source,
        ).collect_and_persist(now=NOW)
        result = await _operator(store, monkeypatch)
        scope = ModelProviderScopeSnapshotV1.model_validate(result["model_provider_scope"])
        assert scope.coverage_complete is False
        assert scope.health is ModelProviderHealth.UNKNOWN
        assert scope.observations[0].reason == "source_binding_mismatch"
        assert scope.observations[0].value is None
        assert (
            next(
                row
                for row in snapshot.self_health.signals
                if row.signal is SelfHealthSignalName.ADAPTER_HEALTHCHECK
            ).status
            is SelfHealthSignalStatus.UNAVAILABLE
        )
        fresh_source = build_runtime_model_provider_scope(
            _container(current, _other(client), revision="b"), _catalog()
        )
        fresh = await fresh_source.observe(now=NOW, parent_snapshot_digest=snapshot.snapshot_digest)
        assert fresh.registration_digest != scope.registration_digest
        assert fresh.observations[0].health is ModelProviderHealth.UNKNOWN


@pytest.mark.parametrize(
    "corruption",
    [
        "drop-role",
        "drop-obligation",
        "claim-complete",
        "scope",
        "parent",
        "binding",
        "global-health",
    ],
)
async def test_existing_operator_scope_consumer_rejects_false_coverage(monkeypatch, corruption):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json={"data": [{"embedding": [0.1, 0.2]}]})
        )
    ) as client:
        model = _embedding(client)
        await model.embed("ordinary invocation")
        store = InMemoryStateStore()
        await SelfHealthRuntimeMonitor(
            registry=_registry(store),
            store=store,
            model_provider_scope=build_runtime_model_provider_scope(
                _container(model, _other(client)), _catalog()
            ),
        ).collect_and_persist(now=NOW)
        value = dict(await store.read_state("runtime:operational-state"))
        scope = dict(value["model_provider_scope"])
        if corruption == "drop-role":
            scope["observations"] = scope["observations"][:1]
        elif corruption == "drop-obligation":
            scope["observations"] = scope["observations"][:1]
            scope["configured_bindings"] = scope["configured_bindings"][:1]
            scope["coverage_complete"] = True
            scope["health"] = "healthy"
        elif corruption == "claim-complete":
            scope["coverage_complete"] = True
            scope["health"] = "healthy"
        elif corruption == "scope":
            scope["scope_kind"] = "all_configured_adapters"
        elif corruption == "parent":
            scope["parent_snapshot_digest"] = "sha256:" + "b" * 64
        elif corruption == "global-health":
            old = OperationalStateSnapshotV1.model_validate(value["snapshot"])
            signals = tuple(
                row.model_copy(
                    update={
                        "status": SelfHealthSignalStatus.HEALTHY,
                        "value": Decimal(1),
                        "observed_at": NOW,
                        "fresh": True,
                        "alert": False,
                        "reason": "unproved_aggregate",
                    }
                )
                if row.signal is SelfHealthSignalName.ADAPTER_HEALTHCHECK
                else row
                for row in old.self_health.signals
            )
            self_health = SelfHealthSnapshotV1(
                catalog_version=old.self_health.catalog_version,
                generated_at=NOW,
                signals=signals,
                snapshot_digest=self_health_snapshot_digest(
                    catalog_version=old.self_health.catalog_version,
                    generated_at=NOW,
                    signals=signals,
                ),
            )
            promoted = OperationalStateSnapshotV1(
                generated_at=NOW,
                self_health=self_health,
                fields=old.fields,
                snapshot_digest=operational_state_snapshot_digest(
                    generated_at=NOW,
                    self_health=self_health,
                    fields=old.fields,
                ),
            )
            value["snapshot"] = promoted.model_dump(mode="json")
            scope["parent_snapshot_digest"] = promoted.snapshot_digest
        else:
            scope["configured_bindings"][0]["binding_digest"] = "sha256:" + "b" * 64
        scope["snapshot_digest"] = canonical_digest(
            {key: item for key, item in scope.items() if key != "snapshot_digest"}
        )
        value["model_provider_scope"] = scope
        await store.write_state("runtime:operational-state", value)
        expected_error = (
            "adapter coverage" if corruption == "global-health" else "scope is malformed"
        )
        with pytest.raises(ProjectionUnavailableError, match=expected_error):
            await _operator(store, monkeypatch)


async def test_missing_registration_never_becomes_healthy_empty_coverage() -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json={"data": [{"embedding": [0.1, 0.2]}]})
        )
    ) as client:
        model = _embedding(client)
        await model.embed("actual but unregistered outcome")
        source = build_runtime_model_provider_scope(
            _container(model, _other(client), registered=False), _catalog()
        )
        scope = await source.observe(now=NOW, parent_snapshot_digest="sha256:" + "a" * 64)
        assert source.registration.source_artifact_digest is None
        assert scope.configured_bindings == ()
        assert scope.registration_digest is None
        assert scope.coverage_complete is False
        assert scope.health is ModelProviderHealth.UNKNOWN


@pytest.mark.parametrize("seconds", [-1, 121])
async def test_reader_never_returns_stale_or_future_sub_adapter_health(monkeypatch, seconds):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json={"data": [{"embedding": [0.1, 0.2]}]})
        )
    ) as client:
        model = _embedding(client)
        await model.embed("ordinary invocation")
        store = InMemoryStateStore()
        await SelfHealthRuntimeMonitor(
            registry=_registry(store),
            store=store,
            model_provider_scope=build_runtime_model_provider_scope(
                _container(model, _other(client)), _catalog()
            ),
        ).collect_and_persist(now=NOW)
        monkeypatch.setattr(
            operator_module, "_model_scope_read_now", lambda: NOW + timedelta(seconds=seconds)
        )
        with pytest.raises(ProjectionUnavailableError, match="scope is malformed"):
            await _operator(store, monkeypatch)
