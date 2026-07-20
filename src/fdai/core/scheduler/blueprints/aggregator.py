"""Deterministic recurrence aggregation for inert automation blueprints."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta

from fdai.core.scheduler.blueprints.models import (
    AutomationBlueprintCandidate,
    AutomationBlueprintEvidence,
    BlueprintEvidenceSource,
    BlueprintOutcome,
)


@dataclass(frozen=True, slots=True)
class BlueprintAggregationPolicy:
    min_recurrence: int = 3
    candidate_ttl: timedelta = timedelta(days=30)
    proposer: str = "deterministic-recurrence-aggregator"

    def __post_init__(self) -> None:
        if not 2 <= self.min_recurrence <= 100:
            raise ValueError("blueprint min_recurrence MUST be in [2, 100]")
        if not timedelta(hours=1) <= self.candidate_ttl <= timedelta(days=90):
            raise ValueError("blueprint candidate_ttl MUST be in [1 hour, 90 days]")
        if not self.proposer:
            raise ValueError("blueprint proposer MUST be non-empty")


class AutomationBlueprintAggregator:
    """Create one candidate per qualifying normalized recurrence group."""

    def __init__(self, policy: BlueprintAggregationPolicy | None = None) -> None:
        self._policy = policy or BlueprintAggregationPolicy()

    def aggregate(
        self,
        evidence: Iterable[AutomationBlueprintEvidence],
        *,
        now: datetime,
        suppressed_dedup_keys: frozenset[str] = frozenset(),
    ) -> tuple[AutomationBlueprintCandidate, ...]:
        if now.tzinfo is None:
            raise ValueError("blueprint aggregation time MUST include timezone")
        evidence_snapshot = tuple(evidence)
        groups: dict[str, list[AutomationBlueprintEvidence]] = defaultdict(list)
        blocked_by_scheduler = {
            item.dedup_key
            for item in evidence_snapshot
            if item.source is BlueprintEvidenceSource.SCHEDULED_RUN
            and (item.outcome is BlueprintOutcome.FAILED or item.unresolved_failure)
        }
        for item in evidence_snapshot:
            if item.source is not BlueprintEvidenceSource.OPERATOR_TURN:
                continue
            groups[item.dedup_key].append(item)
        candidates: list[AutomationBlueprintCandidate] = []
        for dedup_key in sorted(groups):
            items = groups[dedup_key]
            if (
                dedup_key in suppressed_dedup_keys
                or dedup_key in blocked_by_scheduler
                or not _qualifies(items, min_recurrence=self._policy.min_recurrence)
            ):
                continue
            representative = min(items, key=lambda item: (item.occurred_at, item.evidence_id))
            fingerprints = tuple(sorted({item.fingerprint for item in items}))
            candidates.append(
                AutomationBlueprintCandidate(
                    candidate_id=(
                        "blueprint-"
                        + hashlib.sha256(
                            f"{dedup_key}\0{'|'.join(fingerprints)}".encode()
                        ).hexdigest()[:24]
                    ),
                    dedup_key=dedup_key,
                    normalized_task_intent=representative.normalized_task_intent,
                    schedule_class=representative.schedule_class,
                    schedule_expression=representative.schedule_expression,
                    event_type=representative.event_type,
                    principal_id=representative.principal_id,
                    resource_scope=representative.resource_scope,
                    delivery_intent=representative.delivery_intent,
                    required_tools=tuple(sorted(representative.required_tools)),
                    isolation_profile=representative.isolation_profile,
                    estimated_cost_microusd=max(item.estimated_cost_microusd for item in items),
                    evidence_fingerprints=fingerprints,
                    proposer=self._policy.proposer,
                    confidence=min(0.99, len(fingerprints) / (self._policy.min_recurrence + 1)),
                    created_at=now,
                    expires_at=now + self._policy.candidate_ttl,
                )
            )
        return tuple(candidates)


def _qualifies(
    items: list[AutomationBlueprintEvidence],
    *,
    min_recurrence: int,
) -> bool:
    if len({item.fingerprint for item in items}) < min_recurrence:
        return False
    if any(
        item.outcome is not BlueprintOutcome.SUCCEEDED or item.unresolved_failure for item in items
    ):
        return False
    authority_shapes = {
        (
            item.event_type,
            item.delivery_intent,
            item.schedule_expression,
            tuple(sorted(item.required_tools)),
            item.isolation_profile,
        )
        for item in items
    }
    return len(authority_shapes) == 1


__all__ = ["AutomationBlueprintAggregator", "BlueprintAggregationPolicy"]
