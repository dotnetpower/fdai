"""Materialize Process runtime snapshots into the ontology instance graph."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Protocol

from fdai.shared.providers.ontology_instance import (
    OntologyInstanceStore,
    OntologyLinkRecord,
    OntologyObjectRecord,
)
from fdai.shared.providers.process_projection import ProcessProjectionOutbox
from fdai.shared.providers.process_runtime import (
    ProcessEvent,
    ProcessRuntimeStore,
    ProcessSnapshot,
    ProcessStatus,
)

_LOGGER = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(tz=UTC)


class ProcessProjector(Protocol):
    async def project(
        self,
        snapshot: ProcessSnapshot,
        *,
        event: ProcessEvent | None = None,
    ) -> None: ...


class ProcessDomainProjector(Protocol):
    async def project(
        self,
        snapshot: ProcessSnapshot,
        *,
        event: ProcessEvent | None = None,
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class ProcessOntologyProjector:
    store: OntologyInstanceStore
    domain_projectors: Mapping[str, ProcessDomainProjector] = field(default_factory=dict)

    async def project(
        self,
        snapshot: ProcessSnapshot,
        *,
        event: ProcessEvent | None = None,
    ) -> None:
        """Upsert the Process object and its target link when the Resource exists."""
        await self.store.upsert_object(
            OntologyObjectRecord(
                id=snapshot.process_id,
                object_type="Process",
                properties={
                    "id": snapshot.process_id,
                    "workflow_ref": snapshot.workflow_ref,
                    "workflow_version": snapshot.workflow_version,
                    "status": snapshot.status.value,
                    "current_step": snapshot.current_step,
                    "target_resource_id": snapshot.target_resource_id,
                    "started_at": snapshot.started_at.isoformat(),
                    "updated_at": snapshot.updated_at.isoformat(),
                    "correlation_id": snapshot.correlation_id,
                    "revision": snapshot.revision,
                },
            )
        )
        target = await self.store.get_object(snapshot.target_resource_id)
        if target is not None and target.object_type == "Resource":
            await self.store.upsert_link(
                OntologyLinkRecord(
                    link_type="targets",
                    from_id=snapshot.process_id,
                    to_id=snapshot.target_resource_id,
                )
            )
        definitions = await self.store.query_objects(
            object_types=("WorkflowDefinition",),
            property_equals={
                "workflow_name": snapshot.workflow_ref,
                "workflow_version": snapshot.workflow_version,
            },
            limit=2,
        )
        if len(definitions.objects) == 1:
            await self.store.upsert_link(
                OntologyLinkRecord(
                    link_type="instantiates_workflow",
                    from_id=snapshot.process_id,
                    to_id=definitions.objects[0].id,
                )
            )
        domain_projector = self.domain_projectors.get(snapshot.workflow_ref)
        if domain_projector is not None:
            await domain_projector.project(snapshot, event=event)


class ProjectingProcessRuntimeStore:
    """Commit runtime state and refresh its retry-backed ontology projection."""

    def __init__(
        self,
        *,
        runtime: ProcessRuntimeStore,
        projector: ProcessProjector,
        retry_batch_size: int = 100,
        retry_clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        if not isinstance(runtime, ProcessProjectionOutbox):
            raise TypeError("runtime MUST implement ProcessProjectionOutbox")
        if not 1 <= retry_batch_size <= 1000:
            raise ValueError("retry_batch_size MUST be in [1, 1000]")
        self._runtime = runtime
        self._outbox: ProcessProjectionOutbox = runtime
        self._projector = projector
        self._retry_worker = ProcessProjectionWorker(
            runtime=runtime,
            outbox=runtime,
            projector=projector,
            batch_size=retry_batch_size,
            clock=retry_clock,
        )

    async def create(
        self,
        *,
        snapshot: ProcessSnapshot,
        event: ProcessEvent,
    ) -> tuple[ProcessSnapshot, bool]:
        stored, created = await self._runtime.create(snapshot=snapshot, event=event)
        await self._project_after_commit(stored, event)
        return stored, created

    async def transition(
        self,
        *,
        process_id: str,
        expected_revision: int,
        status: ProcessStatus,
        current_step: str,
        event: ProcessEvent,
    ) -> ProcessSnapshot:
        stored = await self._runtime.transition(
            process_id=process_id,
            expected_revision=expected_revision,
            status=status,
            current_step=current_step,
            event=event,
        )
        await self._project_after_commit(stored, event)
        return stored

    async def get(self, process_id: str) -> ProcessSnapshot | None:
        return await self._runtime.get(process_id)

    async def events(self, process_id: str) -> tuple[ProcessEvent, ...]:
        return await self._runtime.events(process_id)

    async def append_event(self, event: ProcessEvent) -> bool:
        appended = await self._runtime.append_event(event)
        if appended:
            snapshot = await self._runtime.get(event.process_id)
            if snapshot is None:  # pragma: no cover - store invariant
                raise RuntimeError(f"process {event.process_id!r} vanished after event append")
            await self._project_after_commit(snapshot, event)
        return appended

    async def list(
        self,
        *,
        workflow_ref: str | None = None,
        status: ProcessStatus | None = None,
        limit: int = 100,
    ) -> tuple[ProcessSnapshot, ...]:
        return await self._runtime.list(
            workflow_ref=workflow_ref,
            status=status,
            limit=limit,
        )

    async def retry_pending(self) -> ProcessProjectionRun:
        """Run one bounded retry batch for startup or event-driven jobs."""
        return await self._retry_worker.run_once()

    async def _project_after_commit(
        self,
        snapshot: ProcessSnapshot,
        event: ProcessEvent,
    ) -> None:
        try:
            await self._projector.project(snapshot, event=event)
            await self._outbox.complete_projection(event.event_id)
            await self._retry_worker.run_once()
        except Exception as exc:  # noqa: BLE001 - the durable outbox owns retry
            _LOGGER.warning(
                "process_projection_deferred",
                extra={
                    "process_id": snapshot.process_id,
                    "event_id": event.event_id,
                    "correlation_id": snapshot.correlation_id,
                    "error_type": type(exc).__name__,
                },
            )


@dataclass(frozen=True, slots=True)
class ProcessProjectionRun:
    claimed: int
    completed: int
    deferred: int


@dataclass(frozen=True, slots=True)
class ProcessProjectionWorker:
    runtime: ProcessRuntimeStore
    outbox: ProcessProjectionOutbox
    projector: ProcessProjector
    batch_size: int = 100
    lease_seconds: int = 30
    retry_delay_seconds: int = 30
    clock: Callable[[], datetime] = _utcnow

    def __post_init__(self) -> None:
        if not 1 <= self.batch_size <= 1000:
            raise ValueError("batch_size MUST be in [1, 1000]")
        if self.lease_seconds < 1:
            raise ValueError("lease_seconds MUST be >= 1")
        if self.retry_delay_seconds < 1:
            raise ValueError("retry_delay_seconds MUST be >= 1")

    async def run_once(self) -> ProcessProjectionRun:
        now = self.clock()
        jobs = await self.outbox.claim_projections(
            now=now,
            limit=self.batch_size,
            lease_seconds=self.lease_seconds,
        )
        completed = 0
        deferred = 0
        for job in jobs:
            snapshot = await self.runtime.get(job.event.process_id)
            if snapshot is None:
                await self.outbox.complete_projection(job.event.event_id)
                completed += 1
                continue
            try:
                await self.projector.project(snapshot, event=job.event)
                await self.outbox.complete_projection(job.event.event_id)
                completed += 1
            except Exception as exc:  # noqa: BLE001 - retry each job independently
                deferred += 1
                retry_at = now + timedelta(seconds=self.retry_delay_seconds)
                try:
                    await self.outbox.retry_projection(
                        job.event.event_id,
                        available_at=retry_at,
                        last_error=type(exc).__name__,
                    )
                except Exception as retry_exc:  # noqa: BLE001 - lease expiry is fallback
                    _LOGGER.error(
                        "process_projection_retry_update_failed",
                        extra={
                            "process_id": snapshot.process_id,
                            "event_id": job.event.event_id,
                            "correlation_id": snapshot.correlation_id,
                            "error_type": type(retry_exc).__name__,
                        },
                    )
                _LOGGER.warning(
                    "process_projection_retry_deferred",
                    extra={
                        "process_id": snapshot.process_id,
                        "event_id": job.event.event_id,
                        "correlation_id": snapshot.correlation_id,
                        "attempt": job.attempts,
                        "error_type": type(exc).__name__,
                    },
                )
        return ProcessProjectionRun(
            claimed=len(jobs),
            completed=completed,
            deferred=deferred,
        )


__all__ = [
    "ProcessDomainProjector",
    "ProcessOntologyProjector",
    "ProcessProjectionRun",
    "ProcessProjectionWorker",
    "ProcessProjector",
    "ProjectingProcessRuntimeStore",
]
