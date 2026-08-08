"""Rule promotion controller - write the audit trail for promote/rollback.

Phase 2 continuous-update pipeline stage 5 (see
[`docs/roadmap/phases/phase-2-quality-and-t1.md § Promote | rollback`]).

Contract
--------

Given a :class:`RegressionDecision`, the controller writes an audit
entry describing the outcome and - on **PASS** - records the promoted
rule set as the new baseline. On **FAIL**, it writes a rollback audit
entry and leaves the last-good baseline in place.

The controller does NOT open a catalog-as-code PR by itself; that is
the pipeline orchestrator's job. Splitting the responsibility keeps
the audit path (this module) independent of the delivery adapter (a
GitHub REST client), so a fork can wire either without touching the
other.

Shadow-first invariant
----------------------

Every promoted rule set is still delivered in **shadow mode** at the
executor layer - enforcement requires a separate per-action promotion
gate (see P2-D). This controller only moves the *catalog* from
"candidate" to "baseline"; ActionType-level enforcement stays untouched.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from fdai.rule_catalog.pipeline.regression_gate import (
    RegressionDecision,
    RegressionOutcome,
)
from fdai.shared.contracts.models import Mode
from fdai.shared.providers.state_store import StateStore


class PromotionOutcome(StrEnum):
    """Terminal outcome for one :meth:`RulePromotionController.apply` call."""

    PROMOTED = "promoted"
    ROLLED_BACK = "rolled_back"


@dataclass(frozen=True, slots=True)
class PromotionRecord:
    """Frozen record for one promotion decision.

    Audit-log consumers persist :attr:`audit_entry`; the fields on this
    record double as an in-process handle so a caller can chain another
    stage (e.g. open a catalog-as-code PR) without re-reading the store.
    """

    outcome: PromotionOutcome
    scenario_set_id: str
    promoted_rule_ids: tuple[str, ...]
    """Rule ids of the set that is now the baseline (== candidate on
    :attr:`PromotionOutcome.PROMOTED`; unchanged from the prior baseline
    on :attr:`PromotionOutcome.ROLLED_BACK`)."""

    reasons: tuple[str, ...] = field(default_factory=tuple)
    """Copy of :attr:`RegressionDecision.reasons` for the audit trail."""

    recorded_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class BaselineState:
    """In-process baseline pointer - updated on every PROMOTED outcome.

    Kept as a returned value rather than a mutable service so tests can
    assert on the immutability of previous baselines.
    """

    scenario_set_id: str
    rule_ids: tuple[str, ...]
    promoted_at: datetime


class RulePromotionController:
    """Turn a :class:`RegressionDecision` into an auditable promotion event."""

    def __init__(self, *, audit_store: StateStore) -> None:
        self._audit_store = audit_store

    async def apply(
        self,
        *,
        decision: RegressionDecision,
        previous_baseline: BaselineState | None = None,
    ) -> tuple[PromotionRecord, BaselineState | None]:
        """Record the outcome and return the next-state baseline pointer.

        Returns a tuple of ``(record, baseline)``:

        - ``record`` - always present, describes what was audited.
        - ``baseline`` - the new baseline on PROMOTED, the previous
          baseline (unchanged) on ROLLED_BACK, or ``None`` when there is
          no baseline yet.
        """
        now = datetime.now(tz=UTC)

        if decision.outcome is RegressionOutcome.PASS:
            new_baseline = BaselineState(
                scenario_set_id=decision.scenario_set_id,
                rule_ids=decision.candidate_rule_ids,
                promoted_at=now,
            )
            record = PromotionRecord(
                outcome=PromotionOutcome.PROMOTED,
                scenario_set_id=decision.scenario_set_id,
                promoted_rule_ids=decision.candidate_rule_ids,
                reasons=(),
                recorded_at=now,
            )
            await self._audit(record=record, decision=decision, now=now)
            return record, new_baseline

        # FAIL - preserve the prior baseline (may be None on first run).
        record = PromotionRecord(
            outcome=PromotionOutcome.ROLLED_BACK,
            scenario_set_id=decision.scenario_set_id,
            promoted_rule_ids=(previous_baseline.rule_ids if previous_baseline else ()),
            reasons=decision.reasons,
            recorded_at=now,
        )
        await self._audit(record=record, decision=decision, now=now)
        return record, previous_baseline

    async def _audit(
        self,
        *,
        record: PromotionRecord,
        decision: RegressionDecision,
        now: datetime,
    ) -> None:
        entry: dict[str, Any] = {
            "actor": "fdai.rule_catalog.pipeline.promotion",
            "action_kind": "rule_catalog.promotion",
            "mode": Mode.SHADOW.value,
            "outcome": record.outcome.value,
            "scenario_set_id": record.scenario_set_id,
            "candidate_rule_ids": list(decision.candidate_rule_ids),
            "promoted_rule_ids": list(record.promoted_rule_ids),
            "baseline_coverage": decision.baseline_coverage,
            "candidate_coverage": decision.candidate_coverage,
            "policy_violation_escapes": decision.policy_violation_escapes,
            "missing_expected_rules": decision.missing_expected_rules,
            "reasons": list(record.reasons),
            "recorded_at": now.isoformat(),
        }
        await self._audit_store.append_audit_entry(entry)


__all__ = [
    "BaselineState",
    "PromotionOutcome",
    "PromotionRecord",
    "RulePromotionController",
]
