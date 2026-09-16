from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fdai.composition import bind_configuration_drift, default_container
from fdai.core.capability_catalog import SideEffectClass
from fdai.core.detection.configuration_drift import (
    ConfigurationObservation,
    ConfigurationResource,
    EvidenceCompleteness,
    FrozenConfigurationBaseline,
)
from fdai.delivery.persistence.state_store_configuration_baseline import (
    CONFIGURATION_BASELINE_PREFIX,
    StateStoreConfigurationBaselineSink,
)
from fdai.shared.config.models import AppConfig
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai_operator_service.families.operations import ProjectionQuery
from fdai_operator_service.runtime_projection_reader import (
    RuntimeProjectionReader,
    RuntimeProjectionReaderConfig,
)
from fdai_service_contracts import OperatorRole

_NOW = datetime(2026, 8, 4, tzinfo=UTC)
_BASELINE = FrozenConfigurationBaseline(
    version="v1",
    created_at=_NOW,
    scope="example-scope",
    source="reviewed snapshot",
    document_sha256="a" * 64,
    resources=(
        ConfigurationResource(
            local_name="service-a",
            resource_type="example/service",
            region="example-region",
        ),
    ),
)


def _config() -> AppConfig:
    return AppConfig.model_validate(
        {
            "schema_version": "1.0.0",
            "azure": {
                "tenant_id": "00000000-0000-0000-0000-000000000000",
                "subscription_id": "00000000-0000-0000-0000-000000000000",
                "region": "example-region",
            },
            "kafka": {
                "bootstrap_servers": "example:9093",
                "topic_events": "example.events",
            },
            "postgres": {"host": "example.local", "database": "fdai"},
            "runtime": {"env": "dev"},
            "llm": {"mode": "local-fake"},
        }
    )


class BaselineSource:
    async def load(self) -> FrozenConfigurationBaseline:
        return _BASELINE


class ObservationSource:
    async def observe(self, *, scope: str) -> ConfigurationObservation:
        return ConfigurationObservation(
            scope=scope,
            observed_at=_NOW,
            source="authoritative inventory",
            completeness=EvidenceCompleteness.COMPLETE,
            resources=(),
        )


def test_public_drift_binder_installs_only_a_read_capability() -> None:
    original = default_container(_config())

    bound = bind_configuration_drift(
        original,
        baseline_source=BaselineSource(),
        observation_source=ObservationSource(),
        expected_version="v1",
        expected_sha256=_BASELINE.sha256,
        expected_scope="example-scope",
    )

    resolved = bound.capability_runtime.resolve("configuration.drift.read")
    assert original.capability_runtime.bound_capability_ids() == ()
    assert bound.capability_runtime.bound_capability_ids() == ("configuration.drift.read",)
    assert resolved.capability.side_effect_class is SideEffectClass.READ
    assert resolved.provider is not None


async def test_completed_core_check_reaches_operator_baseline_panel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = InMemoryStateStore()
    bound = bind_configuration_drift(
        default_container(_config()),
        baseline_source=BaselineSource(),
        observation_source=ObservationSource(),
        expected_version=_BASELINE.version,
        expected_sha256=_BASELINE.sha256,
        expected_scope=_BASELINE.scope,
        report_sink=StateStoreConfigurationBaselineSink(store),
    )
    provider = bound.capability_runtime.resolve("configuration.drift.read").provider
    assert provider is not None
    artifact = next(
        item
        for item in bound.capability_runtime.reasoning_tools
        if item.id == "configuration.drift.check"
    )
    result = await provider.call(artifact=artifact, arguments={})
    assert isinstance(result, dict)

    class NoFallback:
        async def read(self, query: ProjectionQuery) -> dict[str, object]:
            pytest.fail("configuration evidence must not fall back to a catalog")

    async def fetch(
        self: RuntimeProjectionReader,
        statement: str,
        parameters: tuple[object, ...] = (),
    ) -> list[dict[str, object]]:
        assert CONFIGURATION_BASELINE_PREFIX in statement
        assert "value ->> 'observed_at' DESC NULLS LAST" in statement
        return [
            {"value": row, "updated_at": _NOW}
            for row in await store.read_states(CONFIGURATION_BASELINE_PREFIX, limit=1)
        ]

    monkeypatch.setattr(RuntimeProjectionReader, "_fetch_all", fetch)
    reader = RuntimeProjectionReader(
        RuntimeProjectionReaderConfig("postgresql://example.invalid/fdai"), NoFallback()
    )
    panel = await reader.read(
        ProjectionQuery(
            operation="configuration-baselines",
            principal_id="operator-a",
            path={},
            params={},
            limit=100,
            cursor=None,
            roles=frozenset({OperatorRole.READER}),
        )
    )
    assert panel["baseline"]["version"] == _BASELINE.version
    assert panel["drift"]["verdict"] == result["verdict"] == "failed"
    assert panel["performance"] == result["performance"]
    assert panel["knowledge"]["status"] == "not-configured"
    assert panel["review"]["configured"] is False
