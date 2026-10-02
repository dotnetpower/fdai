"""Bind reviewed authoritative inventory sources to forecast history producers.

Both adapters restate records their owners already retained and never write a source fact.
Neither source can currently attest a positive start-of-window checkpoint, so each checkpoint
stays incomplete with an explicit limitation and the collector keeps holding scoring:

* external changes come from the append-only journal witness, whose fenced pages cannot
  exclude in-flight or earlier missing ingestion;
* resource lifecycle comes from confirmed-tombstone incarnation boundaries, which cannot
  exclude an unobserved deletion before the next complete reconciliation.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from fdai.core.detection.forecast_history_source import (
    ForecastSourceCheckpoint,
    ForecastSourceRead,
    ForecastSourceRecord,
)
from fdai.delivery.forecast_change_history import ForecastChangeHistoryResult
from fdai.delivery.persistence.postgres_forecast_change_history import ForecastChangeHistoryQuery
from fdai.delivery.persistence.postgres_forecast_lifecycle_history import LifecycleLedgerRead
from fdai.shared.providers.audit_hash import next_hash

FORECAST_CHANGE_HISTORY_SOURCE_IDENTITY = "fdai.inventory_observation_journal.external_changes"
FORECAST_CHANGE_HISTORY_SOURCE_REVISION = "forecast-change-history-witness.v1"
FORECAST_LIFECYCLE_HISTORY_SOURCE_IDENTITY = "fdai.inventory_resource_incarnation.lifecycle"
FORECAST_LIFECYCLE_HISTORY_SOURCE_REVISION = "forecast-lifecycle-ledger.v1"
FORECAST_ACTION_HISTORY_SOURCE_IDENTITY = "fdai.thor_saga_state_store.action_audit"
FORECAST_ACTION_HISTORY_SOURCE_REVISION = "forecast-action-audit-chain.v1"


class ForecastChangeWitnessReader(Protocol):
    async def read(self, query: ForecastChangeHistoryQuery) -> ForecastChangeHistoryResult: ...


class ForecastLifecycleLedgerReader(Protocol):
    async def read_ledger(
        self,
        *,
        subject_ref: str,
        start_at: datetime,
        end_at: datetime,
        known_at: datetime,
    ) -> LifecycleLedgerRead: ...


@dataclass(frozen=True, slots=True)
class ActionAuditHistoryRow:
    seq: int
    recorded_at: datetime
    entry: Mapping[str, Any] | None
    previous_hash: str
    entry_hash: str
    state: Mapping[str, Any] | None


@dataclass(frozen=True, slots=True)
class ActionAuditHistoryRead:
    rows: tuple[ActionAuditHistoryRow, ...]
    truncated: bool


class ForecastActionAuditReader(Protocol):
    async def read_action_audit(
        self,
        *,
        subject_ref: str,
        start_at: datetime,
        end_at: datetime,
        known_at: datetime,
        limit: int,
    ) -> ActionAuditHistoryRead: ...


class ActionAuditHistorySource:
    """Restate Thor/Saga action history from contiguous state-store audit rows."""

    def __init__(self, *, reader: ForecastActionAuditReader) -> None:
        self._reader = reader

    async def read(
        self,
        *,
        subject_ref: str,
        start_at: datetime,
        end_at: datetime,
        known_at: datetime,
    ) -> ForecastSourceRead:
        result = await self._reader.read_action_audit(
            subject_ref=subject_ref,
            start_at=start_at,
            end_at=end_at,
            known_at=known_at,
            limit=257,
        )
        tokens: set[str] = set()
        if result.truncated or len(result.rows) > 256:
            tokens.add("result_limit")
        rows = result.rows[:256]
        if not rows:
            tokens.add("audit_chain_window_empty")
        if any(
            not _row_chain_valid(previous, current)
            for previous, current in zip(rows, rows[1:], strict=False)
        ):
            tokens.add("audit_chain_gap_or_hash_mismatch")
        records: list[ForecastSourceRecord] = []
        seen: set[str] = set()
        for row in rows:
            if row.entry is None or row.state is None:
                continue
            correlation_id = _bounded_text(row.entry.get("correlation_id")) or _bounded_text(
                row.state.get("correlation_id")
            )
            if correlation_id is None:
                tokens.add("action_correlation_missing")
                continue
            state = _bounded_text(row.state.get("state"))
            action_type = _bounded_text(row.state.get("action_type"))
            resource_id = _bounded_text(row.state.get("resource_id"))
            if state is None or action_type is None or resource_id != subject_ref:
                tokens.add("action_state_malformed")
                continue
            if correlation_id in seen:
                continue
            seen.add(correlation_id)
            records.append(
                ForecastSourceRecord(
                    source_event_id="action-run:" + _digest(correlation_id),
                    source_revision=f"audit-seq:{row.seq}:{row.entry_hash}",
                    source_state=state,
                    subject_ref=subject_ref,
                    effective_at=row.recorded_at,
                    recorded_at=row.recorded_at,
                    evidence_ref=f"state-store-audit:{row.seq}:{row.entry_hash}",
                    pending=state in {"executing", "execution_unknown", "effect_pending"},
                )
            )
        complete = not tokens
        watermark = f"audit-seq:{rows[-1].seq}:{rows[-1].entry_hash}" if rows else "audit-empty"
        return ForecastSourceRead(
            records=tuple(records),
            checkpoint=ForecastSourceCheckpoint(
                source_identity=FORECAST_ACTION_HISTORY_SOURCE_IDENTITY,
                source_revision=FORECAST_ACTION_HISTORY_SOURCE_REVISION,
                subject_ref=subject_ref,
                coverage_start_at=start_at,
                coverage_end_at=end_at,
                known_at=known_at,
                watermark=watermark,
                evidence_ref="state-store-audit-chain:" + _digest(watermark),
                complete=complete,
                limitation="+".join(sorted(tokens)) if tokens else None,
            ),
            exhausted=not result.truncated,
        )


def _row_chain_valid(previous: ActionAuditHistoryRow, current: ActionAuditHistoryRow) -> bool:
    if current.seq != previous.seq + 1 or current.previous_hash != previous.entry_hash:
        return False
    if previous.entry is not None and next_hash(previous.previous_hash, previous.entry) != (
        previous.entry_hash
    ):
        return False
    if current.entry is not None and next_hash(current.previous_hash, current.entry) != (
        current.entry_hash
    ):
        return False
    return True


def _bounded_text(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip() or len(value) > 512:
        return None
    return value


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


class JournalChangeHistorySource:
    """Restate witnessed journal changes; coverage keeps the witness limitation."""

    def __init__(self, *, witness: ForecastChangeWitnessReader, scope_ref: str) -> None:
        self._witness = witness
        self._scope_ref = scope_ref

    async def read(
        self,
        *,
        subject_ref: str,
        start_at: datetime,
        end_at: datetime,
        known_at: datetime,
    ) -> ForecastSourceRead:
        result = await self._witness.read(
            ForecastChangeHistoryQuery(
                scope_ref=self._scope_ref,
                subject_ref=subject_ref,
                start_at=start_at,
                end_at=end_at,
                known_at=known_at,
            )
        )
        records = tuple(
            ForecastSourceRecord(
                source_event_id="journal-event:"
                + _digest(f"{change.source_identity}\n{change.source_event_id}"),
                source_revision=change.observation_ref,
                source_state=f"{change.observation_kind}:{change.mutation_kind}",
                subject_ref=change.subject_ref,
                effective_at=change.effective_at,
                recorded_at=change.recorded_at,
                evidence_ref=change.observation_ref,
            )
            for change in result.changes
        )
        coverage = result.coverage
        return ForecastSourceRead(
            records=records,
            checkpoint=ForecastSourceCheckpoint(
                source_identity=FORECAST_CHANGE_HISTORY_SOURCE_IDENTITY,
                source_revision=FORECAST_CHANGE_HISTORY_SOURCE_REVISION,
                subject_ref=subject_ref,
                coverage_start_at=coverage.start_at,
                coverage_end_at=coverage.end_at,
                known_at=coverage.known_at,
                watermark=f"inventory-journal-fence:{coverage.fence_watermark}",
                evidence_ref=f"inventory-journal-fence:{coverage.fence_watermark}",
                complete=False,
                limitation=coverage.limitation,
            ),
            exhausted=result.exhausted,
        )


@dataclass(frozen=True, slots=True)
class _Boundary:
    record: ForecastSourceRecord
    order: int


class IncarnationLifecycleHistorySource:
    """Restate confirmed incarnation boundaries; absence never becomes a deletion."""

    def __init__(self, *, reader: ForecastLifecycleLedgerReader) -> None:
        self._reader = reader

    async def read(
        self,
        *,
        subject_ref: str,
        start_at: datetime,
        end_at: datetime,
        known_at: datetime,
    ) -> ForecastSourceRead:
        ledger = await self._reader.read_ledger(
            subject_ref=subject_ref, start_at=start_at, end_at=end_at, known_at=known_at
        )
        tokens = {"reconciliation_checkpoint_unverified"}
        if ledger.pending_tombstone_ids:
            tokens.add("pending_tombstone")
        boundaries: list[_Boundary] = []
        for item in ledger.incarnations:
            edges: list[tuple[str, datetime, datetime | None, str | None]] = [
                ("present", item.opened_at, item.opened_recorded_at, item.opening_observation_id)
            ]
            if item.closed_at is not None:
                edges.append(
                    (
                        "deleted",
                        item.closed_at,
                        item.closed_recorded_at,
                        item.closing_observation_id,
                    )
                )
            for order, (state, effective_at, recorded_at, observation_id) in enumerate(edges):
                if recorded_at is None or observation_id is None:
                    tokens.add("lifecycle_record_time_unverified")
                    continue
                if recorded_at > known_at or effective_at > end_at:
                    continue
                boundaries.append(
                    _Boundary(
                        ForecastSourceRecord(
                            source_event_id=f"incarnation-{state}:{item.incarnation_id}",
                            source_revision=observation_id,
                            source_state=state,
                            subject_ref=subject_ref,
                            effective_at=effective_at,
                            recorded_at=recorded_at,
                            evidence_ref=f"inventory-observation:{observation_id}",
                        ),
                        order,
                    )
                )
        boundaries.sort(key=lambda item: (item.record.effective_at, item.order))
        prior = [item.record for item in boundaries if item.record.effective_at <= start_at]
        return ForecastSourceRead(
            records=tuple(
                item.record for item in boundaries if item.record.effective_at >= start_at
            ),
            checkpoint=ForecastSourceCheckpoint(
                source_identity=FORECAST_LIFECYCLE_HISTORY_SOURCE_IDENTITY,
                source_revision=FORECAST_LIFECYCLE_HISTORY_SOURCE_REVISION,
                subject_ref=subject_ref,
                coverage_start_at=start_at,
                coverage_end_at=end_at,
                known_at=known_at,
                watermark=ledger.snapshot_ref[:512],
                evidence_ref="inventory-incarnation-ledger:" + _digest(subject_ref),
                complete=False,
                limitation="+".join(sorted(tokens)),
                initial_state=prior[-1].source_state if prior else None,
                initial_state_ref=prior[-1].evidence_ref if prior else None,
            ),
            exhausted=not ledger.truncated,
        )


__all__ = [
    "FORECAST_CHANGE_HISTORY_SOURCE_IDENTITY",
    "FORECAST_CHANGE_HISTORY_SOURCE_REVISION",
    "FORECAST_ACTION_HISTORY_SOURCE_IDENTITY",
    "FORECAST_ACTION_HISTORY_SOURCE_REVISION",
    "FORECAST_LIFECYCLE_HISTORY_SOURCE_IDENTITY",
    "FORECAST_LIFECYCLE_HISTORY_SOURCE_REVISION",
    "ActionAuditHistoryRead",
    "ActionAuditHistoryRow",
    "ActionAuditHistorySource",
    "ForecastChangeWitnessReader",
    "ForecastActionAuditReader",
    "ForecastLifecycleLedgerReader",
    "IncarnationLifecycleHistorySource",
    "JournalChangeHistorySource",
]
