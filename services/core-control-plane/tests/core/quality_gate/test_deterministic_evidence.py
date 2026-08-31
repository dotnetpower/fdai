from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.quality_gate import (
    DeterministicEvidenceKind,
    DeterministicEvidenceStatus,
    DeterministicVerifierEvidence,
    QualityCandidate,
    QualityGate,
    QualityOutcome,
    quality_candidate_digest,
)
from fdai.core.quality_gate.testing import (
    InMemoryGroundingSource,
    MatchTypeCrossCheckModel,
    StaticVerifier,
)
from fdai.core.tiers.t2_reasoning import T2Outcome, T2ProposalContext, T2Tier
from fdai.shared.contracts.models import (
    Category,
    CheckLogic,
    CheckLogicKind,
    Event,
    Mode,
    Provenance,
    Redistribution,
    Remediation,
    Rule,
    RuleSource,
    Severity,
)

NOW = datetime(2026, 8, 31, tzinfo=UTC)


def _candidate() -> QualityCandidate:
    return QualityCandidate(
        action_type="remediate.tag-add",
        target_resource_ref="resource-a",
        target_resource_type="compute.vm",
        params={"tag_name": "owner", "tag_value": "team-a"},
        cited_rule_ids=("rule-a",),
        confidence_signals={"verified": 0.9},
    )


def _grounding() -> InMemoryGroundingSource:
    rule = Rule(
        schema_version="1.0.0",
        id="rule-a",
        version="1.0.0",
        source=RuleSource.CUSTOM,
        severity=Severity.LOW,
        category=Category.SECURITY,
        resource_type="compute.vm",
        check_logic=CheckLogic(kind=CheckLogicKind.REGO, reference="policies/x.rego"),
        remediation=Remediation(template_ref="remediation/x.tftpl"),
        remediates="remediate.tag-add",
        provenance=Provenance(
            source_url="https://example.com/x",
            resolved_ref="0" * 40,
            content_hash="sha256:0",
            license="MIT",
            redistribution=Redistribution.EMBEDDABLE,
            retrieved_at="2026-07-05T00:00:00Z",  # type: ignore[arg-type]
        ),
    )
    return InMemoryGroundingSource({"rule-a": rule})


@dataclass
class _EvidenceVerifier:
    kind: DeterministicEvidenceKind
    status: DeterministicEvidenceStatus = DeterministicEvidenceStatus.PASSED
    synthetic: bool = False
    observed_at: datetime = NOW
    expires_at: datetime = NOW + timedelta(minutes=5)
    mutate_digest: bool = False

    def verify(self, candidate: QualityCandidate) -> DeterministicVerifierEvidence:
        digest = quality_candidate_digest(candidate)
        if self.mutate_digest:
            digest = f"sha256:{'0' * 64}"
        return DeterministicVerifierEvidence(
            schema_version="1.0.0",
            kind=self.kind,
            status=self.status,
            candidate_digest=digest,
            source_authority=(
                "simulation_engine"
                if self.kind is DeterministicEvidenceKind.WHAT_IF
                else "security_scanner"
            ),
            producer_id=f"test-{self.kind.value}",
            observed_at=self.observed_at,
            expires_at=self.expires_at,
            evidence_refs=(f"evidence:{self.kind.value}",) if self.status.value == "passed" else (),
            synthetic=self.synthetic,
        )


class _CountingModel(MatchTypeCrossCheckModel):
    def __init__(self) -> None:
        self.calls = 0

    async def propose(self, candidate: QualityCandidate):
        self.calls += 1
        return await super().propose(candidate)


def _verifiers(
    *,
    what_if: _EvidenceVerifier | None = None,
    security: _EvidenceVerifier | None = None,
):
    what_if = what_if or _EvidenceVerifier(DeterministicEvidenceKind.WHAT_IF)
    security = security or _EvidenceVerifier(DeterministicEvidenceKind.SECURITY)
    return {what_if.kind: what_if, security.kind: security}


def _gate(verifiers, model=None) -> QualityGate:
    models = (model or MatchTypeCrossCheckModel(), MatchTypeCrossCheckModel())
    return QualityGate(
        verifier=StaticVerifier(outcome=True),
        cross_check_models=models,
        grounding=_grounding(),
        deterministic_evidence_verifiers=verifiers,
        evidence_clock=lambda: NOW,
    )


@pytest.mark.asyncio
async def test_both_current_independent_evidence_families_allow_eligibility() -> None:
    decision = await _gate(_verifiers()).evaluate(_candidate())
    assert decision.outcome is QualityOutcome.ELIGIBLE
    assert [item.kind for item in decision.deterministic_evidence] == list(
        DeterministicEvidenceKind
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("kind", "status", "outcome"),
    [
        (
            DeterministicEvidenceKind.WHAT_IF,
            DeterministicEvidenceStatus.UNAVAILABLE,
            QualityOutcome.ABSTAIN,
        ),
        (
            DeterministicEvidenceKind.SECURITY,
            DeterministicEvidenceStatus.CONFLICT,
            QualityOutcome.ABSTAIN,
        ),
        (
            DeterministicEvidenceKind.SECURITY,
            DeterministicEvidenceStatus.FAILED,
            QualityOutcome.DENY,
        ),
    ],
)
async def test_nonpassing_evidence_short_circuits_before_model_cross_check(
    kind: DeterministicEvidenceKind,
    status: DeterministicEvidenceStatus,
    outcome: QualityOutcome,
) -> None:
    model = _CountingModel()
    verifier = _EvidenceVerifier(kind, status=status)
    decision = await _gate(
        _verifiers(
            what_if=verifier if kind is DeterministicEvidenceKind.WHAT_IF else None,
            security=verifier if kind is DeterministicEvidenceKind.SECURITY else None,
        ),
        model,
    ).evaluate(_candidate())
    assert decision.outcome is outcome
    assert model.calls == 0


@pytest.mark.asyncio
async def test_stale_synthetic_and_candidate_mismatched_evidence_hold() -> None:
    variants = (
        _EvidenceVerifier(
            DeterministicEvidenceKind.WHAT_IF,
            expires_at=NOW - timedelta(seconds=1),
        ),
        _EvidenceVerifier(DeterministicEvidenceKind.WHAT_IF, synthetic=True),
        _EvidenceVerifier(DeterministicEvidenceKind.WHAT_IF, mutate_digest=True),
    )
    for verifier in variants:
        decision = await _gate(_verifiers(what_if=verifier)).evaluate(_candidate())
        assert decision.outcome is QualityOutcome.ABSTAIN


def test_partial_evidence_binding_is_rejected() -> None:
    with pytest.raises(ValueError, match="exactly what_if and security"):
        _gate(
            {
                DeterministicEvidenceKind.WHAT_IF: _EvidenceVerifier(
                    DeterministicEvidenceKind.WHAT_IF
                )
            }
        )


def test_evidence_record_rejects_wrong_authority_and_unreferenced_pass() -> None:
    valid = _EvidenceVerifier(DeterministicEvidenceKind.WHAT_IF).verify(_candidate())
    with pytest.raises(ValueError, match="authority"):
        replace(valid, source_authority="t2_model")
    with pytest.raises(ValueError, match="cite"):
        replace(valid, evidence_refs=())


@pytest.mark.asyncio
async def test_unavailable_evidence_cannot_reach_the_risk_gate() -> None:
    candidate = _candidate()

    class _Proposer:
        async def propose(self, *, context: T2ProposalContext) -> QualityCandidate:
            del context
            return candidate

    unavailable = _EvidenceVerifier(
        DeterministicEvidenceKind.WHAT_IF,
        status=DeterministicEvidenceStatus.UNAVAILABLE,
    )
    tier = T2Tier(
        proposer=_Proposer(),
        quality_gate=_gate(_verifiers(what_if=unavailable)),
    )
    event = Event(
        schema_version="1.0.0",
        event_id="00000000-0000-0000-0000-000000000001",
        idempotency_key="event-a",
        source="test",
        event_type="test",
        resource_ref="resource-a",
        detected_at=NOW,
        ingested_at=NOW,
        mode=Mode.SHADOW,
    )
    allowed_rule = _grounding().get("rule-a")
    assert allowed_rule is not None

    decision = await tier.evaluate(
        context=T2ProposalContext(
            event=event,
            target_resource_ref="resource-a",
            target_resource_type="compute.vm",
            allowed_rules=(allowed_rule,),
        )
    )

    assert decision.outcome is T2Outcome.ESCALATE
    assert decision.eligible_for_risk_gate is False
