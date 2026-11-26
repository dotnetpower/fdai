from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.quality_gate import (
    DeterministicEvidenceKind,
    DeterministicEvidenceStatus,
    DeterministicVerifierEvidence,
    HashedRuleEmbeddingIndex,
    QualityCandidate,
    QualityGate,
    QualityOutcome,
    RagGroundingSource,
    RuleBasedVerifier,
    RuleEmbeddingIndex,
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
        super().__init__(model_id="counting")
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
    models = (
        model or MatchTypeCrossCheckModel(model_id="primary"),
        MatchTypeCrossCheckModel(model_id="secondary"),
    )
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
    with pytest.raises(ValueError, match="producer_id"):
        replace(valid, producer_id="x" * 129)
    with pytest.raises(ValueError, match="bounded and unique"):
        replace(valid, evidence_refs=("evidence:duplicate", "evidence:duplicate"))
    with pytest.raises(ValueError, match="bounded text"):
        replace(valid, status=DeterministicEvidenceStatus.FAILED, reason="x" * 513)


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


# ---------------------------------------------------------------------------
# RuleBasedVerifier unit coverage
# ---------------------------------------------------------------------------


def _catalog_rule(
    rule_id: str = "rule-a",
    *,
    resource_type: str = "compute.vm",
    applies_to: list[str] | None = None,
    remediates: str = "remediate.tag-add",
    alternatives: list[str] | None = None,
    reference: str = "policies/tag_owner.rego",
) -> Rule:
    return Rule(
        schema_version="1.0.0",
        id=rule_id,
        version="1.0.0",
        source=RuleSource.CUSTOM,
        severity=Severity.LOW,
        category=Category.SECURITY,
        resource_type=resource_type,
        applies_to=applies_to or [],
        check_logic=CheckLogic(kind=CheckLogicKind.REGO, reference=reference),
        remediation=Remediation(template_ref="remediation/x.tftpl"),
        remediates=remediates,
        alternatives=alternatives or [],
        provenance=Provenance(
            source_url="https://example.com/x",
            resolved_ref="0" * 40,
            content_hash="sha256:0",
            license="MIT",
            redistribution=Redistribution.EMBEDDABLE,
            retrieved_at="2026-07-05T00:00:00Z",  # type: ignore[arg-type]
        ),
    )


def test_rule_based_verifier_abstains_when_no_cited_rules_resolve() -> None:
    verifier = RuleBasedVerifier(rules_by_id={"rule-a": _catalog_rule()})
    assert verifier.verify(replace(_candidate(), cited_rule_ids=())) is None
    assert verifier.verify(replace(_candidate(), cited_rule_ids=("unknown-rule",))) is None


def test_rule_based_verifier_abstains_when_target_resource_type_cannot_be_resolved() -> None:
    no_type_candidate = replace(_candidate(), target_resource_type=None)
    verifier_without_lookup = RuleBasedVerifier(rules_by_id={"rule-a": _catalog_rule()})
    assert verifier_without_lookup.verify(no_type_candidate) is None

    verifier_missing_ref = RuleBasedVerifier(
        rules_by_id={"rule-a": _catalog_rule()},
        target_resource_type_lookup={"other-resource": "compute.vm"},
    )
    assert verifier_missing_ref.verify(no_type_candidate) is None


def test_rule_based_verifier_resolves_target_type_from_lookup_and_matches_remediates() -> None:
    no_type_candidate = replace(_candidate(), target_resource_type=None)
    verifier = RuleBasedVerifier(
        rules_by_id={"rule-a": _catalog_rule()},
        target_resource_type_lookup={"resource-a": "compute.vm"},
    )
    assert verifier.verify(no_type_candidate) is True


def test_rule_based_verifier_matches_alternatives_and_applies_to_list() -> None:
    rule_mismatch_type = _catalog_rule("rule-mismatch", resource_type="storage.bucket")
    rule_applies_to = _catalog_rule(
        "rule-alt",
        resource_type="compute.scale-set",
        applies_to=["compute.vm"],
        remediates="remediate.restart",
        alternatives=["remediate.tag-add"],
    )
    verifier = RuleBasedVerifier(
        rules_by_id={"rule-mismatch": rule_mismatch_type, "rule-alt": rule_applies_to}
    )
    candidate = replace(_candidate(), cited_rule_ids=("rule-mismatch", "rule-alt"))
    assert verifier.verify(candidate) is True


def test_rule_based_verifier_denies_when_cited_rules_do_not_authorize_action() -> None:
    rule_no_alt = _catalog_rule("rule-1", remediates="remediate.restart", alternatives=[])
    rule_other_alt = _catalog_rule(
        "rule-2", remediates="remediate.restart", alternatives=["remediate.reimage"]
    )
    rule_wrong_type = _catalog_rule("rule-3", resource_type="network.vnet")
    verifier = RuleBasedVerifier(
        rules_by_id={
            "rule-1": rule_no_alt,
            "rule-2": rule_other_alt,
            "rule-3": rule_wrong_type,
        }
    )
    candidate = replace(_candidate(), cited_rule_ids=("rule-1", "rule-2", "rule-3"))
    assert verifier.verify(candidate) is False


# ---------------------------------------------------------------------------
# HashedRuleEmbeddingIndex & RagGroundingSource unit coverage
# ---------------------------------------------------------------------------


def test_hashed_rule_embedding_index_validation_and_cosine() -> None:
    with pytest.raises(ValueError, match="dim MUST be >= 1"):
        HashedRuleEmbeddingIndex(dim=0)
    with pytest.raises(ValueError, match="dim MUST be >= 1"):
        HashedRuleEmbeddingIndex(dim=True)

    index = HashedRuleEmbeddingIndex(dim=16)
    assert isinstance(index, RuleEmbeddingIndex)
    assert index.dim == 16

    zero_vec = index.encode("   ---   ")
    assert all(v == 0.0 for v in zero_vec)

    vec_a = index.encode("remediate.tag-add tag_name=owner")
    vec_b = index.encode("remediate.tag-add tag_name=owner")
    assert index.cosine(vec_a, vec_b) == pytest.approx(1.0)
    assert index.cosine(zero_vec, vec_a) == 0.0
    assert index.cosine(vec_a, zero_vec) == 0.0

    with pytest.raises(ValueError, match="equal-length vectors"):
        index.cosine((1.0, 0.0), (1.0,))


def test_rag_grounding_source_validation_and_supports_branches() -> None:
    index = HashedRuleEmbeddingIndex(dim=32)
    rule_primary = _catalog_rule(
        "rule-a",
        remediates="remediate.tag-add",
        alternatives=["remediate.custom-fallback"],
        reference="policies/tag_add_owner.rego",
    )
    with pytest.raises(ValueError, match="threshold MUST be in"):
        RagGroundingSource(rules={"rule-a": rule_primary}, embedding_index=index, threshold=1.2)
    with pytest.raises(ValueError, match="threshold MUST be in"):
        RagGroundingSource(rules={"rule-a": rule_primary}, embedding_index=index, threshold=-1.2)

    source = RagGroundingSource(
        rules={"rule-a": rule_primary},
        embedding_index=index,
        threshold=0.3,
    )
    assert source.known_rule_ids() == {"rule-a"}
    assert source.known_rule_count == 1
    assert source.threshold == pytest.approx(0.3)
    assert source.get("rule-a") == rule_primary
    assert source.get("unknown") is None

    # Unknown rule id returns False.
    assert source.supports(_candidate(), "unknown") is False

    # Exact match in Rule.alternatives returns True before similarity calculation.
    alt_candidate = replace(_candidate(), action_type="remediate.custom-fallback", params={})
    assert source.supports(alt_candidate, "rule-a") is True

    # Candidate with empty params vs non-empty params on similarity path.
    empty_params_candidate = replace(_candidate(), params={})
    assert source.supports(empty_params_candidate, "rule-a") is True
    assert source.supports(_candidate(), "rule-a") is True

    # Unrelated action_type with zero shared tokens fails threshold.
    unrelated = replace(_candidate(), action_type=" isolate.quantum.flux ", params={})
    assert source.supports(unrelated, "rule-a") is False
