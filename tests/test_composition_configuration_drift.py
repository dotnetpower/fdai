from __future__ import annotations

from datetime import UTC, datetime

from fdai.composition import bind_configuration_drift, default_container
from fdai.core.capability_catalog import SideEffectClass
from fdai.core.detection.configuration_drift import (
    ConfigurationObservation,
    ConfigurationResource,
    EvidenceCompleteness,
    FrozenConfigurationBaseline,
)
from fdai.shared.config.models import AppConfig

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
