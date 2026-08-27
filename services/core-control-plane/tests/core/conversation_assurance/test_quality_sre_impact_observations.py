from __future__ import annotations

import hashlib
from datetime import UTC, datetime

import pytest
from fdai.core.conversation_assurance.quality_sre_observations import (
    AlternativeCauseScenarioResult,
    ImpactScenarioResult,
    observe_alternative_causes,
    observe_impact_scenario,
)
from fdai.core.impact_analysis.change_assessment import ChangeAssessment
from fdai.core.impact_analysis.models import AffectedSet
from fdai.core.rca.contract import Citation, CitationKind, RcaTier, RootCauseHypothesis

_EVIDENCE = "a" * 64


def _hypothesis(cause: str, *, grounded: bool = True) -> RootCauseHypothesis:
    return RootCauseHypothesis(
        tier=RcaTier.T2,
        cause=cause,
        confidence=0.8,
        citations=((Citation(CitationKind.TELEMETRY, "metric-1"),) if grounded else ()),
    )


def _impact(*, truncated: bool = False) -> ChangeAssessment:
    affected = AffectedSet(
        direct_targets=("resource-1",),
        runtime_dependents=("resource-2",),
        protected_services=("service-1",),
        protected_objectives=("objective-1",),
        control_dependencies=(),
        graph_revision="graph-1",
        truncated=truncated,
    )
    return ChangeAssessment(
        change_id="change-1",
        correlation_id="correlation-1",
        target_ref="resource-1",
        occurred_at=datetime(2026, 8, 27, tzinfo=UTC),
        affected_set=affected,
        review_required=truncated,
        reasons=("impact_truncated",) if truncated else (),
        evidence_digest="b" * 64,
    )


def test_alternative_causes_compare_only_grounded_cause_digests() -> None:
    causes = (
        _hypothesis("Configuration drift."),
        _hypothesis("Capacity exhaustion."),
        _hypothesis("Unsupported guess.", grounded=False),
    )
    expected = tuple(hashlib.sha256(cause.cause.encode()).hexdigest() for cause in causes[:2])
    matching = observe_alternative_causes(
        AlternativeCauseScenarioResult("case-1", expected, causes, _EVIDENCE)
    )
    mismatch = observe_alternative_causes(
        AlternativeCauseScenarioResult("case-2", expected[:1], causes, _EVIDENCE)
    )
    assert matching.item_id == 19
    assert matching.value == 1.0
    assert mismatch.value == 0.0


def test_impact_compares_hashed_resource_set_and_completeness() -> None:
    expected = tuple(
        hashlib.sha256(value.encode()).hexdigest() for value in ("resource-1", "resource-2")
    )
    matching = observe_impact_scenario(
        ImpactScenarioResult("case-1", expected, True, _impact(), _EVIDENCE)
    )
    partial = observe_impact_scenario(
        ImpactScenarioResult(
            "case-2",
            expected,
            True,
            _impact(truncated=True),
            _EVIDENCE,
        )
    )
    assert matching.item_id == 20
    assert matching.value == 1.0
    assert partial.value == 0.0


def test_expected_commitments_must_be_digests() -> None:
    with pytest.raises(ValueError, match="cause values"):
        observe_alternative_causes(
            AlternativeCauseScenarioResult(
                "case-1",
                ("plain cause",),
                (_hypothesis("plain cause"),),
                _EVIDENCE,
            )
        )
