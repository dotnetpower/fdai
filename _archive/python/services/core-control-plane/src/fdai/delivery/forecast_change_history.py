"""Evidence-only external-change witnesses from the append-only inventory journal."""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any, Literal, Protocol

from fdai.core.ontology_platform.recent_resource_changes import (
    ACTIVITY_LOG_RESOURCE_CHANGE_SOURCE_IDENTITY,
    ARG_RESOURCE_CHANGE_SOURCE_IDENTITY,
)
from fdai.delivery.persistence.postgres_forecast_change_history import (
    ForecastChangeHistoryCursor,
    ForecastChangeHistoryPage,
    ForecastChangeHistoryQuery,
)

_MAX_ROWS = 256
_DIGEST = re.compile(r"sha256:[a-f0-9]{64}\Z")
_TERMINAL_STATUSES = frozenset({"succeeded", "failed", "canceled", "cancelled"})


class ForecastChangeHistoryReader(Protocol):
    async def read_page(
        self,
        query: ForecastChangeHistoryQuery,
        *,
        cursor: ForecastChangeHistoryCursor | None = None,
    ) -> ForecastChangeHistoryPage: ...


@dataclass(frozen=True, slots=True)
class ForecastChangeWitness:
    """Original journal identity and times; never a fabricated state transition."""

    observation_ref: str
    correction_of: str | None
    idempotency_key: str
    scope_ref: str
    subject_ref: str
    subject_type: str
    source_identity: str
    source_event_id: str
    source_revision: str
    observation_kind: str
    mutation_kind: str
    operation: str | None
    operation_status: str | None
    effective_at: datetime
    recorded_at: datetime
    synthetic: Literal[False] = False
    execution_authority: Literal[False] = False


@dataclass(frozen=True, slots=True)
class ForecastChangeCoverage:
    """Journal rows alone cannot establish a start-of-window source checkpoint."""

    complete: Literal[False]
    limitation: str
    scope_ref: str
    subject_ref: str
    start_at: datetime
    end_at: datetime
    known_at: datetime
    fence_watermark: int


@dataclass(frozen=True, slots=True)
class ForecastChangeHistoryResult:
    changes: tuple[ForecastChangeWitness, ...]
    coverage: ForecastChangeCoverage
    exhausted: bool
    pending_event_ids: tuple[str, ...]
    duplicate_event_ids: tuple[str, ...]
    conflicting_event_ids: tuple[str, ...]
    scoring_eligible: Literal[False] = False
    execution_authority: Literal[False] = False


def _text(row: dict[str, Any], field: str) -> str:
    value = row[field]
    if not isinstance(value, str) or not value or value != value.strip() or len(value) > 512:
        raise ValueError(f"forecast change history {field} is not bounded text")
    return value


def _time(row: dict[str, Any], field: str) -> datetime:
    value = row[field]
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"forecast change history {field} MUST be timezone-aware")
    return value


def _validate_row(row: dict[str, Any], query: ForecastChangeHistoryQuery, fence: int) -> None:
    watermark = row["watermark"]
    if isinstance(watermark, bool) or not isinstance(watermark, int) or not 1 <= watermark <= fence:
        raise ValueError("forecast change history watermark is outside the journal fence")
    if (
        _text(row, "scope_ref") != query.scope_ref
        or _text(row, "subject_ref") != query.subject_ref
        or _text(row, "subject_kind") != "object"
    ):
        raise ValueError("forecast change history row is outside the exact target")
    for field in (
        "subject_type",
        "idempotency_key",
        "source_identity",
        "source_event_id",
        "source_revision",
        "observation_kind",
        "mutation_kind",
    ):
        _text(row, field)
    digest = _text(row, "observation_id")
    if digest != _text(row, "content_digest") or _DIGEST.fullmatch(digest) is None:
        raise ValueError("forecast change history observation reference is invalid")
    if (
        not query.start_at <= _time(row, "effective_at") <= query.end_at
        or _time(row, "recorded_at") > query.known_at
    ):
        raise ValueError("forecast change history row is outside the known-at window")
    if row["source_identity"] == ARG_RESOURCE_CHANGE_SOURCE_IDENTITY:
        if row["observation_kind"] not in {"full", "tombstone"}:
            raise ValueError("forecast change history ARG row has no change semantics")
    elif row["source_identity"] == ACTIVITY_LOG_RESOURCE_CHANGE_SOURCE_IDENTITY:
        if row["observation_kind"] not in {"partial", "change_hint", "tombstone"}:
            raise ValueError("forecast change history Activity Log row has no change semantics")
        if not isinstance(row["operation"], str) or not row["operation"].strip():
            raise ValueError("forecast change history Activity Log operation is missing")
    else:
        raise ValueError("forecast change history source is not an external change source")
    if row["observation_kind"] == "tombstone":
        if row["mutation_kind"] != "delete":
            raise ValueError("forecast change history tombstone mutation is inconsistent")
    elif row["mutation_kind"] != "upsert":
        raise ValueError("forecast change history change mutation is inconsistent")
    for field in ("operation", "operation_status"):
        if row[field] is not None:
            _text(row, field)


def _event_key(row: dict[str, Any]) -> tuple[str, str]:
    return (row["source_identity"], row["source_event_id"])


def _is_pending(row: dict[str, Any]) -> bool:
    status = row["operation_status"]
    return (
        row["source_identity"] == ACTIVITY_LOG_RESOURCE_CHANGE_SOURCE_IDENTITY and status is None
    ) or (status is not None and status.lower() not in _TERMINAL_STATUSES)


class ForecastChangeHistoryWitness:
    """Read at most 256 rows and retain uncertainty rather than issuing coverage."""

    def __init__(self, *, reader: ForecastChangeHistoryReader) -> None:
        self._reader = reader

    async def read(self, query: ForecastChangeHistoryQuery) -> ForecastChangeHistoryResult:
        rows: list[dict[str, Any]] = []
        cursor: ForecastChangeHistoryCursor | None = None
        fence: int | None = None
        seen_watermarks: set[int] = set()
        exhausted = False
        async with asyncio.timeout(5):
            while len(rows) < _MAX_ROWS:
                bounded_query = replace(
                    query, page_size=min(query.page_size, _MAX_ROWS - len(rows))
                )
                page = await self._reader.read_page(bounded_query, cursor=cursor)
                if fence is None:
                    fence = page.fence_watermark
                if page.fence_watermark != fence or len(page.rows) > bounded_query.page_size:
                    raise ValueError("forecast change history page changed its journal fence")
                if not page.rows and page.next_cursor is not None:
                    raise ValueError("forecast change history empty page cannot continue")
                previous = (
                    (cursor.effective_at, cursor.recorded_at, cursor.watermark)
                    if cursor is not None
                    else None
                )
                for row in page.rows:
                    _validate_row(row, query, fence)
                    order = (row["effective_at"], row["recorded_at"], row["watermark"])
                    if previous is not None and order <= previous:
                        raise ValueError("forecast change history page ordering is inconsistent")
                    previous = order
                    if row["watermark"] in seen_watermarks:
                        raise ValueError("forecast change history journal watermark was replayed")
                    seen_watermarks.add(row["watermark"])
                    rows.append(row)
                if page.next_cursor is None:
                    exhausted = True
                    break
                last = page.rows[-1]
                if (
                    len(page.rows) != bounded_query.page_size
                    or page.next_cursor.query_identity != query.identity
                    or page.next_cursor.fence_watermark != fence
                    or (
                        page.next_cursor.effective_at,
                        page.next_cursor.recorded_at,
                        page.next_cursor.watermark,
                    )
                    != (last["effective_at"], last["recorded_at"], last["watermark"])
                ):
                    raise ValueError("forecast change history continuation is inconsistent")
                cursor = page.next_cursor
        if fence is None:
            raise ValueError("forecast change history reader returned no journal fence")

        pending = {_event_key(row) for row in rows if _is_pending(row)}
        conflicting: set[tuple[str, str]] = set()
        duplicates: set[tuple[str, str]] = set()
        revisions: dict[tuple[str, str, str], str] = {}
        for row in rows:
            key = (*_event_key(row), row["source_revision"])
            existing = revisions.get(key)
            if existing is None:
                revisions[key] = row["content_digest"]
            elif existing != row["content_digest"]:
                conflicting.add(_event_key(row))
            else:
                duplicates.add(_event_key(row))

        previous_refs: dict[tuple[str, str], str] = {}
        admitted: list[ForecastChangeWitness] = []
        for row in sorted(rows, key=lambda item: (item["recorded_at"], item["watermark"])):
            event = _event_key(row)
            if event in pending or event in conflicting:
                continue
            ref = f"inventory-observation:{row['observation_id']}"
            if ref == previous_refs.get(event):
                continue
            admitted.append(
                ForecastChangeWitness(
                    observation_ref=ref,
                    correction_of=previous_refs.get(event),
                    idempotency_key=row["idempotency_key"],
                    scope_ref=row["scope_ref"],
                    subject_ref=row["subject_ref"],
                    subject_type=row["subject_type"],
                    source_identity=row["source_identity"],
                    source_event_id=row["source_event_id"],
                    source_revision=row["source_revision"],
                    observation_kind=row["observation_kind"],
                    mutation_kind=row["mutation_kind"],
                    operation=row["operation"],
                    operation_status=row["operation_status"],
                    effective_at=row["effective_at"],
                    recorded_at=row["recorded_at"],
                )
            )
            previous_refs[event] = ref
        admitted.sort(key=lambda item: (item.effective_at, item.recorded_at, item.observation_ref))
        limitation = (
            "result_limit"
            if not exhausted
            else "conflicting_event"
            if conflicting
            else "pending_event"
            if pending
            else "start_checkpoint_unverified"
        )

        def event_ids(keys: set[tuple[str, str]]) -> tuple[str, ...]:
            return tuple(sorted(f"{source}:{event}" for source, event in keys))

        return ForecastChangeHistoryResult(
            changes=tuple(admitted),
            coverage=ForecastChangeCoverage(
                complete=False,
                limitation=limitation,
                scope_ref=query.scope_ref,
                subject_ref=query.subject_ref,
                start_at=query.start_at,
                end_at=query.end_at,
                known_at=query.known_at,
                fence_watermark=fence,
            ),
            exhausted=exhausted,
            pending_event_ids=event_ids(pending),
            duplicate_event_ids=event_ids(duplicates),
            conflicting_event_ids=event_ids(conflicting),
        )


__all__ = [
    "ForecastChangeCoverage",
    "ForecastChangeHistoryResult",
    "ForecastChangeHistoryWitness",
    "ForecastChangeWitness",
]
