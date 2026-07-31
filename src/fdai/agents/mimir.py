"""Mimir - Rule Steward (Wave 2 behavior).

Mimir tracks rule shadow / enforce promotion. Wave 2 exposes a minimal
in-memory promotion tracker; the concrete rule catalog loader stays in
:mod:`fdai.rule_catalog`. Mimir's job here is the promotion state
machine and the RuleCandidate intake.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Any

from fdai.agents._framework.base import Agent
from fdai.agents._framework.bounded import BoundedLruDict
from fdai.agents._framework.candidate_guard import CandidateGuard
from fdai.agents._framework.introspection import (
    IntrospectionResult,
    capability_facts,
    capped_list,
    mentioned,
)
from fdai.agents._framework.pantheon import _MIMIR
from fdai.core.operational_learning import (
    CatalogCandidateCompiler,
    CatalogCompilationError,
    CatalogReviewPackage,
    CatalogReviewPublicationReceipt,
    CatalogReviewPublisher,
)

#: Cap on retained rejected-candidate records. Quarantine holds candidates the
#: CandidateGuard REJECTED - i.e. attacker-controlled volume under a
#: candidate-poisoning attempt. An unbounded list would be a memory-exhaustion
#: DoS vector: a poisoning flood grows it without limit. The durable audit
#: trail is Saga's chain; this in-memory list is a bounded diagnostic ring.
_MAX_QUARANTINE = 5_000
_MAX_PENDING_CANDIDATES = 5_000
_MAX_CATALOG_REVIEW_PACKAGES = 5_000
_OPERATIONAL_RULE_PREFIX = "learned.operational."


@dataclass(frozen=True, slots=True)
class RulePromotion:
    rule_id: str
    state: str  # shadow | enforce | retired
    source: str  # handoff | override | manual | coherence
    updated_at: str | None


class Mimir(Agent):
    """Wave-2 Mimir: promotion state + candidate intake."""

    def __init__(
        self,
        *,
        catalog_candidate_compiler: CatalogCandidateCompiler | None = None,
        catalog_review_publisher: CatalogReviewPublisher | None = None,
    ) -> None:
        super().__init__(spec=_MIMIR)
        self._promotions: dict[str, RulePromotion] = {}
        self._pending_candidates: deque[dict[str, Any]] = deque(maxlen=_MAX_PENDING_CANDIDATES)
        self._quarantined_candidates: deque[dict[str, Any]] = deque(maxlen=_MAX_QUARANTINE)
        self._guard = CandidateGuard()
        self._catalog_candidate_compiler = catalog_candidate_compiler
        self._catalog_review_publisher = catalog_review_publisher
        self._catalog_review_packages: BoundedLruDict[str, CatalogReviewPackage] = BoundedLruDict(
            _MAX_CATALOG_REVIEW_PACKAGES
        )
        self._catalog_review_receipts: BoundedLruDict[str, CatalogReviewPublicationReceipt] = (
            BoundedLruDict(_MAX_CATALOG_REVIEW_PACKAGES)
        )

    async def on_typed_message(self, topic: str, payload: dict[str, Any]) -> None:
        if topic == "object.rule-candidate":
            verdict = self._guard.inspect(payload)
            if verdict.accepted:
                await self._accept_candidate(payload)
            else:
                # Quarantine (not drop): the rejected candidate is kept with
                # its reason so the audit trail shows why the discovery loop
                # refused it (grounded-provenance MUST + poisoning defense).
                self._quarantined_candidates.append(
                    {**dict(payload), "quarantine_reason": verdict.reason}
                )

    async def _accept_candidate(self, payload: dict[str, Any]) -> None:
        candidate = dict(payload)
        if candidate.get("source_signal") != "operational_case_fingerprint_cohort":
            self._pending_candidates.append(candidate)
            return
        compiler = self._catalog_candidate_compiler
        if compiler is None:
            self._pending_candidates.append(candidate)
            self.record_behavior("operational_catalog_compiler_unavailable")
            return
        try:
            package = compiler.compile(candidate)
        except CatalogCompilationError as exc:
            self._quarantined_candidates.append(
                {**candidate, "quarantine_reason": f"catalog_compile:{exc.code}"}
            )
            self.record_behavior("operational_catalog_compile_failed")
            return
        self._pending_candidates.append(candidate)
        self._catalog_review_packages.set(package.content_digest, package)
        publisher = self._catalog_review_publisher
        if publisher is not None:
            receipt = await publisher.publish(package)
            if (
                not isinstance(receipt, CatalogReviewPublicationReceipt)
                or receipt.package_digest != package.content_digest
            ):
                raise ValueError("catalog review publication receipt digest conflict")
            self._catalog_review_receipts.set(package.content_digest, receipt)
        self.record_behavior("operational_catalog_review_ready")

    def pending_candidates(self) -> tuple[dict[str, Any], ...]:
        return tuple(self._pending_candidates)

    def quarantined_candidates(self) -> tuple[dict[str, Any], ...]:
        return tuple(self._quarantined_candidates)

    def catalog_review_packages(self) -> tuple[CatalogReviewPackage, ...]:
        return tuple(package for _, package in self._catalog_review_packages.items())

    def catalog_review_publication_receipts(
        self,
    ) -> tuple[CatalogReviewPublicationReceipt, ...]:
        return tuple(receipt for _, receipt in self._catalog_review_receipts.items())

    def promote(
        self,
        rule_id: str,
        *,
        source: str,
        updated_at: str | None = None,
    ) -> RulePromotion:
        operational_targets = {
            str(candidate.get("target_rule_id"))
            for candidate in self._pending_candidates
            if candidate.get("source_signal") == "operational_case_fingerprint_cohort"
        }
        draft_rule_ids = {
            str(package.draft_rule.mapping["id"])
            for _, package in self._catalog_review_packages.items()
        }
        if (
            rule_id.startswith(_OPERATIONAL_RULE_PREFIX)
            or rule_id in operational_targets
            or rule_id in draft_rule_ids
        ):
            raise ValueError(
                "operational candidates require a reviewed catalog PR; "
                "direct runtime promotion is not supported"
            )
        promo = RulePromotion(
            rule_id=rule_id, state="enforce", source=source, updated_at=updated_at
        )
        self._promotions[rule_id] = promo
        self._pending_candidates = deque(
            (
                candidate
                for candidate in self._pending_candidates
                if candidate.get("target_rule_id") != rule_id
            ),
            maxlen=_MAX_PENDING_CANDIDATES,
        )
        return promo

    def revoke(self, rule_id: str, *, updated_at: str | None = None) -> RulePromotion:
        promo = RulePromotion(
            rule_id=rule_id, state="retired", source="manual", updated_at=updated_at
        )
        self._promotions[rule_id] = promo
        return promo

    def status(self, rule_id: str) -> RulePromotion | None:
        return self._promotions.get(rule_id)

    def conversation_evidence_available(self, context: dict[str, Any]) -> bool:
        """Rule answers rest on tracked promotions and the candidate queue."""
        return bool(self._promotions or self._pending_candidates or self._quarantined_candidates)

    async def introspect(self, question: str, context: dict[str, Any]) -> IntrospectionResult:
        facts = {
            **capability_facts(self.spec),
            "tracked_rules": capped_list(sorted(self._promotions)),
            "tracked_rules_count": len(self._promotions),
            "pending_candidates": len(self._pending_candidates),
            "quarantined_candidates": len(self._quarantined_candidates),
            "catalog_review_packages": len(self._catalog_review_packages),
            "catalog_review_publication_receipts": len(self._catalog_review_receipts),
            "policy_history_available": False,
        }
        if "policy history" in question.casefold():
            return IntrospectionResult(
                answer="No governed policy history is bound to this conversational projection.",
                facts=facts,
            )
        rules = mentioned(question, self._promotions)
        if rules:
            promo = self._promotions[rules[0]]
            facts.update(
                {
                    "rule_id": promo.rule_id,
                    "state": promo.state,
                    "source": promo.source,
                    # When the state last changed, so an operator can tell a
                    # fresh promotion from a long-settled one.
                    "updated_at": promo.updated_at,
                }
            )
            answer = f"Rule {promo.rule_id!r} is {promo.state} (source: {promo.source})."
            return IntrospectionResult(answer=answer, facts=facts)
        answer = (
            f"Tracking {len(self._promotions)} rule promotion(s); "
            f"{len(self._pending_candidates)} candidate(s) pending the quality gate."
        )
        return IntrospectionResult(answer=answer, facts=facts)


__all__ = ["Mimir", "RulePromotion"]
