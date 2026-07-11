"""RcaCoordinator - tier routing + grounding-on-supplied-evidence.

The security-critical assertion here is that a T2 reasoner citation
outside the caller-supplied evidence set is refused (a fabricated /
prompt-injected citation never grounds a hypothesis).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import pytest

from fdai.core.rca import (
    Citation,
    CitationKind,
    CorrelatedEvent,
    RcaCoordinator,
    RcaOutcome,
    RcaTier,
    RootCauseHypothesis,
)
from fdai.shared.contracts.models import (
    Category,
    CheckLogic,
    CheckLogicKind,
    Provenance,
    Redistribution,
    Remediation,
    Rule,
    RuleSource,
    Severity,
)

_RULE_ID = "object-storage.owner-tag.required"
_CANDIDATES = (
    Citation(kind=CitationKind.RULE, ref=_RULE_ID),
    Citation(kind=CitationKind.EVENT, ref="e-1"),
)


def _rule() -> Rule:
    return Rule(
        schema_version="1.0.0",
        id=_RULE_ID,
        version="1.0.0",
        source=RuleSource.CUSTOM,
        severity=Severity.LOW,
        category=Category.CONFIG_DRIFT,
        resource_type="object-storage",
        check_logic=CheckLogic(
            kind=CheckLogicKind.REGO,
            reference="policies/object_storage/owner_tag_required.rego",
        ),
        remediation=Remediation(
            template_ref="remediation/object_storage/tag_owner.tftpl",
            cost_impact_monthly_usd=0,
        ),
        remediates="remediate.tag-add",
        parameters={},
        provenance=Provenance(
            source_url="https://example.com/rules/x",
            resolved_ref="0" * 40,
            content_hash="sha256:0",
            license="MIT",
            redistribution=Redistribution.EMBEDDABLE,
            retrieved_at="2026-07-05T00:00:00Z",  # type: ignore[arg-type]
        ),
    )


class _StubReasoner:
    def __init__(self, result: RootCauseHypothesis | None) -> None:
        self._result = result

    async def reason(
        self,
        *,
        incident_summary: str,
        candidate_citations: Sequence[Citation],
    ) -> RootCauseHypothesis | None:
        return self._result


def _t2(citations: tuple[Citation, ...], confidence: float = 0.9) -> RootCauseHypothesis:
    return RootCauseHypothesis(
        tier=RcaTier.T2,
        cause="runaway writer saturated the volume",
        confidence=confidence,
        citations=citations,
    )


def test_analyze_t0_is_grounded() -> None:
    coordinator = RcaCoordinator()
    result = coordinator.analyze_t0(rule=_rule(), resource_type="object-storage", event_id="e-1")
    assert result.outcome is RcaOutcome.GROUNDED
    assert result.hypothesis is not None
    assert result.hypothesis.tier is RcaTier.T0
    assert result.hypothesis.remediation_ref == "remediate.tag-add"


def test_analyze_t0_passes_high_confidence_floor() -> None:
    # T0 confidence is 1.0, so any floor <= 1.0 passes.
    coordinator = RcaCoordinator(min_confidence=1.0)
    result = coordinator.analyze_t0(rule=_rule(), resource_type="object-storage")
    assert result.outcome is RcaOutcome.GROUNDED


def test_constructor_validates_min_confidence() -> None:
    with pytest.raises(ValueError, match="min_confidence"):
        RcaCoordinator(min_confidence=1.5)


_FAIL_AT = datetime(2026, 7, 7, 12, 0, 0, tzinfo=UTC)
_WINDOW = timedelta(minutes=10)


def test_analyze_t1_causal_chain_grounds_multi_hop() -> None:
    coordinator = RcaCoordinator()
    events = [
        CorrelatedEvent(
            event_id="cfg",
            at=_FAIL_AT - timedelta(minutes=4),
            resource_ref="db",
            is_change=True,
        ),
        CorrelatedEvent(
            event_id="dbslow",
            at=_FAIL_AT - timedelta(minutes=1),
            resource_ref="db",
            is_change=False,
        ),
    ]
    result = coordinator.analyze_t1_causal_chain(
        failure_event_id="fail",
        failure_at=_FAIL_AT,
        failure_resource_ref="app",
        correlated_events=events,
        window=_WINDOW,
        depends_on={"app": {"db"}},
    )
    assert result.outcome is RcaOutcome.GROUNDED
    assert result.hypothesis is not None
    assert result.hypothesis.tier is RcaTier.T1
    assert result.hypothesis.evidence_refs == ("cfg", "dbslow", "fail")


def test_analyze_t1_causal_chain_abstains_on_pure_symptoms() -> None:
    coordinator = RcaCoordinator()
    events = [
        CorrelatedEvent(
            event_id="s1",
            at=_FAIL_AT - timedelta(minutes=1),
            resource_ref="app",
            is_change=False,
        ),
    ]
    result = coordinator.analyze_t1_causal_chain(
        failure_event_id="fail",
        failure_at=_FAIL_AT,
        failure_resource_ref="app",
        correlated_events=events,
        window=_WINDOW,
    )
    assert result.outcome is RcaOutcome.ABSTAINED
    assert result.hypothesis is None
    assert result.reason == "t1_no_causal_chain_in_window"


def test_has_t2_reflects_reasoner_binding() -> None:
    assert RcaCoordinator().has_t2 is False
    assert RcaCoordinator(reasoner=_StubReasoner(None)).has_t2 is True


def test_analyze_t1_causal_chain_respects_confidence_floor() -> None:
    # A far antecedent lands low in the T1 band; a high floor abstains it.
    coordinator = RcaCoordinator(min_confidence=0.84)
    events = [
        CorrelatedEvent(
            event_id="far",
            at=_FAIL_AT - timedelta(minutes=9),
            resource_ref="app",
            is_change=True,
        ),
    ]
    result = coordinator.analyze_t1_causal_chain(
        failure_event_id="fail",
        failure_at=_FAIL_AT,
        failure_resource_ref="app",
        correlated_events=events,
        window=_WINDOW,
    )
    assert result.outcome is RcaOutcome.ABSTAINED


@pytest.mark.asyncio
async def test_analyze_t2_without_reasoner_abstains() -> None:
    coordinator = RcaCoordinator()
    result = await coordinator.analyze_t2(incident_summary="novel", candidate_citations=_CANDIDATES)
    assert result.outcome is RcaOutcome.ABSTAINED
    assert "no_t2_reasoner" in result.reason


@pytest.mark.asyncio
async def test_analyze_t2_reasoner_none_abstains() -> None:
    coordinator = RcaCoordinator(reasoner=_StubReasoner(None))
    result = await coordinator.analyze_t2(incident_summary="novel", candidate_citations=_CANDIDATES)
    assert result.outcome is RcaOutcome.ABSTAINED
    assert "abstained" in result.reason


@pytest.mark.asyncio
async def test_analyze_t2_grounded_on_supplied_evidence() -> None:
    hypothesis = _t2((Citation(kind=CitationKind.RULE, ref=_RULE_ID),))
    coordinator = RcaCoordinator(reasoner=_StubReasoner(hypothesis))
    result = await coordinator.analyze_t2(incident_summary="novel", candidate_citations=_CANDIDATES)
    assert result.outcome is RcaOutcome.GROUNDED
    assert result.hypothesis == hypothesis


@pytest.mark.asyncio
async def test_analyze_t2_refuses_fabricated_citation() -> None:
    # The reasoner cites a rule that was NOT in the supplied evidence.
    hypothesis = _t2((Citation(kind=CitationKind.RULE, ref="fabricated.rule.id"),))
    coordinator = RcaCoordinator(reasoner=_StubReasoner(hypothesis))
    result = await coordinator.analyze_t2(incident_summary="novel", candidate_citations=_CANDIDATES)
    assert result.outcome is RcaOutcome.ABSTAINED
    assert "not_in_evidence" in result.reason


@pytest.mark.asyncio
async def test_analyze_t2_ungrounded_abstains() -> None:
    coordinator = RcaCoordinator(reasoner=_StubReasoner(_t2(())))
    result = await coordinator.analyze_t2(incident_summary="novel", candidate_citations=_CANDIDATES)
    assert result.outcome is RcaOutcome.ABSTAINED


@pytest.mark.asyncio
async def test_analyze_t2_below_confidence_abstains() -> None:
    hypothesis = _t2((Citation(kind=CitationKind.RULE, ref=_RULE_ID),), confidence=0.4)
    coordinator = RcaCoordinator(reasoner=_StubReasoner(hypothesis), min_confidence=0.8)
    result = await coordinator.analyze_t2(incident_summary="novel", candidate_citations=_CANDIDATES)
    assert result.outcome is RcaOutcome.ABSTAINED
    assert "below_min" in result.reason


# ---------------------------------------------------------------------------
# T1 correlation-cause reuse
# ---------------------------------------------------------------------------


def _prior(confidence: float = 0.9) -> RootCauseHypothesis:
    return RootCauseHypothesis(
        tier=RcaTier.T1,
        cause="prior resolved incident cause",
        confidence=confidence,
        citations=(Citation(kind=CitationKind.RULE, ref=_RULE_ID),),
        remediation_ref="remediate.tag-add",
    )


def test_analyze_t1_reuses_prior_cause_when_it_still_applies() -> None:
    coordinator = RcaCoordinator()
    result = coordinator.analyze_t1(
        prior_hypothesis=_prior(0.9),
        current_citations=_CANDIDATES,
        reuse_confidence_factor=0.8,
    )
    assert result.outcome is RcaOutcome.GROUNDED
    assert result.hypothesis is not None
    assert result.hypothesis.tier is RcaTier.T1
    # Reuse decays confidence (0.9 * 0.8).
    assert result.hypothesis.confidence == pytest.approx(0.72)
    assert result.hypothesis.cause == "prior resolved incident cause"
    assert result.hypothesis.remediation_ref == "remediate.tag-add"


def test_analyze_t1_stale_cause_abstains() -> None:
    # None of the prior cause's citations appear in the current evidence.
    coordinator = RcaCoordinator()
    result = coordinator.analyze_t1(
        prior_hypothesis=_prior(),
        current_citations=(Citation(kind=CitationKind.EVENT, ref="unrelated-event"),),
    )
    assert result.outcome is RcaOutcome.ABSTAINED
    assert "stale" in result.reason


def test_analyze_t1_below_confidence_abstains() -> None:
    coordinator = RcaCoordinator(min_confidence=0.8)
    result = coordinator.analyze_t1(
        prior_hypothesis=_prior(0.9),
        current_citations=_CANDIDATES,
        reuse_confidence_factor=0.5,  # 0.9 * 0.5 = 0.45 < 0.8
    )
    assert result.outcome is RcaOutcome.ABSTAINED
    assert "below_min" in result.reason


def test_analyze_t1_validates_reuse_factor() -> None:
    with pytest.raises(ValueError, match="reuse_confidence_factor"):
        RcaCoordinator().analyze_t1(
            prior_hypothesis=_prior(),
            current_citations=_CANDIDATES,
            reuse_confidence_factor=1.5,
        )
