"""Composition helpers for inert automation-blueprint review and suggestions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from fdai.core.conversation.creation import CreateScheduledTaskCommand
from fdai.core.scheduler.blueprints.aggregator import AutomationBlueprintAggregator
from fdai.core.scheduler.blueprints.proposals import (
    AutomationBlueprintProposalProcessor,
    ProposalRolePrincipalResolver,
)
from fdai.core.scheduler.blueprints.review import (
    AutomationBlueprintReviewService,
)
from fdai.core.scheduler.blueprints.suggestion import AutomationBlueprintSuggestionService
from fdai.delivery.persistence.postgres_automation_blueprint import (
    PostgresAutomationBlueprintStore,
    PostgresAutomationBlueprintStoreConfig,
)
from fdai.delivery.persistence.postgres_automation_blueprint_audit import (
    PostgresAutomationBlueprintAudit,
    PostgresAutomationBlueprintAuditConfig,
)
from fdai.delivery.persistence.postgres_automation_blueprint_evidence import (
    PostgresAutomationBlueprintEvidenceFeed,
    PostgresAutomationBlueprintEvidenceFeedConfig,
)
from fdai.delivery.persistence.postgres_automation_blueprint_proposals import (
    PostgresAutomationBlueprintProposalQueue,
    PostgresAutomationBlueprintProposalQueueConfig,
)
from fdai.delivery.persistence.postgres_scheduler_store import (
    PostgresScheduleStore,
    PostgresScheduleStoreConfig,
)


class ApproverAutomationBlueprintAuthorizer:
    """Authorize only approver-or-owner Core principals for review decisions."""

    def can_review(self, principal: object) -> bool:
        role = getattr(getattr(principal, "role", None), "value", "")
        return role in {"approver", "owner"}


@dataclass(frozen=True, slots=True)
class AutomationBlueprintBinding:
    review: AutomationBlueprintReviewService
    suggestion: AutomationBlueprintSuggestionService
    proposals: PostgresAutomationBlueprintProposalQueue
    processor: AutomationBlueprintProposalProcessor

    async def run_once(self, *, now: datetime | None = None) -> dict[str, int]:
        observed_at = now or datetime.now(UTC)
        proposed = len(await self.suggestion.suggest(now=observed_at))
        applied = 0
        rejected = 0
        while True:
            claim = await self.proposals.claim()
            if claim is None:
                break
            try:
                await self.processor.apply(claim.proposal, at=observed_at)
            except (PermissionError, ValueError, KeyError) as exc:
                if await self.proposals.mark_rejected(
                    key=claim.key,
                    claim_id=claim.claim_id,
                    reason_code=type(exc).__name__,
                ):
                    rejected += 1
            except Exception:
                await self.proposals.release(key=claim.key, claim_id=claim.claim_id)
                raise
            else:
                if await self.proposals.mark_applied(key=claim.key, claim_id=claim.claim_id):
                    applied += 1
        return {"proposed": proposed, "applied": applied, "rejected": rejected}


def build_postgres_automation_blueprint_binding(*, dsn: str) -> AutomationBlueprintBinding:
    """Bind PostgreSQL evidence, candidates, audit, proposals, and scheduler command."""

    candidate_store = PostgresAutomationBlueprintStore(
        config=PostgresAutomationBlueprintStoreConfig(dsn=dsn)
    )
    schedule_store = PostgresScheduleStore(config=PostgresScheduleStoreConfig(dsn=dsn))
    review = AutomationBlueprintReviewService(
        store=candidate_store,
        authorizer=ApproverAutomationBlueprintAuthorizer(),
        audit=PostgresAutomationBlueprintAudit(PostgresAutomationBlueprintAuditConfig(dsn=dsn)),
        schedule_command=CreateScheduledTaskCommand(store=schedule_store),
    )
    suggestion = AutomationBlueprintSuggestionService(
        feed=PostgresAutomationBlueprintEvidenceFeed(
            PostgresAutomationBlueprintEvidenceFeedConfig(dsn=dsn)
        ),
        aggregator=AutomationBlueprintAggregator(),
        review=review,
    )
    return AutomationBlueprintBinding(
        review=review,
        suggestion=suggestion,
        proposals=PostgresAutomationBlueprintProposalQueue(
            PostgresAutomationBlueprintProposalQueueConfig(dsn=dsn)
        ),
        processor=AutomationBlueprintProposalProcessor(
            review=review,
            principal_resolver=ProposalRolePrincipalResolver(),
        ),
    )


__all__ = [
    "ApproverAutomationBlueprintAuthorizer",
    "AutomationBlueprintBinding",
    "build_postgres_automation_blueprint_binding",
]
