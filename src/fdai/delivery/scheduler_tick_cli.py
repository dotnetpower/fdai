"""Scheduler tick entry point - out-of-band driver for the scheduler.

A Container Apps Job (cron) launches this module once per scheduled fire
(``infra/modules/compute/container-apps/scheduler_job.tf``). It lives under
``delivery/`` (not ``core/``) because it wires the concrete
:class:`~fdai.delivery.persistence.postgres_scheduler_store.PostgresScheduleStore`
adapter - ``core/`` never imports an adapter; a composition-root entry point
does.

It reads the persistent schedule store (shared with the operator console)
from ``FDAI_SCHEDULE_STORE_DSN`` and computes which tasks are due with the
pure :func:`~fdai.core.scheduler.service.compute_due`.

Upstream-safe binding (mirrors ``core/measurement/runners_cli.py``)
------------------------------------------------------------------

Publishing a due task's synthetic event requires the concrete event-bus
adapter (Kafka), which a fork binds at the composition root. Upstream this
entry point runs a **shadow dry-run**: it loads the persistent store,
computes the due set, and logs the task ids that WOULD fire, then exits
``0`` without publishing. A fork swaps the dry-run for
``await SchedulerService(store, bus).run_once(now=now)`` so the same cron
publishes onto the ingest topic - the standard trust-router + risk-gate
still govern any resulting action. The scheduler never executes a change.

Exit codes
----------

- ``0`` - the tick completed (dry-run listed the due set), or no store DSN
  is configured (nothing to do upstream).
- ``3`` - an unexpected error; safe to page.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from datetime import UTC, datetime, timedelta
from typing import Protocol

from fdai.composition import default_container_from_env
from fdai.core.briefing import BriefingCoordinator, BriefingSchedulerService
from fdai.core.report_feed import ReportFeed
from fdai.core.scheduler.continuation import (
    ScheduledContinuationService,
    StateStoreContinuationAuditSink,
)
from fdai.core.scheduler.service import SchedulerService
from fdai.core.user_context_projection import UserContextOntologyProjector
from fdai.delivery.channels.scheduled_continuation import (
    ScheduledContinuationDeliveryCoordinator,
)
from fdai.delivery.event_publisher import EventPublisherContext
from fdai.delivery.persistence import (
    PostgresBriefingRunStore,
    PostgresBriefingStoreConfig,
    PostgresBriefingSubscriptionStore,
    PostgresConversationHistoryStore,
    PostgresReportSignalStore,
    PostgresReportSignalStoreConfig,
    PostgresScheduledContinuationStoreConfig,
    PostgresScheduledConversationAnchorStore,
    PostgresScheduleRunLedger,
    PostgresScheduleRunLedgerConfig,
    PostgresStateStore,
    PostgresStateStoreConfig,
    PostgresUserContextRetention,
    PostgresUserContextStoreConfig,
)
from fdai.delivery.persistence.postgres_ontology import (
    PostgresOntologyInstanceStore,
    PostgresOntologyInstanceStoreConfig,
)
from fdai.delivery.persistence.postgres_scheduler_store import (
    PostgresScheduleStore,
    PostgresScheduleStoreConfig,
)
from fdai.delivery.persistence.postgres_user_context_projection_recovery import (
    PostgresUserContextProjectionRecovery,
)

_LOGGER = logging.getLogger("fdai.delivery.scheduler_tick_cli")

_ENV_DSN = "FDAI_SCHEDULE_STORE_DSN"
_CONVERSATION_RETENTION_DAYS = 90
_BRIEFING_RETENTION_DAYS = 90
_PROJECTION_RETRY_BASE_SECONDS = 60
_PROJECTION_RETRY_MAX_SECONDS = 3600
_PROJECTION_MAX_ATTEMPTS = 5
_SCHEDULE_CLAIM_LEASE_SECONDS = 900


class _AttemptedJob(Protocol):
    @property
    def attempts(self) -> int: ...


def _projection_retry_delay(job: _AttemptedJob) -> timedelta:
    seconds = min(
        _PROJECTION_RETRY_MAX_SECONDS,
        _PROJECTION_RETRY_BASE_SECONDS * (2 ** min(job.attempts, 6)),
    )
    return timedelta(seconds=seconds)


async def _drain_projection_upserts(
    *,
    recovery: PostgresUserContextProjectionRecovery,
    now: datetime,
) -> int:
    completed = 0
    for job in await recovery.claim(now=now):
        try:
            await recovery.project(job)
            await recovery.complete(job)
            completed += 1
        except Exception as exc:  # noqa: BLE001 - durable queue owns recovery
            error = f"{type(exc).__name__}:{exc}"
            if job.attempts + 1 >= _PROJECTION_MAX_ATTEMPTS:
                await recovery.dead_letter(job, error=error)
            else:
                await recovery.retry(
                    job,
                    available_at=now + _projection_retry_delay(job),
                    error=error,
                )
    return completed


async def _drain_projection_deletes(
    *,
    retention: PostgresUserContextRetention,
    ontology: PostgresOntologyInstanceStore,
    now: datetime,
) -> int:
    completed = 0
    for job in await retention.claim_deletions(now=now):
        try:
            await ontology.delete_object(job.object_id)
            await retention.complete_deletion(job.object_id)
            completed += 1
        except Exception as exc:  # noqa: BLE001 - durable queue owns recovery
            await retention.retry_deletion(
                job.object_id,
                available_at=now + _projection_retry_delay(job),
                error=f"{type(exc).__name__}:{exc}",
            )
    return completed


async def _tick() -> int:
    dsn = os.environ.get(_ENV_DSN, "").strip()
    if not dsn:
        _LOGGER.info("scheduler_tick_no_store", extra={"reason": f"{_ENV_DSN} unset"})
        return 0

    store = PostgresScheduleStore(config=PostgresScheduleStoreConfig(dsn=dsn))
    run_ledger = PostgresScheduleRunLedger(config=PostgresScheduleRunLedgerConfig(dsn=dsn))
    schedule_now = datetime.now(tz=UTC)
    lost_runs = await run_ledger.reconcile_stale(
        before=schedule_now - timedelta(seconds=_SCHEDULE_CLAIM_LEASE_SECONDS),
        at=schedule_now,
    )
    if lost_runs:
        _LOGGER.warning(
            "scheduler_stale_claims_reconciled",
            extra={"lost_run_count": len(lost_runs)},
        )
    container = default_container_from_env()
    async with EventPublisherContext(kafka=container.config.kafka) as event_bus:
        report = await SchedulerService(
            store=store,
            event_bus=event_bus,
            topic=container.config.kafka.topic_events,
            run_ledger=run_ledger,
        ).run_once(now=schedule_now)
    briefing_config = PostgresBriefingStoreConfig(dsn=dsn)
    briefing_runs = await BriefingSchedulerService(
        subscriptions=PostgresBriefingSubscriptionStore(config=briefing_config),
        runs=PostgresBriefingRunStore(config=briefing_config),
        coordinator=BriefingCoordinator(
            report_feed=ReportFeed(
                (PostgresReportSignalStore(config=PostgresReportSignalStoreConfig(dsn=dsn)),)
            )
        ),
        worker_id=os.environ.get("HOSTNAME", "scheduler-job"),
        continuations=ScheduledContinuationService(
            store=PostgresScheduledConversationAnchorStore(
                config=PostgresScheduledContinuationStoreConfig(dsn=dsn)
            ),
            audit=StateStoreContinuationAuditSink(
                store=PostgresStateStore(config=PostgresStateStoreConfig(dsn=dsn))
            ),
        ),
        continuation_delivery=ScheduledContinuationDeliveryCoordinator(
            conversations=PostgresConversationHistoryStore(
                config=PostgresUserContextStoreConfig(dsn=dsn)
            )
        ),
    ).run_once()
    now = datetime.now(tz=UTC)
    retention = PostgresUserContextRetention(config=PostgresUserContextStoreConfig(dsn=dsn))
    retention_report = await retention.purge(
        now=now,
        conversation_before=now - timedelta(days=_CONVERSATION_RETENTION_DAYS),
        briefing_before=now - timedelta(days=_BRIEFING_RETENTION_DAYS),
    )
    projection_deletes = 0
    projection_upserts = 0
    if container.ontology_object_types and container.ontology_link_types:
        ontology = PostgresOntologyInstanceStore(
            config=PostgresOntologyInstanceStoreConfig(dsn=dsn),
            object_types=container.ontology_object_types,
            link_types=container.ontology_link_types,
        )
        projection_deletes = await _drain_projection_deletes(
            retention=retention,
            ontology=ontology,
            now=now,
        )
        projection_upserts = await _drain_projection_upserts(
            recovery=PostgresUserContextProjectionRecovery(
                config=PostgresUserContextStoreConfig(dsn=dsn),
                projector=UserContextOntologyProjector(store=ontology),
            ),
            now=now,
        )
    _LOGGER.info(
        "scheduler_tick_complete",
        extra={
            "fired": report.fired,
            "publish_errors": len(report.publish_errors),
            "briefings": len(briefing_runs),
            "retained_conversations_deleted": retention_report.conversations,
            "expired_memories_deleted": retention_report.memories,
            "old_briefing_runs_deleted": retention_report.briefing_runs,
            "ontology_deletes_completed": projection_deletes,
            "ontology_upserts_completed": projection_upserts,
        },
    )
    return 3 if report.publish_errors else 0


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    try:
        return asyncio.run(_tick())
    except Exception:  # noqa: BLE001 - top-level job guard; log + non-zero exit
        _LOGGER.exception("scheduler_tick_failed")
        return 3


if __name__ == "__main__":
    sys.exit(main())
