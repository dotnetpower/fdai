"""RCA contract + T0 deterministic cause + grounding gate + reasoner seam.

Covers observability-and-detection.md section 4: a hypothesis with
citations, deterministic T0 cause from the matched rule, and the
"ground or abstain to HIL" gate. The T2 reasoner is exercised through a
fake implementing the RcaReasoner Protocol (no live LLM).
"""

from __future__ import annotations

from collections.abc import Sequence

import pytest
from fdai.core.rca import (
    Citation,
    CitationKind,
    RcaOutcome,
    RcaReasoner,
    RcaTier,
    RootCauseHypothesis,
    enforce_grounding,
    t0_root_cause,
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


def _grounded(confidence: float = 0.9, tier: RcaTier = RcaTier.T2) -> RootCauseHypothesis:
    return RootCauseHypothesis(
        tier=tier,
        cause="disk saturation from a runaway writer",
        confidence=confidence,
        citations=(Citation(kind=CitationKind.RULE, ref=_RULE_ID),),
    )


def _ungrounded(confidence: float = 0.9) -> RootCauseHypothesis:
    return RootCauseHypothesis(
        tier=RcaTier.T2,
        cause="a guess with no evidence",
        confidence=confidence,
        citations=(),
    )


# ---------------------------------------------------------------------------
# T0 deterministic RCA
# ---------------------------------------------------------------------------


def test_t0_root_cause_is_grounded_on_the_rule() -> None:
    h = t0_root_cause(rule=_rule(), resource_type="object-storage", event_id="e-1")
    assert h.tier is RcaTier.T0
    assert h.confidence == 1.0
    assert h.grounded is True
    assert len(h.citations) == 1
    assert h.citations[0].kind is CitationKind.RULE
    assert h.citations[0].ref == _RULE_ID
    assert h.remediation_ref == "remediate.tag-add"
    assert _RULE_ID in h.cause
    assert "object-storage" in h.cause
    # Evidence carries the check-logic reference and the triggering event.
    assert "policies/object_storage/owner_tag_required.rego" in h.evidence_refs
    assert "e-1" in h.evidence_refs


def test_t0_root_cause_is_deterministic() -> None:
    a = t0_root_cause(rule=_rule(), resource_type="object-storage")
    b = t0_root_cause(rule=_rule(), resource_type="object-storage")
    assert a == b


def test_t0_hypothesis_passes_grounding() -> None:
    h = t0_root_cause(rule=_rule(), resource_type="object-storage")
    result = enforce_grounding(h)
    assert result.outcome is RcaOutcome.GROUNDED
    assert result.is_grounded is True
    assert result.hypothesis == h


# ---------------------------------------------------------------------------
# Grounding gate
# ---------------------------------------------------------------------------


def test_grounded_property() -> None:
    assert _grounded().grounded is True
    assert _ungrounded().grounded is False


def test_ungrounded_abstains_to_hil() -> None:
    result = enforce_grounding(_ungrounded())
    assert result.outcome is RcaOutcome.ABSTAINED
    assert result.hypothesis is None
    assert "ungrounded" in result.reason


def test_confidence_below_floor_abstains() -> None:
    result = enforce_grounding(_grounded(confidence=0.5), min_confidence=0.8)
    assert result.outcome is RcaOutcome.ABSTAINED
    assert result.hypothesis is None
    assert "below_min" in result.reason


def test_confidence_at_or_above_floor_grounds() -> None:
    result = enforce_grounding(_grounded(confidence=0.8), min_confidence=0.8)
    assert result.outcome is RcaOutcome.GROUNDED


@pytest.mark.parametrize("bad", [-0.1, 1.5])
def test_invalid_confidence_abstains(bad: float) -> None:
    result = enforce_grounding(_grounded(confidence=bad))
    assert result.outcome is RcaOutcome.ABSTAINED
    assert "invalid_confidence" in result.reason


def test_invalid_min_confidence_raises() -> None:
    with pytest.raises(ValueError, match="min_confidence"):
        enforce_grounding(_grounded(), min_confidence=1.5)


# ---------------------------------------------------------------------------
# T2 reasoner seam (fake - no live LLM)
# ---------------------------------------------------------------------------


class _StubReasoner:
    """Fake RcaReasoner returning a preprogrammed hypothesis (or None)."""

    def __init__(self, result: RootCauseHypothesis | None) -> None:
        self._result = result
        self.calls = 0

    async def reason(
        self,
        *,
        incident_summary: str,
        candidate_citations: Sequence[Citation],
    ) -> RootCauseHypothesis | None:
        self.calls += 1
        return self._result


def test_stub_reasoner_satisfies_protocol() -> None:
    assert isinstance(_StubReasoner(None), RcaReasoner)


@pytest.mark.asyncio
async def test_reasoner_grounded_hypothesis_passes_gate() -> None:
    reasoner = _StubReasoner(_grounded(confidence=0.95))
    h = await reasoner.reason(incident_summary="novel", candidate_citations=())
    assert h is not None
    assert enforce_grounding(h).outcome is RcaOutcome.GROUNDED


@pytest.mark.asyncio
async def test_reasoner_ungrounded_hypothesis_abstains() -> None:
    reasoner = _StubReasoner(_ungrounded())
    h = await reasoner.reason(incident_summary="novel", candidate_citations=())
    assert h is not None
    assert enforce_grounding(h).outcome is RcaOutcome.ABSTAINED


@pytest.mark.asyncio
async def test_reasoner_none_is_explicit_abstain() -> None:
    reasoner = _StubReasoner(None)
    h = await reasoner.reason(incident_summary="novel", candidate_citations=())
    assert h is None  # the caller routes an abstaining reasoner to HIL
    assert reasoner.calls == 1
