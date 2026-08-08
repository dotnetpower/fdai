"""Generate grounded briefings and run opening or scheduled triggers."""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from croniter import croniter

from fdai.core.report_feed import ReportFeed
from fdai.core.scheduler.continuation import ScheduledContinuationService
from fdai.shared.contracts.models import Severity
from fdai.shared.providers.briefing import (
    BriefingKind,
    BriefingRun,
    BriefingRunStatus,
    BriefingRunStore,
    BriefingSpec,
    BriefingSubscription,
    BriefingSubscriptionStore,
    ConversationPolicyKind,
    ConversationPolicyStore,
)
from fdai.shared.providers.scheduled_continuation import (
    ContinuationMode,
    ScheduledContinuationDelivery,
    ScheduledConversationAnchor,
    anchor_id_for_run,
)

_SEVERITY_FLOOR: dict[str, int] = {"low": 0, "medium": 1, "high": 2, "critical": 3}
_SEVERITY_VALUE: dict[Severity, int] = {
    Severity.LOW: 0,
    Severity.MEDIUM: 1,
    Severity.HIGH: 2,
    Severity.CRITICAL: 3,
}
_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class BriefingContent:
    title: str
    body_markdown: str
    item_count: int
    evidence_refs: tuple[str, ...]
    source_errors: tuple[str, ...]


class BriefingCoordinator:
    """Collect and render a bounded report-feed window without model judgment."""

    def __init__(self, *, report_feed: ReportFeed) -> None:
        self._feed = report_feed

    async def generate(self, *, spec: BriefingSpec, now: datetime) -> BriefingContent:
        since = now.fromtimestamp(now.timestamp() - spec.lookback_seconds, tz=now.tzinfo)
        result = await self._feed.collect(since=since, until=now)
        floor = _SEVERITY_FLOOR[spec.minimum_severity]
        signals = [
            signal
            for signal in result.signals
            if _SEVERITY_VALUE[signal.severity] >= floor
            and (not spec.categories or signal.category.value in spec.categories)
        ][: spec.max_items]
        errors = tuple(f"{source}:{error}" for source, error in result.source_errors)
        title = (
            "Major operational issues"
            if spec.kind is BriefingKind.MAJOR_ISSUES
            else "Operations digest"
        )
        if signals:
            lines = [
                f"- **{_safe(signal.title, 160)}** "
                f"({signal.severity.value}, {signal.occurred_at.isoformat()}): "
                f"{_safe(signal.detail, 320)}"
                for signal in signals
            ]
        elif errors:
            lines = ["Evidence is unavailable from one or more briefing sources."]
        else:
            lines = [
                f"No {spec.minimum_severity} or higher issues were recorded in the selected window."
            ]
        evidence = tuple(dict.fromkeys(ref for signal in signals for ref in signal.evidence_refs))
        return BriefingContent(
            title=title,
            body_markdown="\n".join(lines),
            item_count=len(signals),
            evidence_refs=evidence,
            source_errors=errors,
        )


class OpeningBriefingService:
    """Return one persisted opening briefing per conversation and policy revision."""

    def __init__(
        self,
        *,
        policies: ConversationPolicyStore,
        runs: BriefingRunStore,
        coordinator: BriefingCoordinator,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._policies = policies
        self._runs = runs
        self._coordinator = coordinator
        self._clock = clock or (lambda: datetime.now(tz=UTC))

    async def open(self, *, principal_id: str, conversation_id: str) -> BriefingRun | None:
        policies = await self._policies.list_for_principal(principal_id=principal_id)
        policy = next(
            (
                item
                for item in policies
                if item.enabled
                and item.kind is ConversationPolicyKind.OPENING_BRIEFING
                and item.briefing_spec is not None
            ),
            None,
        )
        if policy is None or policy.briefing_spec is None:
            return None
        idempotency_key = (
            f"opening-briefing:{principal_id}:{conversation_id}:"
            f"{policy.policy_id}@{policy.revision}"
        )
        prior = await self._runs.list_for_principal(principal_id=principal_id, limit=1000)
        existing = next((run for run in prior if run.idempotency_key == idempotency_key), None)
        if existing is not None:
            return existing
        now = self._clock()
        content = await self._coordinator.generate(spec=policy.briefing_spec, now=now)
        run = _run(
            principal_id=principal_id,
            conversation_id=conversation_id,
            subscription=None,
            scheduled_for=now,
            started_at=now,
            idempotency_key=idempotency_key,
            content=content,
        )
        return await self._runs.create(run)


class BriefingSchedulerService:
    """Claim due subscriptions, generate one run, and advance each schedule."""

    def __init__(
        self,
        *,
        subscriptions: BriefingSubscriptionStore,
        runs: BriefingRunStore,
        coordinator: BriefingCoordinator,
        worker_id: str,
        continuations: ScheduledContinuationService | None = None,
        continuation_delivery: ScheduledContinuationDelivery | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._subscriptions = subscriptions
        self._runs = runs
        self._coordinator = coordinator
        self._worker_id = worker_id
        self._continuations = continuations
        self._continuation_delivery = continuation_delivery
        self._clock = clock or (lambda: datetime.now(tz=UTC))

    async def run_once(self, *, limit: int = 100) -> tuple[BriefingRun, ...]:
        now = self._clock()
        due = await self._subscriptions.claim_due(
            now=now,
            limit=limit,
            lease_owner=self._worker_id,
            lease_seconds=300,
        )
        completed: list[BriefingRun] = []
        for subscription in due:
            local_slot = subscription.next_run_at.astimezone(
                ZoneInfo(subscription.timezone)
            ).strftime("%Y-%m-%dT%H:%M")
            key = f"briefing:{subscription.subscription_id}:{local_slot}"
            lateness = max(0, int((now - subscription.next_run_at).total_seconds()))
            status: BriefingRunStatus | None = None
            if lateness > subscription.max_lateness_seconds:
                status = BriefingRunStatus.FAILED
                content = BriefingContent(
                    title="Briefing missed",
                    body_markdown=(
                        "The scheduled briefing exceeded its configured lateness window "
                        "and was not generated."
                    ),
                    item_count=0,
                    evidence_refs=(),
                    source_errors=(f"missed_by_seconds:{lateness}",),
                )
            else:
                try:
                    content = await self._coordinator.generate(
                        spec=subscription.spec,
                        now=now,
                    )
                except Exception as exc:  # noqa: BLE001 - isolate one subscription
                    status = BriefingRunStatus.FAILED
                    content = BriefingContent(
                        title="Briefing failed",
                        body_markdown="The briefing could not be generated from its sources.",
                        item_count=0,
                        evidence_refs=(),
                        source_errors=(f"{type(exc).__name__}:{exc}",),
                    )
                    _LOGGER.warning(
                        "briefing_generation_failed",
                        extra={"subscription_id": subscription.subscription_id},
                    )
            run = _run(
                principal_id=subscription.principal_id,
                conversation_id=None,
                subscription=subscription,
                scheduled_for=subscription.next_run_at,
                started_at=now,
                idempotency_key=key,
                content=content,
                status=status,
            )
            try:
                stored = await self._runs.create(run)
                await self._create_continuation(subscription, stored)
                await self._subscriptions.advance(
                    subscription_id=subscription.subscription_id,
                    principal_id=subscription.principal_id,
                    expected_revision=subscription.revision,
                    next_run_at=next_cron_run(
                        subscription.cron_expression,
                        subscription.timezone,
                        after=subscription.next_run_at,
                    ),
                )
            except Exception:  # noqa: BLE001 - preserve remaining due work
                _LOGGER.exception(
                    "briefing_run_persist_or_advance_failed",
                    extra={"subscription_id": subscription.subscription_id},
                )
                continue
            completed.append(stored)
        return tuple(completed)

    async def _create_continuation(
        self,
        subscription: BriefingSubscription,
        run: BriefingRun,
    ) -> ScheduledConversationAnchor | None:
        if (
            subscription.continuation_mode is ContinuationMode.NONE
            or run.status is BriefingRunStatus.FAILED
        ):
            return None
        if self._continuations is None:
            raise RuntimeError("continuable briefing requires a continuation service")
        origin = subscription.continuation_origin
        scope_ref = subscription.spec.scope_ref
        result_digest = run.result_digest
        if origin is None or scope_ref is None or result_digest is None:
            raise RuntimeError("continuable briefing is missing immutable result metadata")
        anchor = await self._continuations.create(
            ScheduledConversationAnchor(
                anchor_id=anchor_id_for_run(
                    task_id=subscription.subscription_id,
                    run_id=run.run_id,
                ),
                task_id=subscription.subscription_id,
                run_id=run.run_id,
                owner_principal_id=subscription.principal_id,
                scope_ref=scope_ref,
                mode=subscription.continuation_mode,
                origin=origin,
                result_digest=result_digest,
                result_summary=f"{run.title}\n\n{run.body_markdown}",
                evidence_refs=run.evidence_refs,
                observation_started_at=run.started_at
                - timedelta(seconds=subscription.spec.lookback_seconds),
                observation_ended_at=run.started_at,
                created_at=run.started_at,
                expires_at=run.started_at
                + timedelta(seconds=subscription.continuation_ttl_seconds),
            )
        )
        if self._continuation_delivery is not None:
            await self._continuation_delivery.deliver(anchor)
        return anchor


def next_cron_run(expression: str, timezone: str, *, after: datetime) -> datetime:
    """Return the next IANA-timezone cron occurrence as an aware UTC datetime."""
    zone = ZoneInfo(timezone)
    local_after = after.astimezone(zone)
    next_local = croniter(expression, local_after).get_next(datetime)
    if next_local.tzinfo is None:
        next_local = next_local.replace(tzinfo=zone)
    return next_local.astimezone(UTC)


def _run(
    *,
    principal_id: str,
    conversation_id: str | None,
    subscription: BriefingSubscription | None,
    scheduled_for: datetime,
    started_at: datetime,
    idempotency_key: str,
    content: BriefingContent,
    status: BriefingRunStatus | None = None,
) -> BriefingRun:
    resolved_status = status or (
        BriefingRunStatus.PARTIAL if content.source_errors else BriefingRunStatus.DELIVERED
    )
    digest = hashlib.sha256(idempotency_key.encode()).hexdigest()[:24]
    continuation_mode = subscription.continuation_mode if subscription else ContinuationMode.NONE
    result_digest = (
        _result_digest(content) if continuation_mode is not ContinuationMode.NONE else None
    )
    return BriefingRun(
        run_id=f"briefing-run-{digest}",
        subscription_id=(subscription.subscription_id if subscription else None),
        principal_id=principal_id,
        conversation_id=conversation_id,
        scheduled_for=scheduled_for,
        started_at=started_at,
        status=resolved_status,
        idempotency_key=idempotency_key,
        title=content.title,
        body_markdown=content.body_markdown,
        item_count=content.item_count,
        evidence_refs=content.evidence_refs,
        source_errors=content.source_errors,
        continuation_mode=continuation_mode,
        continuation_origin=(subscription.continuation_origin if subscription else None),
        result_digest=result_digest,
    )


def _result_digest(content: BriefingContent) -> str:
    payload = json.dumps(
        {
            "body_markdown": content.body_markdown,
            "evidence_refs": content.evidence_refs,
            "item_count": content.item_count,
            "source_errors": content.source_errors,
            "title": content.title,
        },
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def _safe(value: str, limit: int) -> str:
    return " ".join(value.replace("`", "'").split())[:limit]


__all__ = [
    "BriefingContent",
    "BriefingCoordinator",
    "BriefingSchedulerService",
    "OpeningBriefingService",
    "next_cron_run",
]
