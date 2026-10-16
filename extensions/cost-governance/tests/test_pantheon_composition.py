from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from fdai.agents._framework.cross_vertical_candidates import (
    validate_cross_vertical_candidate,
)
from fdai.core.decision_case import ObjectiveEffect
from fdai.core.operational_context import SourceFreshness

from fdai_cost_governance.guard import (
    FinOpsActionKind,
    FinOpsCandidate,
    FinOpsEnvironment,
    ResourceContext,
)
from fdai_cost_governance.optimization import (
    CoupledResourceOptimizationPlan,
    OptimizationDisposition,
)
from fdai_cost_governance.pantheon_composition import (
    compose_njord_optimization_candidate,
)

_NOW = datetime(2026, 10, 15, tzinfo=UTC)
_DIGEST = "sha256:" + "a" * 64


def _candidate(
    resource_id: str,
    *,
    kind: FinOpsActionKind = FinOpsActionKind.RIGHT_SIZE,
) -> FinOpsCandidate:
    return FinOpsCandidate(
        action_id=f"optimization:compute:{resource_id}",
        kind=kind,
        resource=ResourceContext(
            resource_id=resource_id,
            environment=FinOpsEnvironment.DEV,
            current_capacity=4,
        ),
        target_capacity=2 if kind is FinOpsActionKind.RIGHT_SIZE else None,
    )


def _plan(
    *, kind: FinOpsActionKind = FinOpsActionKind.RIGHT_SIZE
) -> CoupledResourceOptimizationPlan:
    return CoupledResourceOptimizationPlan(
        disposition=OptimizationDisposition.CANDIDATE,
        target_set_id="optimization-set:example",
        target_revision_digest=_DIGEST,
        candidates=(_candidate("resource-a", kind=kind), _candidate("resource-b", kind=kind)),
        profile_digests=("sha256:" + "b" * 64, "sha256:" + "b" * 64),
        causal_order=("resource-a", "resource-b"),
        logical_target_lock="optimization-lock:example",
        idempotency_key="optimization:example",
        reasons=(),
    )


def _effects() -> tuple[ObjectiveEffect, ...]:
    return (
        ObjectiveEffect(
            objective_id="objective.cost",
            utility=0.7,
            confidence=0.9,
            metric="monthly_cost_usd",
            expected_min=100.0,
            expected_max=120.0,
            observation_window_seconds=86400,
        ),
        ObjectiveEffect(
            objective_id="objective.availability",
            utility=0.0,
            confidence=0.9,
            metric="availability_ratio",
            expected_min=0.999,
            expected_max=1.0,
            observation_window_seconds=3600,
        ),
    )


def test_composes_validator_accepted_njord_candidate_with_pinned_lineage() -> None:
    payload = compose_njord_optimization_candidate(
        _plan(),
        correlation_id="cost-optimization-example",
        observed_at=_NOW,
        cost_objective_id="objective.cost",
        effects=_effects(),
        evidence_refs=("cost-evidence:example",),
        source_freshness=(
            SourceFreshness(
                source="cost-analytics",
                observed_at=_NOW,
                max_age_seconds=7200,
            ),
        ),
    )

    validate_cross_vertical_candidate(
        "object.cost-anomaly",
        {**payload, "producer_principal": "Njord"},
    )
    assert payload["action_type"] == "remediate.right-size"
    assert payload["resource_id"] == "optimization-set:example"
    assert f"optimization-target-revision:{_DIGEST}" in payload["evidence_refs"]
    assert any(
        reference.startswith("optimization-candidate:sha256:")
        for reference in payload["evidence_refs"]
    )
    assert any(
        reference.startswith("optimization-coordination:sha256:")
        for reference in payload["evidence_refs"]
    )
    assert payload["effects"][0]["objective_id"] == "objective.cost"
    assert "producer_principal" not in payload


def test_rejects_candidate_without_shared_action_type_mapping() -> None:
    with pytest.raises(ValueError, match="no shared ActionType mapping"):
        compose_njord_optimization_candidate(
            _plan(kind=FinOpsActionKind.SHUTDOWN),
            correlation_id="cost-optimization-example",
            observed_at=_NOW,
            cost_objective_id="objective.cost",
            effects=_effects(),
            evidence_refs=("cost-evidence:example",),
            source_freshness=(
                SourceFreshness(
                    source="cost-analytics",
                    observed_at=_NOW,
                    max_age_seconds=7200,
                ),
            ),
        )


def test_maximum_coupled_plan_stays_within_forseti_lineage_limit() -> None:
    candidates = tuple(_candidate(f"resource-{index}") for index in range(20))
    plan = replace(
        _plan(),
        candidates=candidates,
        profile_digests=tuple("sha256:" + "b" * 64 for _candidate_item in candidates),
        causal_order=tuple(item.resource.resource_id for item in candidates),
    )

    payload = compose_njord_optimization_candidate(
        plan,
        correlation_id="cost-optimization-maximum",
        observed_at=_NOW,
        cost_objective_id="objective.cost",
        effects=_effects(),
        evidence_refs=("cost-evidence:maximum",),
        source_freshness=(
            SourceFreshness(
                source="cost-analytics",
                observed_at=_NOW,
                max_age_seconds=7200,
            ),
        ),
    )

    validate_cross_vertical_candidate(
        "object.cost-anomaly",
        {**payload, "producer_principal": "Njord"},
    )
    assert len(payload["evidence_refs"]) == 23


def test_rejects_incomplete_causal_order() -> None:
    plan = replace(_plan(), causal_order=("resource-a", "resource-missing"))

    with pytest.raises(ValueError, match="causal order MUST cover each candidate once"):
        compose_njord_optimization_candidate(
            plan,
            correlation_id="cost-optimization-example",
            observed_at=_NOW,
            cost_objective_id="objective.cost",
            effects=_effects(),
            evidence_refs=("cost-evidence:example",),
            source_freshness=(
                SourceFreshness(
                    source="cost-analytics",
                    observed_at=_NOW,
                    max_age_seconds=7200,
                ),
            ),
        )


def test_rejects_duplicate_candidate_resources() -> None:
    plan = replace(
        _plan(),
        candidates=(
            _candidate("resource-a"),
            replace(_candidate("resource-a"), action_id="optimization:compute:duplicate"),
        ),
        causal_order=("resource-a",),
    )

    with pytest.raises(ValueError, match="MUST target unique resources"):
        compose_njord_optimization_candidate(
            plan,
            correlation_id="cost-optimization-example",
            observed_at=_NOW,
            cost_objective_id="objective.cost",
            effects=_effects(),
            evidence_refs=("cost-evidence:example",),
            source_freshness=(
                SourceFreshness(
                    source="cost-analytics",
                    observed_at=_NOW,
                    max_age_seconds=7200,
                ),
            ),
        )


def test_target_capacity_changes_candidate_lineage() -> None:
    first = _plan()
    second = replace(
        first,
        candidates=(replace(first.candidates[0], target_capacity=3), first.candidates[1]),
    )
    common = {
        "correlation_id": "cost-optimization-example",
        "observed_at": _NOW,
        "cost_objective_id": "objective.cost",
        "effects": _effects(),
        "evidence_refs": ("cost-evidence:example",),
        "source_freshness": (
            SourceFreshness(
                source="cost-analytics",
                observed_at=_NOW,
                max_age_seconds=7200,
            ),
        ),
    }

    first_refs = compose_njord_optimization_candidate(first, **common)["evidence_refs"]
    second_refs = compose_njord_optimization_candidate(second, **common)["evidence_refs"]

    assert first_refs != second_refs


def test_rejects_oversized_effects() -> None:
    with pytest.raises(ValueError, match="MUST carry objective effects"):
        compose_njord_optimization_candidate(
            _plan(),
            correlation_id="cost-optimization-example",
            observed_at=_NOW,
            cost_objective_id="objective.cost",
            effects=_effects() * 9,
            evidence_refs=("cost-evidence:example",),
            source_freshness=(
                SourceFreshness(
                    source="cost-analytics",
                    observed_at=_NOW,
                    max_age_seconds=7200,
                ),
            ),
        )


def test_rejects_duplicate_source_freshness() -> None:
    freshness = SourceFreshness(
        source="cost-analytics",
        observed_at=_NOW,
        max_age_seconds=7200,
    )

    with pytest.raises(ValueError, match="MUST be unique by source"):
        compose_njord_optimization_candidate(
            _plan(),
            correlation_id="cost-optimization-example",
            observed_at=_NOW,
            cost_objective_id="objective.cost",
            effects=_effects(),
            evidence_refs=("cost-evidence:example",),
            source_freshness=(freshness, freshness),
        )


def test_rejects_oversized_source_identity() -> None:
    with pytest.raises(ValueError, match="MUST use bounded exact sources"):
        compose_njord_optimization_candidate(
            _plan(),
            correlation_id="cost-optimization-example",
            observed_at=_NOW,
            cost_objective_id="objective.cost",
            effects=_effects(),
            evidence_refs=("cost-evidence:example",),
            source_freshness=(
                SourceFreshness(
                    source="s" * 513,
                    observed_at=_NOW,
                    max_age_seconds=7200,
                ),
            ),
        )


def test_rejects_evidence_that_exceeds_forseti_lineage_limit() -> None:
    with pytest.raises(ValueError, match="evidence refs exceed the intake limit"):
        compose_njord_optimization_candidate(
            _plan(),
            correlation_id="cost-optimization-example",
            observed_at=_NOW,
            cost_objective_id="objective.cost",
            effects=_effects(),
            evidence_refs=tuple(f"cost-evidence:{index}" for index in range(30)),
            source_freshness=(
                SourceFreshness(
                    source="cost-analytics",
                    observed_at=_NOW,
                    max_age_seconds=7200,
                ),
            ),
        )


def test_rejects_invalid_effects_and_future_source_evidence() -> None:
    duplicate_effects = (_effects()[0], _effects()[0])
    with pytest.raises(ValueError, match="effects MUST be unique"):
        compose_njord_optimization_candidate(
            _plan(),
            correlation_id="cost-optimization-example",
            observed_at=_NOW,
            cost_objective_id="objective.cost",
            effects=duplicate_effects,
            evidence_refs=("cost-evidence:example",),
            source_freshness=(
                SourceFreshness(
                    source="cost-analytics",
                    observed_at=_NOW,
                    max_age_seconds=7200,
                ),
            ),
        )

    with pytest.raises(ValueError, match="MUST improve its cost objective"):
        compose_njord_optimization_candidate(
            _plan(),
            correlation_id="cost-optimization-example",
            observed_at=_NOW,
            cost_objective_id="objective.availability",
            effects=_effects(),
            evidence_refs=("cost-evidence:example",),
            source_freshness=(
                SourceFreshness(
                    source="cost-analytics",
                    observed_at=_NOW,
                    max_age_seconds=7200,
                ),
            ),
        )

    with pytest.raises(ValueError, match="source evidence is from the future"):
        compose_njord_optimization_candidate(
            _plan(),
            correlation_id="cost-optimization-example",
            observed_at=_NOW,
            cost_objective_id="objective.cost",
            effects=_effects(),
            evidence_refs=("cost-evidence:example",),
            source_freshness=(
                SourceFreshness(
                    source="cost-analytics",
                    observed_at=_NOW + timedelta(seconds=1),
                    max_age_seconds=7200,
                ),
            ),
        )


def test_rejects_malformed_profile_lineage() -> None:
    malformed = replace(
        _plan(),
        profile_digests=("not-a-digest", "not-a-digest"),
    )

    with pytest.raises(ValueError, match="profile MUST be an exact SHA-256"):
        compose_njord_optimization_candidate(
            malformed,
            correlation_id="cost-optimization-example",
            observed_at=_NOW,
            cost_objective_id="objective.cost",
            effects=_effects(),
            evidence_refs=("cost-evidence:example",),
            source_freshness=(
                SourceFreshness(
                    source="cost-analytics",
                    observed_at=_NOW,
                    max_age_seconds=7200,
                ),
            ),
        )
