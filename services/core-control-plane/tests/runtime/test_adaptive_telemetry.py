from __future__ import annotations

from datetime import UTC, datetime

import pytest
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

_NOW = datetime(2026, 9, 16, 12, tzinfo=UTC)


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


def _build(provider, store, environment):
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

    result = await investigator.investigate(
        incident_id="incident:one",
        resource_ref="resource:one",
        event_type="http.429.detected",
        resource_type="application",
        evidence_cutoff=_NOW,
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
        evidence_cutoff=_NOW,
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

    assert ADAPTIVE_TELEMETRY_CONFIG_VERSION == "1.0.0"
    assert baseline.policy_digest == AdaptiveTelemetryRuntimeConfig(enabled=True).policy_digest
    assert (
        baseline.policy_digest
        != AdaptiveTelemetryRuntimeConfig(
            enabled=True,
            max_cost_units=121,
        ).policy_digest
    )
