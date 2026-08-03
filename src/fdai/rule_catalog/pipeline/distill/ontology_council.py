"""Blind deterministic orchestration for ontology-aware model distillation."""

from __future__ import annotations

import asyncio
import math
from dataclasses import dataclass
from typing import Protocol, cast, runtime_checkable

from fdai.rule_catalog.pipeline.distill.coverage import analyze_coverage
from fdai.rule_catalog.pipeline.distill.ontology_claims import (
    claim_text_records,
    inventory_claims,
)
from fdai.rule_catalog.pipeline.distill.ontology_council_packets import (
    build_council_claim_packet,
    candidate_from_council_vote,
)
from fdai.rule_catalog.pipeline.distill.ontology_council_reducer import (
    CouncilRoundDecision,
    reduce_council_votes,
    validate_council_vote,
)
from fdai.rule_catalog.pipeline.distill.ontology_models import ClaimUnit, stable_digest
from fdai.rule_catalog.pipeline.distill.ontology_verify import VerificationContext
from fdai.shared.providers.distiller import (
    DistillationResult,
    DistilledCandidate,
    DistillerAvailability,
    DistillerCapabilityDescriptor,
    ManualDocument,
)
from fdai.shared.providers.ontology_council import (
    CouncilClaimPacket,
    CouncilDispute,
    CouncilModelIdentity,
    CouncilOutcome,
    CouncilVote,
    OntologyCouncilModel,
)
from fdai.shared.providers.ontology_council_errors import (
    CouncilBudgetExceededError,
    CouncilContextGapError,
)
from fdai.shared.providers.ontology_council_receipt import OntologyCouncilReceipt


@runtime_checkable
class OntologyAwareDistiller(Protocol):
    """Distill a document against one immutable ontology verification context."""

    async def distill_ontology(
        self,
        document: ManualDocument,
        context: VerificationContext,
    ) -> DistillationResult: ...


@dataclass(frozen=True, slots=True)
class OntologyCouncilPolicy:
    policy_id: str
    version: str
    prompt_digest: str
    schema_digest: str
    call_timeout_seconds: float = 30.0
    max_claims: int = 256

    def __post_init__(self) -> None:
        if not self.policy_id.strip() or len(self.policy_id) > 128:
            raise ValueError("council policy id MUST be bounded and non-empty")
        if not self.version.strip() or len(self.version) > 128:
            raise ValueError("council policy version MUST be bounded and non-empty")
        for value in (self.prompt_digest, self.schema_digest):
            if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
                raise ValueError("council prompt and schema digests MUST be lowercase SHA-256")
        if not math.isfinite(self.call_timeout_seconds) or self.call_timeout_seconds <= 0.0:
            raise ValueError("council call timeout MUST be finite and positive")
        if not 1 <= self.max_claims <= 10_000:
            raise ValueError("council max claims MUST be between 1 and 10000")

    @property
    def digest(self) -> str:
        return stable_digest(
            {
                "policy_id": self.policy_id,
                "version": self.version,
                "prompt_digest": self.prompt_digest,
                "schema_digest": self.schema_digest,
                "call_timeout_seconds": self.call_timeout_seconds,
                "max_claims": self.max_claims,
                "required_models": 3,
                "required_consensus": 3,
                "revision_rounds": 1,
            }
        )


@dataclass(frozen=True, slots=True)
class _RoundResult:
    votes: tuple[CouncilVote, CouncilVote, CouncilVote] | None
    digests: tuple[str, str, str]
    reason_codes: tuple[str, ...]


class OntologyCouncilDistiller:
    """Generate inert candidates only after exact three-family agreement."""

    def __init__(
        self,
        *,
        models: tuple[OntologyCouncilModel, OntologyCouncilModel, OntologyCouncilModel],
        policy: OntologyCouncilPolicy,
    ) -> None:
        ordered = tuple(sorted(models, key=lambda model: model.identity.digest))
        identities = tuple(model.identity for model in ordered)
        if len({(item.publisher, item.family) for item in identities}) != 3:
            raise ValueError("ontology council requires three distinct model families")
        if len({item.binding for item in identities}) != 3:
            raise ValueError("ontology council requires three unique model bindings")
        self._models = cast(
            tuple[OntologyCouncilModel, OntologyCouncilModel, OntologyCouncilModel],
            ordered,
        )
        self._policy = policy

    def distiller_capability(self) -> DistillerCapabilityDescriptor:
        return DistillerCapabilityDescriptor(
            binding_id=self._policy.policy_id,
            binding_version=self._policy.version,
            contract_version="ontology-distiller-conformance.v1",
            availability=DistillerAvailability.AVAILABLE,
        )

    async def distill_ontology(
        self,
        document: ManualDocument,
        context: VerificationContext,
    ) -> DistillationResult:
        claims = inventory_claims(document)
        exact_text = dict(claim_text_records(document, claims))
        candidates: list[DistilledCandidate] = []
        receipts: list[OntologyCouncilReceipt] = []
        for index, claim in enumerate(claims):
            packet = build_council_claim_packet(claim, exact_text[claim.claim_id], context)
            if index >= self._policy.max_claims:
                receipts.append(self._budget_receipt(claim, packet))
                continue
            candidate, receipt = await self._distill_claim(document, claim, packet)
            if candidate is not None:
                candidates.append(candidate)
            receipts.append(receipt)
        candidate_tuple = tuple(candidates)
        return DistillationResult(
            candidates=candidate_tuple,
            coverage=analyze_coverage(document.text, candidate_tuple),
            council_receipts=tuple(receipts),
        )

    async def _distill_claim(
        self,
        document: ManualDocument,
        claim: ClaimUnit,
        packet: CouncilClaimPacket,
    ) -> tuple[DistilledCandidate | None, OntologyCouncilReceipt]:
        initial = await self._run_round(packet, dispute=None)
        if initial.votes is None:
            return None, self._receipt(
                claim,
                packet,
                initial=initial,
                outcome=CouncilOutcome.UNRESOLVED,
                reason_codes=initial.reason_codes,
            )
        initial_decision = reduce_council_votes(initial.votes)
        if initial_decision.outcome in {CouncilOutcome.CONSENSUS, CouncilOutcome.UNSUPPORTED}:
            return self._close_decision(
                document,
                claim,
                packet,
                initial,
                initial_decision,
            )
        if not initial_decision.differences:
            return None, self._receipt(
                claim,
                packet,
                initial=initial,
                outcome=CouncilOutcome.UNRESOLVED,
                reason_codes=("no_revision_difference",),
            )
        dispute = CouncilDispute(
            claim_id=claim.claim_id,
            packet_digest=packet.digest,
            initial_vote_digests=initial.digests,
            differences=initial_decision.differences,
        )
        revised = await self._run_round(packet, dispute=dispute)
        if revised.votes is None:
            outcome = (
                CouncilOutcome.CONTESTED
                if initial_decision.outcome is CouncilOutcome.CONTESTED
                else CouncilOutcome.UNRESOLVED
            )
            return None, self._receipt(
                claim,
                packet,
                initial=initial,
                revised=revised,
                outcome=outcome,
                reason_codes=("revision_failed", *revised.reason_codes),
                disputed_fields=tuple(item.field_name for item in dispute.differences),
            )
        revised_decision = reduce_council_votes(revised.votes)
        return self._close_decision(
            document,
            claim,
            packet,
            initial,
            revised_decision,
            revised=revised,
            disputed_fields=tuple(item.field_name for item in dispute.differences),
        )

    async def _run_round(
        self,
        packet: CouncilClaimPacket,
        *,
        dispute: CouncilDispute | None,
    ) -> _RoundResult:
        calls = (self._invoke(model, packet, dispute=dispute) for model in self._models)
        results = tuple(await asyncio.gather(*calls, return_exceptions=True))
        votes: list[CouncilVote] = []
        digests: list[str] = []
        reasons: list[str] = []
        for model, result in zip(self._models, results, strict=True):
            if isinstance(result, asyncio.CancelledError):
                raise result
            if isinstance(result, Exception):
                reason = _exception_reason(result)
                reasons.append(reason)
                digests.append(_failed_attempt_digest(model.identity, reason, dispute is not None))
                continue
            if not isinstance(result, CouncilVote):
                reasons.append("invalid_vote")
                digests.append(
                    _failed_attempt_digest(model.identity, "invalid_vote", dispute is not None)
                )
                continue
            try:
                vote = validate_council_vote(
                    result,
                    expected_model=model.identity,
                    packet=packet,
                )
            except ValueError:
                reasons.append("invalid_vote")
                digests.append(
                    _failed_attempt_digest(model.identity, "invalid_vote", dispute is not None)
                )
                continue
            votes.append(vote)
            digests.append(vote.digest)
        fixed_digests = cast(tuple[str, str, str], tuple(digests))
        if reasons:
            return _RoundResult(None, fixed_digests, tuple(sorted(set(reasons))))
        return _RoundResult(
            cast(tuple[CouncilVote, CouncilVote, CouncilVote], tuple(votes)),
            fixed_digests,
            (),
        )

    async def _invoke(
        self,
        model: OntologyCouncilModel,
        packet: CouncilClaimPacket,
        *,
        dispute: CouncilDispute | None,
    ) -> CouncilVote:
        call = model.blind_vote(packet) if dispute is None else model.revise_vote(packet, dispute)
        return await asyncio.wait_for(call, timeout=self._policy.call_timeout_seconds)

    def _close_decision(
        self,
        document: ManualDocument,
        claim: ClaimUnit,
        packet: CouncilClaimPacket,
        initial: _RoundResult,
        decision: CouncilRoundDecision,
        *,
        revised: _RoundResult | None = None,
        disputed_fields: tuple[str, ...] = (),
    ) -> tuple[DistilledCandidate | None, OntologyCouncilReceipt]:
        candidate = None
        if decision.outcome is CouncilOutcome.CONSENSUS:
            if decision.consensus_vote is None:
                raise ValueError("consensus decision MUST include its exact vote")
            candidate = candidate_from_council_vote(
                document,
                claim,
                decision.consensus_vote,
            )
        return candidate, self._receipt(
            claim,
            packet,
            initial=initial,
            revised=revised,
            outcome=decision.outcome,
            reason_codes=decision.reason_codes,
            disputed_fields=disputed_fields,
        )

    def _receipt(
        self,
        claim: ClaimUnit,
        packet: CouncilClaimPacket,
        *,
        initial: _RoundResult,
        outcome: CouncilOutcome,
        reason_codes: tuple[str, ...],
        revised: _RoundResult | None = None,
        disputed_fields: tuple[str, ...] = (),
    ) -> OntologyCouncilReceipt:
        return OntologyCouncilReceipt(
            claim_digest=stable_digest(claim.claim_id),
            packet_digest=packet.digest,
            policy_digest=self._policy.digest,
            model_digests=cast(
                tuple[str, str, str],
                tuple(model.identity.digest for model in self._models),
            ),
            initial_vote_digests=initial.digests,
            revised_vote_digests=revised.digests if revised is not None else (),
            disputed_fields=disputed_fields,
            outcome=outcome,
            reason_codes=tuple(sorted(set(reason_codes))),
            rounds=2 if revised is not None else 1,
        )

    def _budget_receipt(
        self,
        claim: ClaimUnit,
        packet: CouncilClaimPacket,
    ) -> OntologyCouncilReceipt:
        attempts = cast(
            tuple[str, str, str],
            tuple(
                _failed_attempt_digest(model.identity, "claim_budget_exhausted", False)
                for model in self._models
            ),
        )
        return self._receipt(
            claim,
            packet,
            initial=_RoundResult(None, attempts, ("claim_budget_exhausted",)),
            outcome=CouncilOutcome.UNRESOLVED,
            reason_codes=("claim_budget_exhausted",),
        )


def _failed_attempt_digest(
    model: CouncilModelIdentity,
    reason_code: str,
    revision: bool,
) -> str:
    return stable_digest(
        {
            "model_digest": model.digest,
            "reason_code": reason_code,
            "round": "revision" if revision else "blind",
        }
    )


def _exception_reason(error: Exception) -> str:
    if isinstance(error, TimeoutError):
        return "model_timeout"
    if isinstance(error, CouncilBudgetExceededError):
        return "budget_exhausted"
    if isinstance(error, CouncilContextGapError):
        return "context_gap"
    return "model_exception"


__all__ = [
    "OntologyAwareDistiller",
    "OntologyCouncilDistiller",
    "OntologyCouncilPolicy",
]
