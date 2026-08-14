"""Composition-root binding tests for the T2 self-consistency cascade."""

from __future__ import annotations

from dataclasses import replace

from fdai.composition import Container, default_container
from fdai.composition._helpers import LlmBindings
from fdai.core.quality_gate.testing import MatchTypeCrossCheckModel
from fdai.core.tiers.t1_lightweight.testing import DeterministicEmbeddingModel
from fdai.runtime.control_loop import _build_self_consistency_cascade
from fdai.shared.config import AppConfig


def _bindings() -> LlmBindings:
    return LlmBindings(
        embedding_model=DeterministicEmbeddingModel(),
        cross_check_models=(MatchTypeCrossCheckModel(model_id="primary"),),
    )


def _container(container: Container, **llm_overrides: object) -> Container:
    config: AppConfig = container.config
    return replace(
        container,
        config=config.model_copy(update={"llm": config.llm.model_copy(update=llm_overrides)}),
    )


def test_cascade_stays_unbound_by_default(container: Container) -> None:
    assert container.config.llm.self_consistency_samples == 0
    assert _build_self_consistency_cascade(container, _bindings()) is None


def test_cascade_binds_the_primary_cross_check_model(container: Container) -> None:
    configured = _container(
        container,
        self_consistency_samples=3,
        self_consistency_sample_threshold=0.6,
        self_consistency_stability_threshold=0.8,
    )

    cascade = _build_self_consistency_cascade(configured, _bindings())

    assert cascade is not None
    assert cascade.sample_threshold == 0.6
    assert cascade.stability_threshold == 0.8


def test_cascade_stays_unbound_without_positive_samples(container: Container) -> None:
    configured = _container(container, self_consistency_samples=0)

    assert _build_self_consistency_cascade(configured, _bindings()) is None


def test_default_container_config_keeps_sampling_off() -> None:
    config = AppConfig.model_validate(
        {
            "schema_version": "1.0.0",
            "azure": {
                "tenant_id": "00000000-0000-0000-0000-000000000000",
                "subscription_id": "00000000-0000-0000-0000-000000000000",
                "resource_group": "rg-fdai",
                "region": "krc",
            },
            "kafka": {
                "bootstrap_servers": "evhns-fdai.example.local:9093",
                "topic_events": "aw.change.events",
            },
            "postgres": {"host": "psql-fdai.example.local", "database": "fdai"},
            "rule_catalog": {"ref": "main"},
            "runtime": {"env": "dev"},
        }
    )

    assert default_container(config).config.llm.self_consistency_samples == 0


def test_self_consistency_keys_load_through_the_config_boundary() -> None:
    from fdai.shared.config.provider import EnvVarConfigProvider

    config = EnvVarConfigProvider(
        {
            "AZURE_TENANT_ID": "00000000-0000-0000-0000-000000000000",
            "AZURE_SUBSCRIPTION_ID": "00000000-0000-0000-0000-000000000000",
            "AZURE_REGION": "krc",
            "KAFKA_BOOTSTRAP_SERVERS": "evhns-fdai.example.local:9093",
            "KAFKA_TOPIC_EVENTS": "aw.change.events",
            "POSTGRES_HOST": "psql-fdai.example.local",
            "POSTGRES_DATABASE": "fdai",
            "RUNTIME_ENV": "dev",
            "SELF_CONSISTENCY_SAMPLES": "3",
            "SELF_CONSISTENCY_SAMPLE_THRESHOLD": "0.55",
            "SELF_CONSISTENCY_STABILITY_THRESHOLD": "0.85",
        }
    ).get()

    assert config.llm.self_consistency_samples == 3
    assert config.llm.self_consistency_sample_threshold == 0.55
    assert config.llm.self_consistency_stability_threshold == 0.85
