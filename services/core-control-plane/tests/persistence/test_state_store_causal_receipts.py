from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fdai.core.rca.hypothesis import (
    CausalEvidenceAssessment,
    CausalHypothesisRecord,
    build_causal_hypothesis,
)
from fdai.core.rca.runtime import CausalClosureObservation
from fdai.delivery.persistence.state_store_causal_receipts import (
    StateStoreCausalInterventionReceiptVerifier,
)
from fdai.shared.contracts.models import CausalEvidenceGrade
from fdai.shared.providers.testing import InMemoryStateStore

_NOW = datetime(2026, 8, 12, tzinfo=UTC)
_RECEIPT = "a" * 64


def _hypothesis() -> CausalHypothesisRecord:
    return build_causal_hypothesis(
        incident_id="incident-1",
        cause_ref="metric:node_cpu_percent",
        effect_ref="event:effect-1",
        mechanism="node-pressure",
        graph_revision="graph-1",
        evidence_cutoff=_NOW,
        method_version="temporal-causality-v1",
        evidence_grade=CausalEvidenceGrade.QUASI_EXPERIMENTAL,
        assessment=CausalEvidenceAssessment(
            temporal_precedence=0.9,
            topological_reachability=0.9,
            mechanism_fit=0.9,
            intervention_consistency=0.9,
            evidence_completeness=1.0,
            supporting_refs=("support-1",),
        ),
        created_at=_NOW,
    )


def _observation(**changes: Any) -> CausalClosureObservation:
    hypothesis = _hypothesis()
    values: dict[str, Any] = {
        "hypothesis": hypothesis,
        "finding_id": "finding-1",
        "outcome_ref": "outcome-1",
        "observed_at": _NOW + timedelta(minutes=30),
        "expected_direction_matched": True,
        "telemetry_complete": True,
        "within_window": True,
        "affected_scope_safe": True,
        "intervention_approved": True,
        "independent_observer": True,
        "intervention_receipt_digest": _RECEIPT,
        "intervention_executed_at": _NOW + timedelta(minutes=5),
        "intervention_target_ref": hypothesis.cause_ref,
        "predicted_effect_ref": hypothesis.effect_ref,
        "prohibited_effects_absent": True,
        "intervention_action_ref": "run-1",
    }
    values.update(changes)
    return CausalClosureObservation(**values)


def _run(**changes: Any) -> dict[str, Any]:
    run: dict[str, Any] = {
        "correlation_id": "run-1",
        "state": "succeeded",
        "shadow_mode": False,
        "resource_id": "/subscriptions/example/resourceGroups/example",
        "params": {"causal_hypothesis_ref": _hypothesis().hypothesis_id},
        "execution_closure_ref": _RECEIPT,
        "effect_verification_ref": "b" * 64,
        "effect_verified_at": (_NOW + timedelta(minutes=10)).isoformat(),
    }
    run.update(changes)
    return run


async def _verify(run: dict[str, Any] | None, observation: CausalClosureObservation) -> bool:
    store = InMemoryStateStore()
    if run is not None:
        await store.write_state("thor:run|run-1", run)
    return await StateStoreCausalInterventionReceiptVerifier(store).verify(observation)


async def test_exact_verified_action_run_resolves_the_receipt() -> None:
    assert await _verify(_run(), _observation()) is True


async def test_effect_verification_ref_also_resolves_the_receipt() -> None:
    run = _run(execution_closure_ref="c" * 64, effect_verification_ref=_RECEIPT)
    assert await _verify(run, _observation()) is True


@pytest.mark.parametrize(
    "run",
    [
        None,
        _run(state="failed"),
        _run(state="rolled_back"),
        _run(shadow_mode=True),
        _run(shadow_mode=None),
        _run(correlation_id="run-2"),
        _run(params={"causal_hypothesis_ref": "causal-other"}),
        _run(params={}),
        _run(params="not-a-mapping"),
        _run(execution_closure_ref="c" * 64, effect_verification_ref="d" * 64),
        _run(effect_verified_at=None),
        _run(effect_verified_at="not-a-time"),
        _run(effect_verified_at="2026-08-12T00:10:00"),
        _run(effect_verified_at=(_NOW + timedelta(minutes=1)).isoformat()),
        _run(effect_verified_at=(_NOW + timedelta(hours=2)).isoformat()),
    ],
)
async def test_missing_or_inconsistent_run_never_resolves(run: dict[str, Any] | None) -> None:
    assert await _verify(run, _observation()) is False


async def test_observation_without_action_ref_never_resolves() -> None:
    assert await _verify(_run(), replace(_observation(), intervention_action_ref=None)) is False


def test_action_ref_requires_a_receipt_and_bounded_text() -> None:
    with pytest.raises(ValueError, match="action ref"):
        _observation(
            intervention_receipt_digest=None,
            intervention_executed_at=None,
            intervention_target_ref=None,
            predicted_effect_ref=None,
            prohibited_effects_absent=None,
        )
    with pytest.raises(ValueError, match="action ref"):
        _observation(intervention_action_ref=" ")
    with pytest.raises(ValueError, match="action ref"):
        _observation(intervention_action_ref="x" * 257)
