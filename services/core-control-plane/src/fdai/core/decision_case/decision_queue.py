"""Read-only Operator Decision Queue projection ranked by cost-of-delay signal.

Combines a :class:`~fdai.core.decision_case.models.DecisionCase` and its
:class:`~fdai.core.decision_case.models.DecisionSelection` with ontology decision
signals (``decision.blast_radius``, ``decision.change_risk``, and the ungated
``decision.cost_of_delay`` ranking signal) plus the required human-approval control
metadata into one read-only queue view. ``decision.cost_of_delay`` orders items
without opening or closing any gate, and the projection carries no mutation,
approval, or execution authority.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from math import isfinite
from typing import Final, Literal

from fdai_service_contracts.ontology_query import content_digest

from fdai.core.decision_case.models import DecisionCase, DecisionSelection, ObjectiveEffect

_VALID_TIERS: Final = frozenset({"low", "medium", "high", "critical", "unknown"})
_TIER_SEVERITY: Final = {"critical": 4, "high": 3, "medium": 2, "low": 1, "unknown": 0}
_APPROVAL_STATUSES: Final = frozenset({"pending", "approved", "rejected", "expired"})


@dataclass(frozen=True, slots=True)
class DecisionQueueApprovalControl:
    """Read-only summary of the approval control governing one queued decision."""

    requires_human_approval: bool
    required_role: str
    quorum: int
    no_self_approval: bool
    approval_status: str = "pending"

    def __post_init__(self) -> None:
        if not self.required_role.strip():
            raise ValueError("DecisionQueueApprovalControl.required_role MUST be non-empty")
        if isinstance(self.quorum, bool) or self.quorum < 1:
            raise ValueError("DecisionQueueApprovalControl.quorum MUST be >= 1")
        if self.approval_status not in _APPROVAL_STATUSES:
            raise ValueError(f"Unsupported approval_status: {self.approval_status!r}")


@dataclass(frozen=True, slots=True)
class DecisionQueueItem:
    """One read-only decision card showing recommendation, evidence, uncertainty, and cost rank."""

    case_id: str
    process_id: str | None
    target_resource_ref: str
    recommended_option_id: str | None
    recommended_action_type: str | None
    expected_effects: tuple[ObjectiveEffect, ...]
    uncertainty: float
    blast_radius_tier: str
    change_risk_tier: str
    cost_of_delay_amount: Decimal | None
    cost_of_delay_currency: str | None
    evidence_refs: tuple[str, ...]
    approval_control: DecisionQueueApprovalControl
    created_at: datetime
    read_only: Literal[True] = True
    execution_authority: Literal[False] = False

    def __post_init__(self) -> None:
        if not self.case_id.strip() or not self.target_resource_ref.strip():
            raise ValueError("DecisionQueueItem case_id and target_resource_ref MUST be non-empty")
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("DecisionQueueItem.created_at MUST be timezone-aware")
        if not isfinite(self.uncertainty) or not 0.0 <= self.uncertainty <= 1.0:
            raise ValueError("DecisionQueueItem.uncertainty MUST be in [0.0, 1.0]")
        if self.blast_radius_tier not in _VALID_TIERS or self.change_risk_tier not in _VALID_TIERS:
            raise ValueError("DecisionQueueItem tiers MUST be valid decision tiers")
        if (self.cost_of_delay_amount is None) != (self.cost_of_delay_currency is None):
            raise ValueError("cost_of_delay_amount and cost_of_delay_currency MUST be set together")
        if self.cost_of_delay_amount is not None and (
            not self.cost_of_delay_amount.is_finite() or self.cost_of_delay_amount < Decimal(0)
        ):
            raise ValueError("cost_of_delay_amount MUST be a finite non-negative Decimal")
        if not self.evidence_refs or len(self.evidence_refs) != len(set(self.evidence_refs)):
            raise ValueError("DecisionQueueItem.evidence_refs MUST be non-empty and unique")
        if self.read_only is not True or self.execution_authority is not False:
            raise ValueError("DecisionQueueItem MUST remain read-only with no execution authority")


@dataclass(frozen=True, slots=True)
class DecisionQueueProjection:
    """Replay-stable, read-only Operator Decision Queue."""

    items: tuple[DecisionQueueItem, ...]
    ranking_currency: str | None
    as_of: datetime
    projection_digest: str
    read_only: Literal[True] = True
    execution_authority: Literal[False] = False

    def __post_init__(self) -> None:
        if self.as_of.tzinfo is None or self.as_of.utcoffset() is None:
            raise ValueError("DecisionQueueProjection.as_of MUST be timezone-aware")
        if self.read_only is not True or self.execution_authority is not False:
            raise ValueError("DecisionQueueProjection MUST remain read-only with no authority")


def build_decision_queue_item(
    *,
    case: DecisionCase,
    selection: DecisionSelection,
    target_resource_ref: str,
    approval_control: DecisionQueueApprovalControl,
    blast_radius_tier: str = "unknown",
    change_risk_tier: str = "unknown",
    cost_of_delay_reading: dict[str, object] | None = None,
    envelope_uncertainty: float | None = None,
) -> DecisionQueueItem:
    """Compose one read-only queue item from a DecisionCase and ontology readings."""

    selected = next(
        (opt for opt in case.options if opt.option_id == selection.selected_option_id),
        None,
    )
    effects = selected.effects if selected is not None else case.no_action_effects
    effect_uncertainty = max((1.0 - eff.confidence for eff in effects), default=1.0)
    uncertainty = (
        max(effect_uncertainty, envelope_uncertainty)
        if envelope_uncertainty is not None
        else effect_uncertainty
    )
    amount: Decimal | None = None
    currency: str | None = None
    if cost_of_delay_reading is not None and cost_of_delay_reading.get("complete") is True:
        raw_amount = cost_of_delay_reading.get("total_amount")
        raw_currency = cost_of_delay_reading.get("currency")
        if isinstance(raw_amount, str) and isinstance(raw_currency, str) and raw_currency.strip():
            amount = Decimal(raw_amount)
            currency = raw_currency.strip()
    refs = tuple(
        dict.fromkeys(
            (*case.evidence_refs, *(selected.evidence_refs if selected is not None else ()))
        )
    )
    return DecisionQueueItem(
        case_id=case.case_id,
        process_id=case.process_id,
        target_resource_ref=target_resource_ref,
        recommended_option_id=selection.selected_option_id,
        recommended_action_type=selected.action_type if selected is not None else None,
        expected_effects=effects,
        uncertainty=round(min(max(uncertainty, 0.0), 1.0), 6),
        blast_radius_tier=blast_radius_tier,
        change_risk_tier=change_risk_tier,
        cost_of_delay_amount=amount,
        cost_of_delay_currency=currency,
        evidence_refs=refs,
        approval_control=approval_control,
        created_at=case.created_at,
    )


def build_decision_queue_projection(
    items: tuple[DecisionQueueItem, ...],
    *,
    as_of: datetime,
    ranking_currency: str | None = None,
) -> DecisionQueueProjection:
    """Order queue items by cost-of-delay ranking signal, then blast radius, then age."""

    if len({item.case_id for item in items}) != len(items):
        raise ValueError("DecisionQueueProjection case_ids MUST be unique")
    currencies = {
        item.cost_of_delay_currency for item in items if item.cost_of_delay_currency is not None
    }
    effective_currency = ranking_currency or (
        next(iter(currencies)) if len(currencies) == 1 else None
    )

    def _sort_key(item: DecisionQueueItem) -> tuple[object, ...]:
        priced = (
            effective_currency is not None
            and item.cost_of_delay_currency == effective_currency
            and item.cost_of_delay_amount is not None
        )
        neg_cost = -(item.cost_of_delay_amount or Decimal(0)) if priced else Decimal(0)
        return (
            0 if priced else 1,
            neg_cost,
            -_TIER_SEVERITY.get(item.blast_radius_tier, 0),
            item.created_at.astimezone(UTC),
            item.case_id,
        )

    ordered = tuple(sorted(items, key=_sort_key))
    digest = content_digest(
        {
            "as_of": as_of.astimezone(UTC).isoformat(),
            "ranking_currency": effective_currency,
            "items": [
                {
                    "case_id": item.case_id,
                    "target_resource_ref": item.target_resource_ref,
                    "recommended_option_id": item.recommended_option_id,
                    "recommended_action_type": item.recommended_action_type,
                    "uncertainty": item.uncertainty,
                    "blast_radius_tier": item.blast_radius_tier,
                    "change_risk_tier": item.change_risk_tier,
                    "cost_of_delay_amount": (
                        None
                        if item.cost_of_delay_amount is None
                        else str(item.cost_of_delay_amount)
                    ),
                    "cost_of_delay_currency": item.cost_of_delay_currency,
                    "approval_status": item.approval_control.approval_status,
                    "evidence_refs": list(item.evidence_refs),
                }
                for item in ordered
            ],
        }
    )
    return DecisionQueueProjection(
        items=ordered,
        ranking_currency=effective_currency,
        as_of=as_of,
        projection_digest=digest,
    )


__all__ = [
    "DecisionQueueApprovalControl",
    "DecisionQueueItem",
    "DecisionQueueProjection",
    "build_decision_queue_item",
    "build_decision_queue_projection",
]
