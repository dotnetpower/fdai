"""Exhaustive complete/no-data convergence through the actual verified read gateway."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from itertools import product

import httpx
import pytest
from fdai.core.rca import (
    DEFAULT_TELEMETRY_RECIPE_CATALOG,
    TelemetryEvidenceDisposition,
    build_telemetry_evidence_receipt,
)
from fdai.core.rca.observation_history import ObservationOutcome
from fdai.core.read_investigation.adaptive import AdaptiveInvestigationCoordinator
from fdai.core.read_investigation.adaptive_codec import (
    adaptive_result_from_mapping,
    adaptive_result_to_mapping,
)
from fdai.core.read_investigation.adaptive_contract import (
    AdaptiveInvestigationBudget,
    AdaptiveInvestigationDisposition,
    build_adaptive_investigation_iteration,
    build_hypothesis_revision_set,
)
from fdai.core.read_investigation.telemetry_adaptive import (
    adaptive_telemetry_evidence_result,
    build_initial_telemetry_frame,
    build_telemetry_adaptive_bindings,
    telemetry_mechanisms_for_event,
)
from fdai_service_contracts.ontology_query import content_digest
from tests.core.read_investigation.test_telemetry_adaptive import (
    _NOW,
    _SCOPE,
    _manifest,
    _SequencedProvider,
)

POSITIVE = TelemetryEvidenceDisposition.COMPLETE
NEGATIVE = TelemetryEvidenceDisposition.COMPLETE_NO_DATA


async def run(sequence, *, rounds=3, queries=3, cost=120, provider=None):
    provider = provider if provider is not None else _SequencedProvider(sequence)
    bindings = build_telemetry_adaptive_bindings(
        provider=provider,
        manifest=_manifest(),
        principal_scope_digest=_SCOPE,
        resource_ref="resource:one",
    )
    frame = build_initial_telemetry_frame(
        incident_id="incident:one",
        graph_revision="graph:one",
        evidence_cutoff=_NOW,
        mechanisms=telemetry_mechanisms_for_event("http.429.detected"),
    )
    coordinator = AdaptiveInvestigationCoordinator(
        round_source=bindings.round_source,
        reviser=bindings.reviser,
        gateway=bindings.gateway,
        active_strategy_digest=DEFAULT_TELEMETRY_RECIPE_CATALOG.catalog_digest,
        clock=lambda: _NOW,
    )
    result = await coordinator.investigate(
        session_id="session:convergence",
        initial_frame=frame,
        budget=AdaptiveInvestigationBudget(
            max_rounds=rounds,
            max_queries=queries,
            max_cost_units=cost,
            deadline_at=_NOW + timedelta(minutes=1),
            policy_digest=content_digest({"fixture": "complete-convergence"}),
        ),
    )
    return result, provider


@pytest.mark.parametrize("sequence", tuple(product((POSITIVE, NEGATIVE), repeat=3)))
async def test_every_default_three_hypothesis_sequence_is_fully_observed(sequence):
    result, provider = await run(sequence)
    positives = sequence.count(POSITIVE)
    expected = (
        AdaptiveInvestigationDisposition.ALL_REFUTED
        if positives == 0
        else AdaptiveInvestigationDisposition.CONVERGED
        if positives == 1
        else AdaptiveInvestigationDisposition.HELD
    )
    assert result.disposition is expected
    assert result.used_queries == len(provider.needs) == 3
    assert len({(need.recipe_id, need.recipe_version) for need in provider.needs}) == 3
    revision = result.iterations[-1].revision
    assert revision is not None and len(revision.observation_history) == 3
    assert (
        sum(item.outcome is ObservationOutcome.SUPPORTED for item in revision.observation_history)
        == positives
    )
    assert len(revision.active_hypothesis_ids) == positives
    assert adaptive_result_from_mapping(adaptive_result_to_mapping(result)) == result
    assert result.execution_authority is False
    citations = adaptive_telemetry_evidence_result(result).citations
    assert len(citations) == positives
    for citation in citations:
        assert "evidence_grade:association" in citation.facts
        assert f"investigation_status:{expected.value}" in citation.facts


async def test_last_unobserved_survivor_is_validated_not_assumed_true():
    result, provider = await run((NEGATIVE, NEGATIVE, POSITIVE))
    last = result.iterations[-1]
    assert last.selection.method_version == "single-hypothesis-validation-v1"
    assert last.selection.total_pair_count == last.selection.separated_pair_count == 0
    assert result.disposition is AdaptiveInvestigationDisposition.CONVERGED
    assert len(provider.needs) == 3


@pytest.mark.parametrize(
    "disposition",
    [
        TelemetryEvidenceDisposition.UNAVAILABLE,
        TelemetryEvidenceDisposition.PARTIAL,
        TelemetryEvidenceDisposition.STALE,
    ],
)
async def test_unusable_evidence_stays_explicitly_unknown(disposition):
    result, _ = await run((POSITIVE, disposition))
    assert result.disposition is AdaptiveInvestigationDisposition.HELD
    revision = result.iterations[-1].revision
    assert revision is not None
    assert len(revision.active_hypothesis_ids) == 3
    assert any(item.outcome is ObservationOutcome.UNKNOWN for item in revision.observation_history)


async def test_insufficient_budget_does_not_claim_complete_investigation():
    result, provider = await run((POSITIVE, NEGATIVE), rounds=2)
    assert result.disposition is AdaptiveInvestigationDisposition.ROUND_EXHAUSTED
    assert result.used_queries == 2
    assert len({need.recipe_id for need in provider.needs}) == 2


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({"queries": 1}, AdaptiveInvestigationDisposition.QUERY_EXHAUSTED),
        ({"cost": 40}, AdaptiveInvestigationDisposition.COST_EXHAUSTED),
    ],
)
async def test_query_and_cost_bounds_preserve_partial_progress(kwargs, expected):
    result, provider = await run((POSITIVE, NEGATIVE, NEGATIVE), **kwargs)
    assert result.disposition is expected
    assert result.used_queries == len(provider.needs) == 1
    revision = result.iterations[0].revision
    assert revision is not None and len(revision.observation_history) == 1
    assert len(revision.active_hypothesis_ids) == 3
    assert adaptive_result_from_mapping(adaptive_result_to_mapping(result)) == result


@pytest.mark.parametrize(
    ("disposition", "gap"),
    [
        (POSITIVE, "zero_routes"),
        (POSITIVE, "missing_cutoff"),
        (NEGATIVE, "zero_routes"),
        (NEGATIVE, "missing_cutoff"),
        (NEGATIVE, "older_cutoff"),
    ],
)
async def test_self_declared_complete_receipt_does_not_prove_missing_coverage(disposition, gap):
    class CoverageFixture(_SequencedProvider):
        async def gather(self, need):
            self.needs.append(need)
            recipe = DEFAULT_TELEMETRY_RECIPE_CATALOG.get(need.recipe_id, need.recipe_version)
            return build_telemetry_evidence_receipt(
                need=need,
                observed_until=(
                    None
                    if gap == "missing_cutoff"
                    else _NOW - timedelta(seconds=1)
                    if gap == "older_cutoff"
                    else _NOW
                ),
                disposition=disposition,
                route_count=0 if gap == "zero_routes" else 1,
                queried_route_count=0 if gap == "zero_routes" else 1,
                row_count=1 if disposition is POSITIVE else 0,
                latency_ms=1,
                estimated_cost_units=10,
                actual_cost_units=10,
                fact_tokens=(f"mechanism:{recipe.mechanism.value}",)
                if disposition is POSITIVE
                else (),
                complete=True,
                truncated=False,
            )

    result, _ = await run((), provider=CoverageFixture(()))
    assert result.disposition is AdaptiveInvestigationDisposition.HELD
    revision = result.iterations[-1].revision
    assert revision is not None and not revision.complete
    assert revision.observation_history[-1].outcome is ObservationOutcome.UNKNOWN
    assert len(revision.active_hypothesis_ids) == 3
    assert adaptive_telemetry_evidence_result(result).citations == ()


async def test_actual_azure_recipe_adapter_keeps_positive_event_before_query_cutoff():
    from fdai.delivery.azure.log_query import (
        AzureLogAnalyticsQueryConfig,
        AzureLogAnalyticsQueryProvider,
    )
    from fdai.delivery.azure.telemetry_recipe_query import AzureMonitorTelemetryRecipeProvider
    from tests.delivery.azure.test_telemetry_recipe_query import _Identity, _Resolver, _table

    def respond(request):
        return httpx.Response(200, json=_table([[2, "2026-09-16T11:59:00Z", "low"]]))

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        provider = AzureMonitorTelemetryRecipeProvider(
            query_provider=AzureLogAnalyticsQueryProvider(
                config=AzureLogAnalyticsQueryConfig(workspace_id="workspace-fallback"),
                identity=_Identity(),
                http_client=client,
            ),
            workspace_resolver=_Resolver(),
        )
        result, _ = await run((), provider=provider)
    assert result.used_queries == 3
    assert result.disposition is AdaptiveInvestigationDisposition.HELD
    final = result.iterations[-1].revision
    assert final is not None
    assert all(item.outcome is ObservationOutcome.SUPPORTED for item in final.observation_history)
    assert all(
        item.execution.source_metadata.observed_until < item.frame.evidence_cutoff
        for item in result.iterations
    )
    assert len(adaptive_telemetry_evidence_result(result).citations) == 3


@pytest.mark.parametrize("change", ["rewrite", "erase", "result", "citation", "competitor"])
async def test_fully_rehashed_revisions_cannot_substitute_verified_progress(change):
    result, _ = await run((POSITIVE, NEGATIVE, NEGATIVE))
    iteration = result.iterations[1]
    revision = iteration.revision
    assert revision is not None and iteration.execution is not None
    history = revision.observation_history
    current_id = next(
        item.hypothesis_id
        for item in history
        if item.hypothesis_id
        not in {prior.hypothesis_id for prior in iteration.frame.observation_history}
    )
    active = revision.active_hypothesis_ids
    if change == "rewrite":
        history = tuple(
            replace(item, outcome=ObservationOutcome.UNKNOWN)
            if item.hypothesis_id != current_id
            else item
            for item in history
        )
    elif change == "erase":
        history = tuple(item for item in history if item.hypothesis_id == current_id)
    elif change == "result":
        history = tuple(
            replace(item, result_digest="sha256:" + "f" * 64)
            if item.hypothesis_id == current_id
            else item
            for item in history
        )
    elif change == "citation":
        history = tuple(
            replace(item, evidence_ref="telemetry-receipt:sha256:" + "f" * 64)
            if item.hypothesis_id == current_id
            else item
            for item in history
        )
    else:
        observed = {item.hypothesis_id for item in history}
        active = tuple(item for item in active if item not in observed)
    with pytest.raises(ValueError):
        changed = build_hypothesis_revision_set(
            prior_active_set_receipt_digest=revision.prior_active_set_receipt_digest,
            prior_frame_digest=revision.prior_frame_digest,
            observation_result_digest=revision.observation_result_digest,
            scorer_version=revision.scorer_version,
            graph_revision=revision.graph_revision,
            evidence_cutoff=revision.evidence_cutoff,
            active_hypothesis_ids=active,
            active_set_receipt_digest=revision.active_set_receipt_digest,
            evidence_refs=revision.evidence_refs,
            complete=revision.complete,
            truncated=revision.truncated,
            disposition=revision.disposition,
            observation_history=history,
        )
        build_adaptive_investigation_iteration(
            round_index=iteration.round_index,
            frame=iteration.frame,
            selection=iteration.selection,
            execution=iteration.execution,
            revision=changed,
        )
