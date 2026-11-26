"""Bounded maintenance contracts for Mimir governance work."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class MimirCatalogPromotionOutcome:
    """Reviewed catalog outcome that can start Saga issue-close evidence."""

    problem_fingerprint: str
    promotion_pr: str
    correlation_id: str
    outcome: str
    rule_id: str
    promoted_at: datetime
    candidate_digest: str | None = None
    package_digest: str | None = None
    review_ref: str | None = None


@dataclass(frozen=True, slots=True)
class MimirRegressionResult:
    """Read-only regression result bound to one promoted fingerprint."""

    passed: bool
    started_at: datetime
    completed_at: datetime
    evidence_ref: str


@dataclass(frozen=True, slots=True)
class MimirRuleSourcePollResult:
    """Bounded rule-source polling summary."""

    checked: int
    changed: int
    evidence_ref: str


@dataclass(frozen=True, slots=True)
class MimirDeprecationCandidate:
    """Audit-only stale or retired rule evidence."""

    rule_id: str
    reason: str
    evidence_ref: str
    observed_at: datetime


class MimirCatalogPromotionOutcomeReader(Protocol):
    """Read-only reviewed catalog outcomes."""

    async def read_promotion_outcomes(
        self,
        *,
        limit: int,
        now: datetime,
    ) -> Sequence[MimirCatalogPromotionOutcome]: ...


class MimirRegressionRunner(Protocol):
    """Read-only regression suite runner."""

    async def run_regression(
        self,
        outcome: MimirCatalogPromotionOutcome,
        *,
        now: datetime,
    ) -> MimirRegressionResult: ...


class MimirRuleSourcePoller(Protocol):
    """Read-only rule source poller."""

    async def poll_rule_sources(
        self,
        *,
        limit: int,
        now: datetime,
    ) -> MimirRuleSourcePollResult: ...


class MimirRuleDeprecationReader(Protocol):
    """Read-only stale-rule and retirement evidence reader."""

    async def stale_or_retired_rules(
        self,
        *,
        limit: int,
        now: datetime,
    ) -> Sequence[MimirDeprecationCandidate]: ...


def promotion_outcome_is_authoritative(outcome: MimirCatalogPromotionOutcome) -> bool:
    """Validate the minimum evidence Mimir can forward to Saga."""

    return (
        bool(outcome.problem_fingerprint)
        and bool(outcome.promotion_pr)
        and bool(outcome.correlation_id)
        and outcome.outcome.strip().lower() in {"promoted", "promotion_succeeded"}
        and bool(outcome.rule_id)
        and outcome.promoted_at.tzinfo is not None
    )


def regression_result_is_clean(result: MimirRegressionResult) -> bool:
    """Return whether regression evidence can start Saga's clean window."""

    return (
        result.passed
        and result.started_at.tzinfo is not None
        and result.completed_at.tzinfo is not None
        and result.started_at <= result.completed_at
        and bool(result.evidence_ref)
    )


def norns_issue_close_support(payload: Mapping[str, Any]) -> dict[str, Any] | None:
    """Extract Norns' inert issue-close support from a RuleCandidate."""

    if (
        payload.get("producer_principal") != "Norns"
        or payload.get("kind") != "issue_close_eligibility_signal"
    ):
        return None
    raw = payload.get("closure_eligibility")
    if not isinstance(raw, Mapping):
        return None
    fingerprint = str(raw.get("fingerprint") or payload.get("fingerprint") or "")
    if not fingerprint:
        return None
    return {
        "fingerprint": fingerprint,
        "occurrence_count": raw.get("occurrence_count"),
        "idempotency_key": str(payload.get("idempotency_key") or ""),
        "correlation_id": str(payload.get("correlation_id") or ""),
        "inert": True,
        "grants_issue_authority": False,
    }
