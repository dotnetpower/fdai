from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from fdai.composition import bind_configuration_drift, default_container
from fdai.core.detection.configuration_drift import (
    ConfigurationObservation,
    ConfigurationResource,
    EvidenceCompleteness,
    FrozenConfigurationBaseline,
)
from fdai.shared.config.models import AppConfig

_NOW = datetime(2026, 8, 4, tzinfo=UTC)


@dataclass
class _BaselineSource:
    baseline: FrozenConfigurationBaseline

    async def load(self) -> FrozenConfigurationBaseline:
        return self.baseline


@dataclass
class _ObservationSource:
    observation: ConfigurationObservation

    async def observe(self, *, scope: str) -> ConfigurationObservation:
        assert scope == self.observation.scope
        return self.observation


def _container():  # type: ignore[no-untyped-def]
    return default_container(
        AppConfig.model_validate(
            {
                "schema_version": "1.0.0",
                "azure": {
                    "tenant_id": "00000000-0000-0000-0000-000000000000",
                    "subscription_id": "00000000-0000-0000-0000-000000000000",
                    "region": "koreacentral",
                },
                "kafka": {
                    "bootstrap_servers": "events.example.com:9093",
                    "topic_events": "fdai.events",
                },
                "postgres": {"host": "postgres.example.com", "database": "fdai"},
                "runtime": {"env": "dev"},
                "llm": {"mode": "local-fake"},
            }
        )
    )


def _resource() -> ConfigurationResource:
    return ConfigurationResource(
        local_name="service-a",
        resource_type="example/service",
        region="korea central",
        attributes={"sku": "Standard"},
    )


async def test_binding_installs_read_only_tool_without_mutating_input_container() -> None:
    baseline = FrozenConfigurationBaseline(
        version="s13-v1",
        created_at=_NOW,
        scope="example-scope",
        source="reviewed inventory snapshot",
        document_sha256="a" * 64,
        resources=(_resource(),),
    )
    observation = ConfigurationObservation(
        scope=baseline.scope,
        observed_at=_NOW,
        source="authoritative inventory",
        completeness=EvidenceCompleteness.COMPLETE,
        resources=(_resource(),),
    )
    original = _container()

    bound = bind_configuration_drift(
        original,
        baseline_source=_BaselineSource(baseline),
        observation_source=_ObservationSource(observation),
        expected_version=baseline.version,
        expected_sha256=baseline.sha256,
        expected_scope=baseline.scope,
    )

    assert "configuration.drift.read" not in original.capability_runtime.bound_capability_ids()
    resolved = bound.capability_runtime.resolve("configuration.drift.read")
    assert resolved.capability.side_effect_class.value == "read"
    assert resolved.provider is not None
    artifact = next(
        item
        for item in bound.capability_runtime.reasoning_tools
        if item.id == "configuration.drift.check"
    )
    result = await resolved.provider.call(artifact=artifact, arguments={})
    assert isinstance(result, dict)
    assert result["verdict"] == "passed"
    assert result["mutation_count"] == 0
