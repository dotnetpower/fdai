"""Serialize count-only inventory progress across concurrent provider callbacks."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime
from typing import Protocol

from fdai_service_contracts import (
    InventoryProgressFractionBasis,
    InventoryProgressRecord,
    InventoryProgressStage,
    InventoryProgressState,
    inventory_progress_record_digest,
)

INVENTORY_PROGRESS_GENESIS_DIGEST = "sha256:" + "0" * 64
InventoryProgressClock = Callable[[], datetime]


class InventoryProgressPublisher(Protocol):
    """Append one validated progress record without granting collection authority."""

    async def append(self, record: InventoryProgressRecord) -> bool: ...


class InventoryProgressUnavailableError(RuntimeError):
    """A progress sink failed and the recorder cannot safely infer append state."""


class InventoryProgressRecorder:
    """Own one attempt's monotonic counters and hash chain under an async lock."""

    def __init__(
        self,
        *,
        run_id: str,
        attempt_id: str,
        scopes_total: int,
        provider_types_total: int,
        pages_expected: int,
        started_at: datetime,
        deadline_at: datetime,
        publisher: InventoryProgressPublisher,
        clock: InventoryProgressClock,
    ) -> None:
        if scopes_total < 1 or provider_types_total < 0 or pages_expected < 0:
            raise ValueError("inventory progress initial counters are invalid")
        if started_at.tzinfo is None or deadline_at.tzinfo is None or deadline_at <= started_at:
            raise ValueError("inventory progress attempt times are invalid")
        self._run_id = run_id
        self._attempt_id = attempt_id
        self._scopes_total = scopes_total
        self._provider_types_total = provider_types_total
        self._pages_expected = pages_expected
        self._started_at = started_at
        self._deadline_at = deadline_at
        self._publisher = publisher
        self._clock = clock
        self._lock = asyncio.Lock()
        self._sequence = 0
        self._previous_digest = INVENTORY_PROGRESS_GENESIS_DIGEST
        self._scopes_completed = 0
        self._provider_types_completed = 0
        self._resources_observed = 0
        self._resources_expected: int | None = None
        self._pages_completed = 0
        self._links_observed = 0
        self._unmapped_objects = 0
        self._coverage_gaps = 0
        self._generation_digest: str | None = None
        self._terminal = False
        self._publish_failed = False

    @classmethod
    def resume(
        cls,
        record: InventoryProgressRecord,
        *,
        publisher: InventoryProgressPublisher,
        clock: InventoryProgressClock,
    ) -> InventoryProgressRecorder:
        """Resume one validated nonterminal chain for postcondition finalization."""

        if record.state is not InventoryProgressState.RUNNING:
            raise ValueError("only running inventory progress can resume")
        recorder = cls(
            run_id=record.run_id,
            attempt_id=record.attempt_id,
            scopes_total=record.scopes_total,
            provider_types_total=record.provider_types_total,
            pages_expected=record.pages_expected,
            started_at=record.started_at,
            deadline_at=record.deadline_at,
            publisher=publisher,
            clock=clock,
        )
        recorder._sequence = record.sequence
        recorder._previous_digest = record.record_digest
        recorder._scopes_completed = record.scopes_completed
        recorder._provider_types_completed = record.provider_types_completed
        recorder._resources_observed = record.resources_observed
        recorder._resources_expected = record.resources_expected
        recorder._pages_completed = record.pages_completed
        recorder._links_observed = record.links_observed
        recorder._unmapped_objects = record.unmapped_objects
        recorder._coverage_gaps = record.coverage_gaps
        recorder._generation_digest = record.generation_digest
        return recorder

    async def begin_source(self, *, provider_types: int, initial_pages: int) -> None:
        """Expand planned work when an ordered fallback source actually starts."""

        if provider_types < 0 or initial_pages < 0:
            raise ValueError("inventory progress source counters MUST be non-negative")
        async with self._lock:
            self._require_open()
            self._provider_types_total += provider_types
            self._pages_expected += initial_pages

    async def page_collected(self, *, has_more: bool) -> InventoryProgressRecord:
        """Advance one provider page and extend its estimate for a continuation."""

        async with self._lock:
            self._require_open()
            self._pages_completed += 1
            if has_more:
                self._pages_expected += 1
            return await self._append(
                stage=InventoryProgressStage.COLLECT,
                state=InventoryProgressState.RUNNING,
                reason_code=None,
            )

    async def provider_type_completed(
        self,
        *,
        resources: int,
        links: int,
        unmapped_objects: int = 0,
        coverage_gaps: int = 0,
    ) -> InventoryProgressRecord:
        """Advance one completed type shard using aggregate counts only."""

        if min(resources, links, unmapped_objects, coverage_gaps) < 0:
            raise ValueError("inventory progress shard counters MUST be non-negative")
        async with self._lock:
            self._require_open()
            self._provider_types_completed += 1
            self._resources_observed += resources
            self._links_observed += links
            self._unmapped_objects += unmapped_objects
            self._coverage_gaps += coverage_gaps
            return await self._append(
                stage=InventoryProgressStage.COLLECT,
                state=InventoryProgressState.RUNNING,
                reason_code=None,
            )

    async def advance(
        self,
        stage: InventoryProgressStage,
        *,
        scopes_completed: int | None = None,
        provider_types_completed: int | None = None,
        provider_types_total: int | None = None,
        resources_observed: int | None = None,
        resources_expected: int | None = None,
        pages_completed: int | None = None,
        pages_expected: int | None = None,
        links_observed: int | None = None,
        unmapped_objects: int | None = None,
        coverage_gaps: int | None = None,
        generation_digest: str | None = None,
    ) -> InventoryProgressRecord:
        """Publish one nonterminal monotonic snapshot of absolute counters."""

        if stage in {InventoryProgressStage.COMPLETE, InventoryProgressStage.FAILED}:
            raise ValueError("terminal inventory progress requires a terminal method")
        async with self._lock:
            self._require_open()
            self._advance_counters(
                scopes_completed=scopes_completed,
                provider_types_completed=provider_types_completed,
                provider_types_total=provider_types_total,
                resources_observed=resources_observed,
                resources_expected=resources_expected,
                pages_completed=pages_completed,
                pages_expected=pages_expected,
                links_observed=links_observed,
                unmapped_objects=unmapped_objects,
                coverage_gaps=coverage_gaps,
            )
            if generation_digest is not None:
                if (
                    self._generation_digest is not None
                    and generation_digest != self._generation_digest
                ):
                    raise ValueError("inventory progress generation digest MUST NOT change")
                self._generation_digest = generation_digest
            return await self._append(
                stage=stage,
                state=InventoryProgressState.RUNNING,
                reason_code=None,
            )

    async def complete(self) -> InventoryProgressRecord:
        """Publish verified closure only after callers complete independent readback."""

        async with self._lock:
            self._require_open()
            self._scopes_completed = self._scopes_total
            record = await self._append(
                stage=InventoryProgressStage.COMPLETE,
                state=InventoryProgressState.COMPLETE,
                reason_code=None,
            )
            self._terminal = True
            return record

    async def fail(self, reason_code: str) -> InventoryProgressRecord:
        """Publish one stable terminal failure without provider error text."""

        async with self._lock:
            self._require_open()
            record = await self._append(
                stage=InventoryProgressStage.FAILED,
                state=InventoryProgressState.FAILED,
                reason_code=reason_code,
            )
            self._terminal = True
            return record

    def _advance_counters(self, **values: int | None) -> None:
        for field_name, value in values.items():
            if value is None:
                continue
            attribute = f"_{field_name}"
            current = getattr(self, attribute)
            if current is not None and value < current:
                raise ValueError(f"inventory progress {field_name} MUST NOT regress")
            setattr(self, attribute, value)

    async def _append(
        self,
        *,
        stage: InventoryProgressStage,
        state: InventoryProgressState,
        reason_code: str | None,
    ) -> InventoryProgressRecord:
        observed_at = self._clock()
        if observed_at.tzinfo is None or not self._started_at <= observed_at <= self._deadline_at:
            raise ValueError("inventory progress clock is outside the attempt window")
        next_sequence = self._sequence + 1
        fraction, basis = self._fraction(stage, state)
        values: dict[str, object] = {
            "run_id": self._run_id,
            "attempt_id": self._attempt_id,
            "sequence": next_sequence,
            "previous_digest": self._previous_digest,
            "stage": stage,
            "state": state,
            "reason_code": reason_code,
            "generation_digest": self._generation_digest,
            "scopes_completed": self._scopes_completed,
            "scopes_total": self._scopes_total,
            "provider_types_completed": self._provider_types_completed,
            "provider_types_total": self._provider_types_total,
            "resources_observed": self._resources_observed,
            "resources_expected": self._resources_expected,
            "pages_completed": self._pages_completed,
            "pages_expected": self._pages_expected,
            "links_observed": self._links_observed,
            "unmapped_objects": self._unmapped_objects,
            "coverage_gaps": self._coverage_gaps,
            "started_at": self._started_at,
            "last_progress_at": observed_at,
            "deadline_at": self._deadline_at,
            "fraction": fraction,
            "fraction_basis": basis,
        }
        record = InventoryProgressRecord(
            run_id=self._run_id,
            attempt_id=self._attempt_id,
            sequence=next_sequence,
            previous_digest=self._previous_digest,
            stage=stage,
            state=state,
            reason_code=reason_code,
            generation_digest=self._generation_digest,
            scopes_completed=self._scopes_completed,
            scopes_total=self._scopes_total,
            provider_types_completed=self._provider_types_completed,
            provider_types_total=self._provider_types_total,
            resources_observed=self._resources_observed,
            resources_expected=self._resources_expected,
            pages_completed=self._pages_completed,
            pages_expected=self._pages_expected,
            links_observed=self._links_observed,
            unmapped_objects=self._unmapped_objects,
            coverage_gaps=self._coverage_gaps,
            started_at=self._started_at,
            last_progress_at=observed_at,
            deadline_at=self._deadline_at,
            fraction=fraction,
            fraction_basis=basis,
            record_digest=inventory_progress_record_digest(**values),
        )
        try:
            await self._publisher.append(record)
        except Exception as exc:
            self._publish_failed = True
            raise InventoryProgressUnavailableError(
                "inventory progress persistence is unavailable"
            ) from exc
        self._sequence = next_sequence
        self._previous_digest = record.record_digest
        return record

    def _fraction(
        self,
        stage: InventoryProgressStage,
        state: InventoryProgressState,
    ) -> tuple[float, InventoryProgressFractionBasis]:
        if state is InventoryProgressState.COMPLETE:
            return 1.0, InventoryProgressFractionBasis.VERIFIED_CLOSURE
        if stage is InventoryProgressStage.COUNT:
            return 0.05, InventoryProgressFractionBasis.COUNT
        if stage is InventoryProgressStage.COLLECT:
            type_fraction = (
                self._provider_types_completed / self._provider_types_total
                if self._provider_types_total
                else 0.0
            )
            page_fraction = (
                self._pages_completed / self._pages_expected if self._pages_expected else 0.0
            )
            if page_fraction > type_fraction:
                return min(0.64, 0.05 + 0.59 * page_fraction), InventoryProgressFractionBasis.PAGES
            return (
                min(0.64, 0.05 + 0.59 * type_fraction),
                InventoryProgressFractionBasis.PROVIDER_TYPES,
            )
        floor = {
            InventoryProgressStage.STAGE: 0.68,
            InventoryProgressStage.ENRICH: 0.76,
            InventoryProgressStage.VALIDATE: 0.84,
            InventoryProgressStage.PROMOTE: 0.91,
            InventoryProgressStage.VERIFY: 0.97,
            InventoryProgressStage.FAILED: 0.0,
        }[stage]
        return floor, InventoryProgressFractionBasis.PROVIDER_TYPES

    def _require_open(self) -> None:
        if self._publish_failed:
            raise InventoryProgressUnavailableError(
                "inventory progress recorder is unavailable after an ambiguous append"
            )
        if self._terminal:
            raise ValueError("terminal inventory progress cannot advance")


class CompositeInventoryProgressPublisher:
    """Require every ordered publisher to accept the same immutable record."""

    def __init__(self, *publishers: InventoryProgressPublisher) -> None:
        if not publishers:
            raise ValueError("inventory progress requires at least one publisher")
        self._publishers = publishers

    async def append(self, record: InventoryProgressRecord) -> bool:
        inserted = False
        for publisher in self._publishers:
            inserted = await publisher.append(record) or inserted
        return inserted


__all__ = [
    "CompositeInventoryProgressPublisher",
    "INVENTORY_PROGRESS_GENESIS_DIGEST",
    "InventoryProgressPublisher",
    "InventoryProgressRecorder",
    "InventoryProgressUnavailableError",
]
