"""Settle recorded Forseti proposal reviews only from the writer's real outcome.

A recorded intake row names one exact evidence request. The row becomes ``reviewed``
only after the Forseti writer confirms that exact review, and ``superseded`` when a
newer review of the same proposal replaced it. When the writer's Rule-generation or
Inventory fence can no longer hold, the stale request is retired so the relay stops
republishing it, and the proposal is re-derived within a bounded attempt count while
its what-if is fresh. Otherwise the row settles ``unavailable`` with the real reason.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from fdai.delivery.assurance_twin_evidence_source import StateStoreTwinEvidenceRepository
from fdai.delivery.assurance_twin_inventory import TwinInventoryRevision
from fdai.delivery.assurance_twin_posture_producer import CompletePostureEvaluator
from fdai.delivery.assurance_twin_proposal_intake import (
    StateStoreTypedProposalReviewIntake,
    TypedProposalReviewInput,
)

_LOG = logging.getLogger(__name__)
_RETRYABLE_REASONS = frozenset(
    {"evidence_expired", "inventory_revision_changed", "rule_generation_changed"}
)


@dataclass(slots=True)
class ProposalReviewPass:
    """Intake transitions made by one bounded producer pass."""

    recorded: int = 0
    reviewed: int = 0
    superseded: int = 0
    retried: int = 0
    unavailable: int = 0


class AssuranceTwinReviewFollowUpMixin:
    """Follow one recorded review until the writer confirms or a terminal gap."""

    _repository: StateStoreTwinEvidenceRepository
    _intake: StateStoreTypedProposalReviewIntake
    _evaluator: CompletePostureEvaluator
    _clock: Callable[[], datetime]
    _max_derivations: int

    async def _follow_up(
        self,
        item: TypedProposalReviewInput,
        current_inventory: Callable[[], Awaitable[TwinInventoryRevision | None]],
        summary: ProposalReviewPass,
    ) -> None:
        """Settle a recorded row from the writer outcome, never from the record alone."""

        request = item.request
        if (
            request is None
            or item.inventory_revision is None
            or item.rule_generation_digest is None
            or await self._repository.review_evidence_state(request) is None
        ):
            await self._retry_or_settle(item, "evidence_missing", summary)
            return
        disposition = await self._repository.writer_disposition(request)
        if disposition in ("published", "superseded"):
            terminal: Literal["reviewed", "superseded"] = (
                "reviewed" if disposition == "published" else "superseded"
            )
            if await self._intake.settle(
                item,
                status=terminal,
                reason_code=None if terminal == "reviewed" else "review_superseded",
            ):
                if terminal == "reviewed":
                    summary.reviewed += 1
                else:
                    summary.superseded += 1
            return
        if disposition == "conflict":
            state = await self._repository.review_evidence_state(request)
            changed = state is not None and state.get("inventory_revision_changed") is True
            conflict_reason = "inventory_revision_changed" if changed else "evidence_conflict"
            await self._retry_or_settle(item, conflict_reason, summary)
            return
        if disposition == "expired":
            await self._retry_or_settle(item, "evidence_expired", summary)
            return
        drift = await self._fence_drift(
            rule_generation_digest=item.rule_generation_digest,
            inventory_revision=item.inventory_revision,
            current_inventory=current_inventory,
        )
        if drift is not None and await self._repository.retire_unconfirmed_request(request):
            await self._retry_or_settle(item, drift, summary)

    async def _fence_drift(
        self,
        *,
        rule_generation_digest: str,
        inventory_revision: str,
        current_inventory: Callable[[], Awaitable[TwinInventoryRevision | None]],
    ) -> str | None:
        """Name the fence that the writer can no longer satisfy, if any."""

        async def current() -> bool:
            return True

        if (
            await self._evaluator.run_assurance_twin_if_current(
                rule_generation_revision=rule_generation_digest,
                operation=current,
            )
            is not True
        ):
            return "rule_generation_changed"
        inventory = await current_inventory()
        if inventory is not None and inventory.source_revision != inventory_revision:
            return "inventory_revision_changed"
        return None

    async def _retry_or_settle(
        self,
        item: TypedProposalReviewInput,
        reason_code: str,
        summary: ProposalReviewPass,
    ) -> None:
        """Re-derive a fenced proposal while its what-if is fresh, within the bound."""

        what_if = item.what_if
        fresh = what_if is not None and what_if.expires_at > self._clock()
        _LOG.info("assurance_twin_proposal_review_unsettled", extra={"reason": reason_code})
        if reason_code in _RETRYABLE_REASONS and fresh:
            exhausted = item.attempts + 1 >= self._max_derivations
            if await self._intake.retry(
                item,
                reason_code=reason_code,
                max_attempts=self._max_derivations,
            ):
                if exhausted:
                    summary.unavailable += 1
                else:
                    summary.retried += 1
            return
        if await self._intake.settle(item, status="unavailable", reason_code=reason_code):
            summary.unavailable += 1


__all__ = ["AssuranceTwinReviewFollowUpMixin", "ProposalReviewPass"]
