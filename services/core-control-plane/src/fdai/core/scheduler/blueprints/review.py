"""Review, audit, metrics, and scheduler materialization for blueprint candidates."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import TYPE_CHECKING, Any, Protocol

from fdai.core.conversation.session import Principal
from fdai.core.scheduler.blueprints.models import (
    AutomationBlueprintCandidate,
    AutomationBlueprintState,
)
from fdai.core.scheduler.blueprints.store import AutomationBlueprintStore

if TYPE_CHECKING:
    from fdai.core.conversation.creation import CreateScheduledTaskCommand


class AutomationBlueprintReviewAuthorizer(Protocol):
    def can_review(self, principal: Principal) -> bool: ...


class AutomationBlueprintAudit(Protocol):
    async def append(self, event: Mapping[str, Any]) -> None: ...


@dataclass(slots=True)
class AutomationBlueprintMetrics:
    proposed: int = 0
    accepted: int = 0
    rejected: int = 0
    expired: int = 0
    materialized: int = 0
    realized_usage: int = 0
    rejection_reasons: Counter[str] = field(default_factory=Counter)

    def snapshot(self) -> dict[str, object]:
        reviewed = self.accepted + self.rejected
        return {
            "proposed": self.proposed,
            "accepted": self.accepted,
            "rejected": self.rejected,
            "expired": self.expired,
            "materialized": self.materialized,
            "realized_usage": self.realized_usage,
            "candidate_precision": self.accepted / reviewed if reviewed else 0.0,
            "acceptance_rate": self.accepted / reviewed if reviewed else 0.0,
            "rejection_reasons": dict(sorted(self.rejection_reasons.items())),
        }


class AutomationBlueprintReviewService:
    def __init__(
        self,
        *,
        store: AutomationBlueprintStore,
        authorizer: AutomationBlueprintReviewAuthorizer,
        audit: AutomationBlueprintAudit,
        schedule_command: CreateScheduledTaskCommand,
        metrics: AutomationBlueprintMetrics | None = None,
    ) -> None:
        self._store = store
        self._authorizer = authorizer
        self._audit = audit
        self._schedule_command = schedule_command
        self.metrics = metrics or AutomationBlueprintMetrics()

    async def submit(self, candidate: AutomationBlueprintCandidate) -> AutomationBlueprintCandidate:
        existing_ids = {item.candidate_id for item in await self._store.list_all()}
        stored = await self._store.create(candidate)
        if stored.candidate_id not in existing_ids:
            self.metrics.proposed += 1
            await self._audit.append(_event("automation_blueprint.proposed", stored))
        return stored

    async def review(
        self,
        candidate_id: str,
        *,
        principal: Principal,
        approve: bool,
        reason: str,
        at: datetime,
    ) -> AutomationBlueprintCandidate:
        if not self._authorizer.can_review(principal):
            raise PermissionError("principal is not authorized to review automation blueprints")
        if not reason.strip():
            raise ValueError("automation blueprint review reason MUST be non-empty")
        current = await self._store.get(candidate_id)
        if current.proposer == principal.id:
            raise PermissionError("automation blueprint proposer cannot self-review")
        if current.expires_at <= at:
            raise ValueError("automation blueprint candidate has expired")
        if current.state is not AutomationBlueprintState.DRAFT:
            raise ValueError("only a draft automation blueprint can be reviewed")
        state = AutomationBlueprintState.ACCEPTED if approve else AutomationBlueprintState.REJECTED
        reviewed = await self._store.transition(
            replace(
                current,
                state=state,
                reviewed_by=principal.id,
                review_reason=reason.strip(),
            ),
            expected_state=AutomationBlueprintState.DRAFT,
        )
        if reviewed is None:
            raise ValueError("automation blueprint changed before review")
        if approve:
            self.metrics.accepted += 1
        else:
            self.metrics.rejected += 1
            self.metrics.rejection_reasons[reason.strip()] += 1
        await self._audit.append(_event(f"automation_blueprint.{state.value}", reviewed))
        return reviewed

    async def materialize(
        self,
        candidate_id: str,
        *,
        principal: Principal,
        at: datetime,
    ) -> AutomationBlueprintCandidate:
        current = await self._store.get(candidate_id)
        if current.state is AutomationBlueprintState.MATERIALIZED:
            return current
        if current.state is not AutomationBlueprintState.ACCEPTED:
            raise ValueError("only an accepted automation blueprint can be materialized")
        if current.reviewed_by != principal.id:
            raise PermissionError("reviewing principal MUST materialize the accepted blueprint")
        task = await self._schedule_command.create(
            principal=principal,
            name=current.normalized_task_intent,
            interval_seconds=_interval_seconds(current.schedule_class),
            event_type=current.event_type,
            resource_ref=current.resource_scope,
            event_payload={
                "automation_blueprint_id": current.candidate_id,
                "delivery_intent": current.delivery_intent,
                "shadow_only": True,
            },
            task_id=f"task-{current.candidate_id}",
            cron_expression=(
                current.schedule_expression if current.schedule_class == "cron" else None
            ),
            isolation_profile=current.isolation_profile,
        )
        materialized = await self._store.transition(
            replace(
                current,
                state=AutomationBlueprintState.MATERIALIZED,
                resulting_task_id=task.task_id,
            ),
            expected_state=AutomationBlueprintState.ACCEPTED,
        )
        if materialized is None:
            raise ValueError("automation blueprint changed before materialization")
        self.metrics.materialized += 1
        await self._audit.append(_event("automation_blueprint.materialized", materialized))
        return materialized

    async def expire(self, *, now: datetime) -> int:
        count = await self._store.expire(now=now)
        self.metrics.expired += count
        return count

    async def record_realized_usage(self, candidate_id: str) -> AutomationBlueprintCandidate:
        current = await self._store.get(candidate_id)
        if current.state is not AutomationBlueprintState.MATERIALIZED:
            raise ValueError("realized usage requires a materialized automation blueprint")
        updated = await self._store.transition(
            replace(current, realized_usage_count=current.realized_usage_count + 1),
            expected_state=AutomationBlueprintState.MATERIALIZED,
        )
        if updated is None:
            raise ValueError("automation blueprint changed before usage update")
        self.metrics.realized_usage += 1
        await self._audit.append(_event("automation_blueprint.used", updated))
        return updated


def _interval_seconds(schedule_class: str) -> float:
    values = {"hourly": 3_600.0, "daily": 86_400.0, "weekly": 604_800.0}
    if schedule_class == "cron":
        return 60.0
    try:
        return values[schedule_class]
    except KeyError as exc:
        raise ValueError("unsupported automation blueprint schedule class") from exc


def _event(kind: str, candidate: AutomationBlueprintCandidate) -> dict[str, object]:
    return {
        "action_kind": kind,
        "candidate_id": candidate.candidate_id,
        "dedup_key": candidate.dedup_key,
        "state": candidate.state.value,
        "principal_id": candidate.principal_id,
        "resource_scope": candidate.resource_scope,
        "evidence_fingerprints": list(candidate.evidence_fingerprints),
        "reviewed_by": candidate.reviewed_by,
        "review_reason": candidate.review_reason,
        "resulting_task_id": candidate.resulting_task_id,
    }


__all__ = [
    "AutomationBlueprintAudit",
    "AutomationBlueprintMetrics",
    "AutomationBlueprintReviewAuthorizer",
    "AutomationBlueprintReviewService",
]
