"""Forseti-owned read-only Assurance Twin review of FDAI typed ActionType proposals.

The producer turns one typed proposal and its completed what-if into complete,
exact-revision review evidence. It applies only a reviewed, declared ActionType
effect to a scratch projection of the retained Inventory revision, evaluates the
changed targets with the control loop's immutable T0/OPA generation, and requires an
applying Rule input for every written property. Terraform plans and rendered IaC are
never read. The producer never approves, executes, or promotes.

An intake row is ``reviewed`` only after the Forseti writer confirms the exact review.
When a Rule-generation or Inventory change blocks the writer's fenced commit, the
producer retires the stale evidence request and re-derives while the what-if is
fresh, within a bounded attempt count; otherwise the row settles ``unavailable`` with
the real reason. Every evidence gap is an explicit disposition, never ``clear``.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TypeVar

import psycopg

from fdai.core.assurance_twin.evaluation import AssuranceTwinEvaluationUnavailableError
from fdai.core.assurance_twin.proposal_effects import (
    ProposalReviewUnavailableError,
    ReviewedEffectCatalog,
    derive_predicted_change_set,
    require_assessed_effect,
    require_completed_what_if,
)
from fdai.core.assurance_twin.typed_proposal import canonical_digest
from fdai.delivery.assurance_twin_evidence_source import (
    AssuranceTwinEvidenceClockCapacityError,
    AssuranceTwinEvidenceClockContentionError,
    AssuranceTwinEvidenceExpiredError,
    StateStoreTwinEvidenceRepository,
)
from fdai.delivery.assurance_twin_inventory import (
    AssuranceTwinInventoryChangedError,
    TwinInventoryRevision,
    TwinInventoryUnavailableError,
)
from fdai.delivery.assurance_twin_posture_producer import (
    CompletePostureEvaluator,
    TwinInventorySource,
)
from fdai.delivery.assurance_twin_proposal_intake import (
    StateStoreTypedProposalReviewIntake,
    TypedProposalReviewInput,
)
from fdai.delivery.assurance_twin_review_follow_up import (
    AssuranceTwinReviewFollowUpMixin,
    ProposalReviewPass,
)
from fdai.delivery.assurance_twin_writers import AssuranceTwinPublishRequest, findings_digest

_LOG = logging.getLogger(__name__)
_FRESHNESS_TTL = timedelta(minutes=30)
_FenceResult = TypeVar("_FenceResult")


@dataclass(frozen=True, slots=True)
class RecordedReview:
    """Exact evidence request plus the fences the writer must still hold."""

    request: AssuranceTwinPublishRequest
    inventory_revision: str
    rule_generation_digest: str


@dataclass(frozen=True, slots=True)
class ReviewDerivation:
    """One derivation attempt; neither a record nor a reason means retry later."""

    recorded: RecordedReview | None = None
    reason_code: str | None = None


@dataclass(frozen=True, slots=True)
class _FencedRecord:
    request: AssuranceTwinPublishRequest | None


class AssuranceTwinReviewProducer(AssuranceTwinReviewFollowUpMixin):
    """Record complete typed-proposal review evidence for Forseti's writer."""

    owner = "Forseti"

    def __init__(
        self,
        *,
        inventory: TwinInventorySource,
        evaluator: CompletePostureEvaluator,
        repository: StateStoreTwinEvidenceRepository,
        intake: StateStoreTypedProposalReviewIntake,
        effects: ReviewedEffectCatalog,
        required_scopes: tuple[str, ...],
        max_derivations: int = 3,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not required_scopes or required_scopes != tuple(sorted(set(required_scopes))):
            raise ValueError("Assurance Twin Inventory scopes MUST be non-empty and canonical")
        if max_derivations < 1:
            raise ValueError("Assurance Twin review derivations MUST be positive")
        self._inventory = inventory
        self._evaluator = evaluator
        self._repository = repository
        self._intake = intake
        self._effects = effects
        self._required_scopes = required_scopes
        self._max_derivations = max_derivations
        self._clock = clock or (lambda: datetime.now(UTC))

    async def review_pending(self) -> ProposalReviewPass:
        """Advance one bounded batch of active intake rows by one step each."""

        summary = ProposalReviewPass()
        loaded: list[TwinInventoryRevision | None] = []

        async def current_inventory() -> TwinInventoryRevision | None:
            if not loaded:
                loaded.append(await self._load_inventory())
            return loaded[0]

        for item in await self._intake.active():
            if item.status == "recorded":
                await self._follow_up(item, current_inventory, summary)
                continue
            derivation = await self.review(item)
            if derivation.recorded is not None:
                if await self._intake.mark_recorded(
                    item,
                    request=derivation.recorded.request,
                    inventory_revision=derivation.recorded.inventory_revision,
                    rule_generation_digest=derivation.recorded.rule_generation_digest,
                ):
                    summary.recorded += 1
            elif derivation.reason_code is not None:
                await self._retry_or_settle(item, derivation.reason_code, summary)
        return summary

    async def review(self, item: TypedProposalReviewInput) -> ReviewDerivation:
        """Derive and retain one exact review, or return why it is unavailable."""

        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("Assurance Twin review clock MUST be timezone-aware")
        proposal = item.proposal
        effect = self._effects.effect_for(proposal.action_type, proposal.action_type_version)
        try:
            what_if = require_completed_what_if(proposal, item.what_if, now)
            if effect is None:
                raise ProposalReviewUnavailableError("effect_model_unavailable")
        except ProposalReviewUnavailableError as exc:
            return ReviewDerivation(reason_code=exc.reason_code)
        inventory = await self._load_inventory()
        if inventory is None:
            return ReviewDerivation()
        try:
            change_set = derive_predicted_change_set(
                proposal=proposal,
                what_if=what_if,
                effect=effect,
                projection=inventory.projection,
                inventory_revision=inventory.source_revision,
                now=now,
            )
            evaluation = await self._evaluator.evaluate_assurance_twin_posture(
                projection=change_set.scratch,
                inventory_revision=change_set.change_digest,
            )
            require_assessed_effect(change_set, evaluation.declared_inputs)
        except ProposalReviewUnavailableError as exc:
            return ReviewDerivation(reason_code=exc.reason_code)
        except AssuranceTwinEvaluationUnavailableError:
            return ReviewDerivation(reason_code="rule_evaluation_unavailable")

        source_revision = canonical_digest(
            {
                "inventory_revision": inventory.source_revision,
                "change_digest": change_set.change_digest,
                "rule_set_digest": evaluation.rule_set_digest,
                "rule_generation_digest": evaluation.rule_generation_digest,
                "rule_generation_time": evaluation.rule_generation_time.isoformat(),
                "coverage_refs": list(evaluation.coverage_refs),
                "findings_digest": findings_digest(evaluation.findings),
            }
        )
        fresh_until = min(inventory.completed_at + _FRESHNESS_TTL, what_if.expires_at)
        if now >= fresh_until:
            return ReviewDerivation(reason_code="evidence_expired")

        async def record() -> AssuranceTwinPublishRequest | None:
            try:
                return await self._repository.record_review(
                    review_key=proposal.proposal_ref,
                    change_set=change_set,
                    source_revision=source_revision,
                    findings=evaluation.findings,
                    evaluated_rule_ids=evaluation.evaluated_rule_ids,
                    rule_coverage_refs=evaluation.coverage_refs,
                    rule_set_revision=evaluation.rule_set_digest,
                    rule_generation_revision=evaluation.rule_generation_digest,
                    generated_at=now,
                    fresh_until=fresh_until,
                    correlation_id=item.correlation_id,
                )
            except (
                AssuranceTwinEvidenceClockCapacityError,
                AssuranceTwinEvidenceClockContentionError,
                AssuranceTwinEvidenceExpiredError,
                psycopg.Error,
            ) as exc:
                _LOG.warning(
                    "assurance_twin_review_evidence_write_unavailable",
                    extra={"reason": type(exc).__name__},
                )
                return None

        async def fenced_record() -> _FencedRecord:
            return _FencedRecord(
                await self.run_assurance_twin_inventory_if_current(
                    inventory_revision=inventory.source_revision,
                    operation=record,
                )
            )

        try:
            fenced = await self._evaluator.run_assurance_twin_if_current(
                rule_generation_revision=evaluation.rule_generation_digest,
                operation=fenced_record,
            )
        except AssuranceTwinInventoryChangedError:
            return ReviewDerivation(reason_code="inventory_revision_changed")
        if fenced is None:
            return ReviewDerivation(reason_code="rule_generation_changed")
        if fenced.request is None:
            return ReviewDerivation()
        return ReviewDerivation(
            recorded=RecordedReview(
                request=fenced.request,
                inventory_revision=inventory.source_revision,
                rule_generation_digest=evaluation.rule_generation_digest,
            )
        )

    async def _load_inventory(self) -> TwinInventoryRevision | None:
        try:
            return await self._inventory.load(
                now=self._clock(),
                freshness_ttl=_FRESHNESS_TTL,
                required_scopes=self._required_scopes,
            )
        except (TwinInventoryUnavailableError, psycopg.Error) as exc:
            _LOG.info(
                "assurance_twin_review_inventory_unavailable",
                extra={"reason": type(exc).__name__},
            )
            return None

    async def run_assurance_twin_inventory_if_current(
        self,
        *,
        inventory_revision: str,
        operation: Callable[[], Awaitable[_FenceResult]],
    ) -> _FenceResult | None:
        """Hold the retained Inventory revision through one guarded review write."""

        try:
            return await self._inventory.run_at_revision(
                expected_revision=inventory_revision,
                now=self._clock(),
                freshness_ttl=_FRESHNESS_TTL,
                required_scopes=self._required_scopes,
                operation=operation,
            )
        except AssuranceTwinInventoryChangedError as exc:
            affected_request = (
                exc.result
                if isinstance(exc.result, AssuranceTwinPublishRequest)
                else getattr(exc.result, "request", None)
            )
            if isinstance(affected_request, AssuranceTwinPublishRequest):
                await self._repository.mark_inventory_changed(affected_request)
            raise
        except (TwinInventoryUnavailableError, psycopg.Error) as exc:
            _LOG.info(
                "assurance_twin_review_inventory_revision_unavailable",
                extra={"reason": type(exc).__name__},
            )
            return None

    async def run(self, stop: asyncio.Event, *, interval_seconds: float = 30.0) -> None:
        """Drain the durable intake until ``stop`` is set."""

        if interval_seconds <= 0:
            raise ValueError("Assurance Twin review producer interval MUST be positive")
        while not stop.is_set():
            await self.review_pending()
            try:
                await asyncio.wait_for(stop.wait(), timeout=interval_seconds)
            except TimeoutError:
                pass


__all__ = [
    "AssuranceTwinReviewProducer",
    "ProposalReviewPass",
    "RecordedReview",
    "ReviewDerivation",
]
