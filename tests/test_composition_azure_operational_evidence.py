from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from fdai.composition import bind_azure_operational_evidence, default_container
from fdai.core.assurance_twin import EffectModelStatus, SimulationBranch
from fdai.core.rca import TemporalCausalityConfig
from fdai.delivery.azure.operational_evidence import (
    AzureDynamicPolicy,
    AzureOperationalSnapshot,
    AzureReuseSafetyChecks,
    AzureTemporalPolicy,
)
from fdai.shared.config import AppConfig
from fdai.shared.providers.metric import StaticMetricProvider


def _config() -> AppConfig:
    return AppConfig.model_validate(
        {
            "schema_version": "1.0.0",
            "azure": {
                "tenant_id": "00000000-0000-0000-0000-000000000000",
                "subscription_id": "00000000-0000-0000-0000-000000000000",
                "region": "krc",
            },
            "kafka": {
                "bootstrap_servers": "example:9093",
                "topic_events": "aw.change.events",
            },
            "postgres": {"host": "example.local", "database": "fdai"},
            "runtime": {"env": "dev"},
            "llm": {"mode": "local-fake"},
        }
    )


class _Snapshots:
    async def get(self, resource_ref: str) -> AzureOperationalSnapshot | None:
        return AzureOperationalSnapshot(
            resource_ref=resource_ref,
            resource_type="kubernetes.cluster",
            topology_roles=("hosts",),
            ownership_shape=("platform-team",),
            graph_digest="a" * 64,
            owner_digest="b" * 64,
            observed_at=datetime(2026, 8, 1, tzinfo=UTC),
            evidence_refs=("c" * 64,),
        )


class _Safety:
    async def evaluate(self, **kwargs: Any) -> AzureReuseSafetyChecks:
        return AzureReuseSafetyChecks(
            True,
            True,
            True,
            True,
            True,
            True,
            True,
            ("d" * 64,),
        )


class _Estimator:
    async def estimate(self, **kwargs: Any) -> tuple[SimulationBranch, ...]:
        return (SimulationBranch("noop", "noop", 1.0, 0.1),)


class _Models:
    async def get(
        self,
        *,
        status: EffectModelStatus,
        action_type_id: str,
        metric: str,
    ):  # type: ignore[no-untyped-def]
        return None


def test_azure_operational_evidence_binder_is_immutable_and_complete() -> None:
    original = replace(default_container(_config()), metric_provider=StaticMetricProvider(()))

    bound = bind_azure_operational_evidence(
        original,
        snapshots=_Snapshots(),
        safety=_Safety(),
        temporal_policies={
            "aks.node-pressure": AzureTemporalPolicy(
                cause_metric="node_cpu_percent",
                effect_metric="latency_ms",
                mechanism="node-pressure",
                required_topology_role="hosts",
                lookback=timedelta(minutes=20),
            )
        },
        temporal_config=TemporalCausalityConfig(lag_seconds=(0, 60), min_samples=4),
        branch_estimator=_Estimator(),
        dynamic_policies={"ops.scale-out": AzureDynamicPolicy(metric="latency_ms")},
        effect_models=_Models(),
    )

    assert original.current_reuse_verifier is None
    assert bound.current_reuse_verifier is not None
    assert bound.temporal_causal_evidence_provider is not None
    assert bound.temporal_causality_config is not None
    assert bound.dynamic_simulation_request_provider is not None
    assert bound.effect_model_reader is not None


def test_container_rejects_partial_operational_evidence_bindings() -> None:
    container = default_container(_config())

    with pytest.raises(ValueError, match="temporal causal evidence provider and config"):
        replace(
            container,
            temporal_causal_evidence_provider=object(),  # type: ignore[arg-type]
        )
