from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.ontology_platform.query_manifest import QueryManifest
from fdai.core.rca import (
    DEFAULT_TELEMETRY_RECIPE_CATALOG,
    TelemetryEvidenceDisposition,
    TelemetryMechanism,
    build_telemetry_evidence_receipt,
)
from fdai.core.read_investigation.adaptive import AdaptiveInvestigationCoordinator
from fdai.core.read_investigation.adaptive_contract import (
    AdaptiveInvestigationBudget,
    AdaptiveInvestigationDisposition,
    build_adaptive_observation_execution,
)
from fdai.core.read_investigation.telemetry_adaptive import (
    adaptive_telemetry_evidence_result,
    build_initial_telemetry_frame,
    build_telemetry_adaptive_bindings,
    telemetry_mechanisms_for_event,
)
from fdai.shared.contracts.models import CeilingRole
from fdai_service_contracts.ontology_query import StructuralCoverageReceipt, content_digest

_NOW = datetime(2026, 9, 16, 12, tzinfo=UTC)
_RELEASE = f"sha256:{'a' * 64}"
_SCOPE = f"sha256:{'b' * 64}"


def _manifest() -> QueryManifest:
    manifest_digest = content_digest(
        {
            "release_digest": _RELEASE,
            "principal_role": "reader",
            "purposes": ("operations-review",),
            "descriptors": (),
            "unavailable": (),
            "mutation_authority": False,
        }
    )
    coverage = StructuralCoverageReceipt(
        ontology_release_digest=_RELEASE,
        principal_scope_digest=_SCOPE,
        readable_declaration_count=0,
        descriptor_count=0,
        unavailable_declaration_ids=(),
        manifest_digest=manifest_digest,
        complete=True,
        receipt_digest=content_digest(
            {
                "schema_version": "1.0.0",
                "ontology_release_digest": _RELEASE,
                "principal_scope_digest": _SCOPE,
                "readable_declaration_count": 0,
                "descriptor_count": 0,
                "unavailable_declaration_ids": (),
                "manifest_digest": manifest_digest,
                "complete": True,
            }
        ),
    )
    return QueryManifest(
        release_digest=_RELEASE,
        principal_role=CeilingRole.READER,
        purposes=("operations-review",),
        descriptors=(),
        unavailable=(),
        manifest_digest=manifest_digest,
        coverage_receipt=coverage,
    )


class _SequencedProvider:
    def __init__(self, dispositions: tuple[TelemetryEvidenceDisposition, ...]) -> None:
        self.dispositions = list(dispositions)
        self.needs = []

    async def gather(self, need):
        self.needs.append(need)
        disposition = self.dispositions.pop(0)
        recipe = DEFAULT_TELEMETRY_RECIPE_CATALOG.get(need.recipe_id, need.recipe_version)
        has_data = disposition is TelemetryEvidenceDisposition.COMPLETE
        complete = disposition in {
            TelemetryEvidenceDisposition.COMPLETE,
            TelemetryEvidenceDisposition.COMPLETE_NO_DATA,
        }
        return build_telemetry_evidence_receipt(
            need=need,
            observed_until=_NOW if complete else None,
            disposition=disposition,
            route_count=1,
            queried_route_count=1,
            row_count=1 if has_data else 0,
            latency_ms=1,
            estimated_cost_units=recipe.estimated_cost_units,
            actual_cost_units=recipe.estimated_cost_units,
            fact_tokens=(f"mechanism:{recipe.mechanism.value}",) if has_data else (),
            complete=complete,
            truncated=False,
        )


def test_event_router_selects_bounded_relevant_recipes_and_unknown_falls_back() -> None:
    throttling = telemetry_mechanisms_for_event("http.429.detected")
    unknown = telemetry_mechanisms_for_event("novel.signal")

    assert TelemetryMechanism.THROTTLING in throttling
    assert TelemetryMechanism.FAILED_REQUESTS in throttling
    assert len(throttling) == 3
    assert set(unknown) == set(TelemetryMechanism)


@pytest.mark.asyncio
async def test_existing_adaptive_loop_refutes_then_converges_on_positive_recipe_evidence() -> None:
    provider = _SequencedProvider(
        (
            TelemetryEvidenceDisposition.COMPLETE_NO_DATA,
            TelemetryEvidenceDisposition.COMPLETE,
        )
    )
    manifest = _manifest()
    bindings = build_telemetry_adaptive_bindings(
        provider=provider,
        manifest=manifest,
        principal_scope_digest=_SCOPE,
        resource_ref="resource:one",
    )
    frame = build_initial_telemetry_frame(
        incident_id="incident:one",
        graph_revision="graph:one",
        evidence_cutoff=_NOW,
        mechanisms=(
            TelemetryMechanism.FAILED_REQUESTS,
            TelemetryMechanism.ERROR_TIMELINE,
            TelemetryMechanism.THROTTLING,
        ),
    )
    coordinator = AdaptiveInvestigationCoordinator(
        round_source=bindings.round_source,
        reviser=bindings.reviser,
        gateway=bindings.gateway,
        active_strategy_digest=DEFAULT_TELEMETRY_RECIPE_CATALOG.catalog_digest,
        clock=lambda: _NOW,
    )

    result = await coordinator.investigate(
        session_id="adaptive-telemetry:one",
        initial_frame=frame,
        budget=AdaptiveInvestigationBudget(
            max_rounds=3,
            max_queries=3,
            max_cost_units=120,
            deadline_at=_NOW + timedelta(minutes=1),
            policy_digest=content_digest({"policy": "telemetry-test"}),
        ),
    )

    assert result.disposition is AdaptiveInvestigationDisposition.CONVERGED
    assert result.used_queries == 2
    assert result.used_cost_units == 20
    assert len(provider.needs) == 2
    assert all(not hasattr(need, "kql") for need in provider.needs)
    assert result.iterations[0].revision is not None
    assert result.iterations[0].revision.disposition is AdaptiveInvestigationDisposition.CONTINUE
    assert result.iterations[1].revision is not None
    assert result.iterations[1].revision.owner_agent == "Forseti"
    assert result.iterations[1].revision.disposition is AdaptiveInvestigationDisposition.CONVERGED


@pytest.mark.asyncio
async def test_incomplete_source_holds_without_changing_active_hypotheses() -> None:
    provider = _SequencedProvider((TelemetryEvidenceDisposition.UNAVAILABLE,))
    manifest = _manifest()
    bindings = build_telemetry_adaptive_bindings(
        provider=provider,
        manifest=manifest,
        principal_scope_digest=_SCOPE,
        resource_ref="resource:one",
    )
    frame = build_initial_telemetry_frame(
        incident_id="incident:one",
        graph_revision="graph:one",
        evidence_cutoff=_NOW,
        mechanisms=(TelemetryMechanism.FAILED_REQUESTS, TelemetryMechanism.THROTTLING),
    )
    coordinator = AdaptiveInvestigationCoordinator(
        round_source=bindings.round_source,
        reviser=bindings.reviser,
        gateway=bindings.gateway,
        active_strategy_digest=DEFAULT_TELEMETRY_RECIPE_CATALOG.catalog_digest,
        clock=lambda: _NOW,
    )

    result = await coordinator.investigate(
        session_id="adaptive-telemetry:held",
        initial_frame=frame,
        budget=AdaptiveInvestigationBudget(
            max_rounds=1,
            max_queries=1,
            max_cost_units=40,
            deadline_at=_NOW + timedelta(minutes=1),
            policy_digest=content_digest({"policy": "telemetry-test"}),
        ),
    )

    assert result.disposition is AdaptiveInvestigationDisposition.HELD
    assert result.iterations[0].revision is not None
    assert result.iterations[0].revision.active_hypothesis_ids == frame.active_hypothesis_ids
    assert result.iterations[0].revision.complete is False


@pytest.mark.asyncio
async def test_complete_no_data_refutes_but_is_not_positive_t2_grounding() -> None:
    provider = _SequencedProvider((TelemetryEvidenceDisposition.COMPLETE_NO_DATA,))
    manifest = _manifest()
    bindings = build_telemetry_adaptive_bindings(
        provider=provider,
        manifest=manifest,
        principal_scope_digest=_SCOPE,
        resource_ref="resource:one",
    )
    frame = build_initial_telemetry_frame(
        incident_id="incident:one",
        graph_revision="graph:one",
        evidence_cutoff=_NOW,
        mechanisms=(
            TelemetryMechanism.FAILED_REQUESTS,
            TelemetryMechanism.ERROR_TIMELINE,
            TelemetryMechanism.THROTTLING,
        ),
    )
    result = await AdaptiveInvestigationCoordinator(
        round_source=bindings.round_source,
        reviser=bindings.reviser,
        gateway=bindings.gateway,
        active_strategy_digest=DEFAULT_TELEMETRY_RECIPE_CATALOG.catalog_digest,
        clock=lambda: _NOW,
    ).investigate(
        session_id="adaptive-telemetry:no-data",
        initial_frame=frame,
        budget=AdaptiveInvestigationBudget(
            max_rounds=1,
            max_queries=1,
            max_cost_units=40,
            deadline_at=_NOW + timedelta(minutes=1),
            policy_digest=content_digest({"policy": "telemetry-test"}),
        ),
    )

    assert result.iterations[0].revision is not None
    assert result.iterations[0].revision.disposition is AdaptiveInvestigationDisposition.CONTINUE
    assert adaptive_telemetry_evidence_result(result).citations == ()


@pytest.mark.asyncio
async def test_iteration_rejects_substituted_receipt_metadata_or_future_watermark() -> None:
    provider = _SequencedProvider((TelemetryEvidenceDisposition.COMPLETE,))
    manifest = _manifest()
    bindings = build_telemetry_adaptive_bindings(
        provider=provider,
        manifest=manifest,
        principal_scope_digest=_SCOPE,
        resource_ref="resource:one",
    )
    frame = build_initial_telemetry_frame(
        incident_id="incident:one",
        graph_revision="graph:one",
        evidence_cutoff=_NOW,
        mechanisms=(TelemetryMechanism.FAILED_REQUESTS, TelemetryMechanism.THROTTLING),
    )
    result = await AdaptiveInvestigationCoordinator(
        round_source=bindings.round_source,
        reviser=bindings.reviser,
        gateway=bindings.gateway,
        active_strategy_digest=DEFAULT_TELEMETRY_RECIPE_CATALOG.catalog_digest,
        clock=lambda: _NOW,
    ).investigate(
        session_id="adaptive-telemetry:metadata",
        initial_frame=frame,
        budget=AdaptiveInvestigationBudget(
            max_rounds=1,
            max_queries=1,
            max_cost_units=40,
            deadline_at=_NOW + timedelta(minutes=1),
            policy_digest=content_digest({"policy": "telemetry-test"}),
        ),
    )
    iteration = result.iterations[0]
    assert iteration.execution is not None and iteration.execution.source_metadata is not None

    def changed_execution(*, evidence_refs, source_metadata):
        execution = iteration.execution
        return build_adaptive_observation_execution(
            round_index=execution.round_index,
            frame_digest=execution.frame_digest,
            selection_digest=execution.selection_digest,
            candidate_digest=execution.candidate_digest,
            binding_digest=execution.binding_digest,
            verification_receipt_digest=execution.verification_receipt_digest,
            plan_digest=execution.plan_digest,
            result_digest=execution.result_digest,
            query_status=execution.query_status,
            evidence_refs=evidence_refs,
            reserved_cost_units=execution.reserved_cost_units,
            actual_cost_units=execution.actual_cost_units,
            source_metadata=source_metadata,
        )

    with pytest.raises(ValueError, match="receipt reference"):
        replace(
            iteration,
            execution=changed_execution(
                evidence_refs=(),
                source_metadata=iteration.execution.source_metadata,
            ),
        )
    with pytest.raises(ValueError, match="frame cutoff"):
        replace(
            iteration,
            execution=changed_execution(
                evidence_refs=iteration.execution.evidence_refs,
                source_metadata=replace(
                    iteration.execution.source_metadata,
                    observed_until=_NOW + timedelta(seconds=1),
                ),
            ),
        )
