"""PostgreSQL read projections owned by the independent Operator Service."""

from __future__ import annotations

import base64
import binascii
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final, cast

import psycopg
from fdai_service_contracts import (
    AgentActivityQuery,
    AuditQuery,
    HilQueueProjection,
    HilQueueQuery,
    IncidentAttentionProjection,
    IncidentAttentionQuery,
    IncidentQuery,
    JsonObject,
    JsonProjection,
    PageProjection,
)
from psycopg.rows import dict_row

from fdai_operator_service.activity_projection import durable_activity_projection
from fdai_operator_service.postgres_sql import (
    AGENT_INVENTORY_ACTIVITY_SQL,
    AGENT_OBSERVATION_ACTIVITY_SQL,
    AGENT_ONTOLOGY_ACTIVITY_SQL,
    AGENT_READ_ACTIVITY_SQL,
    AUDIT_PAGE_SQL,
    HIL_COUNT_SQL,
    HIL_PAGE_SQL,
    INCIDENT_PAGE_SQL,
    KPI_SAMPLE_SQL,
    LLM_USAGE_CONVERSATIONS_SQL,
    LLM_USAGE_RECORDS_SQL,
    LLM_USAGE_SUMMARIES_SQL,
)
from fdai_operator_service.projection_logic import (
    KPI_SAMPLE_LIMIT,
    LLM_USAGE_DETAIL_LIMIT,
    audit_item,
    dashboard_kpi,
    hil_item,
    incident_summary,
    llm_usage_projection,
    rule_fire_trace,
)
from fdai_operator_service.projections import ProjectionUnavailableError
from fdai_operator_service.rca_projection import rca_view

INCIDENT_HISTORY_LIMIT: Final = 100
HIL_KEY_PATTERN: Final = "hil_park:%"


@dataclass(frozen=True, slots=True)
class PostgresOperatorReadModelConfig:
    """Bounded PostgreSQL connection and statement settings."""

    dsn: str
    statement_timeout_ms: int = 20_000
    connect_timeout_s: int = 10

    def __post_init__(self) -> None:
        if not self.dsn.strip():
            raise ValueError("PostgreSQL DSN MUST be non-empty")
        _psycopg_dsn(self.dsn)
        if self.statement_timeout_ms < 1 or self.connect_timeout_s < 1:
            raise ValueError("PostgreSQL timeouts MUST be positive")


class PostgresOperatorReadModel:
    """Read immutable Operator projections from ``audit_log`` and ``state_kv``."""

    def __init__(self, config: PostgresOperatorReadModelConfig) -> None:
        self._config = config

    async def list_agent_activity(self, query: AgentActivityQuery) -> JsonProjection:
        """Merge bounded durable scan, ontology, and resource-state read sources."""
        try:
            payload = durable_activity_projection(
                inventory_rows=await self._fetch_all(
                    AGENT_INVENTORY_ACTIVITY_SQL,
                    {"limit": query.limit},
                ),
                ontology_rows=await self._fetch_all(AGENT_ONTOLOGY_ACTIVITY_SQL, {}),
                read_rows=await self._fetch_all(
                    AGENT_READ_ACTIVITY_SQL,
                    {"limit": query.limit},
                ),
                observation_rows=await self._fetch_all(
                    AGENT_OBSERVATION_ACTIVITY_SQL,
                    {"limit": query.limit},
                ),
                limit=query.limit,
            )
        except (TypeError, ValueError) as exc:
            raise ProjectionUnavailableError(
                "durable operational activity projection is malformed"
            ) from exc
        return JsonProjection(cast(JsonObject, payload))

    async def list_audit(self, query: AuditQuery) -> PageProjection:
        cutoff = _positive_cursor(query.cursor)
        rows = await self._fetch_all(
            AUDIT_PAGE_SQL,
            {
                "cutoff": cutoff,
                "correlation_id": query.correlation_id,
                "fetch": query.limit + 1,
            },
        )
        items = tuple(audit_item(row) for row in rows[: query.limit])
        next_cursor = str(items[-1]["seq"]) if len(rows) > query.limit and items else None
        return PageProjection(items=items, next_cursor=next_cursor)

    async def dashboard_metrics(self) -> JsonProjection:
        rows = await self._fetch_all(KPI_SAMPLE_SQL, {"limit": KPI_SAMPLE_LIMIT})
        pending_rows = await self._fetch_all(
            HIL_COUNT_SQL,
            {"key_pattern": HIL_KEY_PATTERN},
        )
        pending = int(pending_rows[0]["total_count"]) if pending_rows else 0
        return JsonProjection(dashboard_kpi(rows, hil_pending=pending))

    async def llm_usage(self, range_start: datetime, range_end: datetime) -> JsonProjection:
        """Read bounded measured invocation facts and exact aggregate summaries."""
        parameters: dict[str, object] = {
            "range_start": range_start,
            "range_end": range_end,
        }
        summaries = await self._fetch_all(LLM_USAGE_SUMMARIES_SQL, parameters)
        conversations = await self._fetch_all(
            LLM_USAGE_CONVERSATIONS_SQL,
            {**parameters, "fetch": LLM_USAGE_DETAIL_LIMIT + 1},
        )
        records = await self._fetch_all(
            LLM_USAGE_RECORDS_SQL,
            {**parameters, "fetch": LLM_USAGE_DETAIL_LIMIT + 1},
        )
        return JsonProjection(
            llm_usage_projection(
                range_start=range_start,
                range_end=range_end,
                summary_rows=summaries,
                conversation_rows=conversations,
                record_rows=records,
            )
        )

    async def list_hil_queue(self, query: HilQueueQuery) -> HilQueueProjection:
        if not query.include_details:
            rows = await self._fetch_all(
                HIL_COUNT_SQL,
                {"key_pattern": HIL_KEY_PATTERN},
            )
            return HilQueueProjection(
                items=(),
                total=int(rows[0]["total_count"]) if rows else 0,
            )
        rows = await self._fetch_all(
            HIL_PAGE_SQL,
            {
                "key_pattern": HIL_KEY_PATTERN,
                "search": query.search,
                "search_pattern": f"%{query.search}%" if query.search else None,
                "limit": query.limit,
            },
        )
        items: list[JsonObject] = []
        for row in rows:
            projected = hil_item(row)
            if projected is None:
                raise ProjectionUnavailableError("authoritative PostgreSQL HIL row is malformed")
            items.append(projected)
        total = int(rows[0]["total_count"]) if rows else 0
        return HilQueueProjection(items=tuple(items), total=total)

    async def list_incidents(self, query: IncidentQuery) -> PageProjection:
        page, _ = await self._incident_page(query)
        return page

    async def incident_attention(
        self, query: IncidentAttentionQuery
    ) -> IncidentAttentionProjection | None:
        page, snapshot_seq = await self._incident_page(
            IncidentQuery(status="active", limit=query.limit)
        )
        if query.after_seq is not None and snapshot_seq <= query.after_seq:
            return None
        incidents = [
            {
                key: item[key]
                for key in (
                    "incident_id",
                    "correlation_id",
                    "title",
                    "severity",
                    "status",
                    "opened_at",
                    "last_updated_at",
                )
            }
            for item in page.items
            if item.get("incident_id") is not None
        ]
        return IncidentAttentionProjection(
            sequence=snapshot_seq,
            payload=cast(
                JsonObject,
                {
                    "event": "incident_attention.snapshot",
                    "ts": datetime.now(UTC).isoformat(),
                    "incidents": incidents,
                },
            ),
        )

    async def get_rca(self, correlation_id: str) -> JsonProjection | None:
        page = await self.list_audit(AuditQuery(limit=500, correlation_id=correlation_id))
        payload = rca_view(correlation_id, page.items)
        return JsonProjection(payload) if payload is not None else None

    async def get_rule_fire_trace(self, correlation_id: str) -> JsonProjection | None:
        page = await self.list_audit(AuditQuery(limit=500, correlation_id=correlation_id))
        payload = rule_fire_trace(correlation_id, page.items)
        return JsonProjection(payload) if payload is not None else None

    async def _incident_page(self, query: IncidentQuery) -> tuple[PageProjection, int]:
        cursor = _decode_incident_cursor(
            query.cursor,
            status=query.status,
            vertical=query.vertical,
        )
        rows = await self._fetch_all(
            INCIDENT_PAGE_SQL,
            {
                "snapshot_seq": cursor[0] if cursor else None,
                "before_seq": cursor[1] if cursor else None,
                "status": query.status,
                "vertical": query.vertical,
                "correlation_id": query.correlation_id,
                "fetch": query.limit + 1,
                "history_limit": INCIDENT_HISTORY_LIMIT,
            },
        )
        grouped = _group_incident_rows(rows)
        visible = grouped[: query.limit]
        items = tuple(_without_last_seq(incident_summary(group)) for group in visible)
        snapshot_seq = int(rows[0]["snapshot_seq"]) if rows else cursor[0] if cursor else 0
        next_cursor = None
        if len(grouped) > query.limit and visible:
            next_cursor = _encode_incident_cursor(
                snapshot_seq,
                int(visible[-1][-1]["group_last_seq"]),
                query.status,
                query.vertical,
            )
        return PageProjection(items=items, next_cursor=next_cursor), snapshot_seq

    async def _fetch_all(
        self,
        statement: str,
        parameters: Mapping[str, object],
    ) -> list[dict[str, Any]]:
        try:
            async with await psycopg.AsyncConnection.connect(
                _psycopg_dsn(self._config.dsn),
                row_factory=dict_row,
                connect_timeout=self._config.connect_timeout_s,
            ) as connection:
                async with connection.transaction():
                    await connection.execute(
                        "SELECT set_config('statement_timeout', %s, true)",
                        (str(self._config.statement_timeout_ms),),
                    )
                    cursor = await connection.execute(statement, parameters)
                    return list(await cursor.fetchall())
        except psycopg.Error as exc:
            raise ProjectionUnavailableError(
                "authoritative PostgreSQL projection is unavailable"
            ) from exc


def _positive_cursor(value: str | None) -> int | None:
    if value is None or value == "":
        return None
    try:
        cursor = int(value)
    except ValueError as exc:
        raise ValueError(f"invalid cursor: {value!r}") from exc
    if cursor < 1:
        raise ValueError(f"invalid cursor: {value!r}")
    return cursor


def _psycopg_dsn(value: str) -> str:
    prefix = "postgresql+psycopg://"
    normalized = f"postgresql://{value[len(prefix) :]}" if value.startswith(prefix) else value
    if normalized in {"postgres://", "postgresql://"}:
        raise ValueError("PostgreSQL DSN MUST include a connection target")
    return normalized


def _encode_incident_cursor(
    snapshot_seq: int,
    before_seq: int,
    status: str,
    vertical: str | None,
) -> str:
    payload = json.dumps(
        {
            "v": 1,
            "snapshot_seq": snapshot_seq,
            "before_seq": before_seq,
            "status": status,
            "vertical": vertical,
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return base64.urlsafe_b64encode(payload).rstrip(b"=").decode("ascii")


def _decode_incident_cursor(
    value: str | None,
    *,
    status: str,
    vertical: str | None,
) -> tuple[int, int] | None:
    if not value:
        return None
    try:
        padded = value + "=" * (-len(value) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded).decode())
        snapshot_seq = payload["snapshot_seq"]
        before_seq = payload["before_seq"]
        if (
            payload.get("v") != 1
            or payload.get("status") != status
            or payload.get("vertical") != vertical
            or not isinstance(snapshot_seq, int)
            or isinstance(snapshot_seq, bool)
            or snapshot_seq < 0
            or not isinstance(before_seq, int)
            or isinstance(before_seq, bool)
            or before_seq < 1
        ):
            raise ValueError
    except (binascii.Error, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("invalid incident cursor or status mismatch") from exc
    return snapshot_seq, before_seq


def _group_incident_rows(
    rows: Sequence[Mapping[str, Any]],
) -> list[list[Mapping[str, Any]]]:
    ordered: list[list[Mapping[str, Any]]] = []
    indexes: dict[str, int] = {}
    for row in rows:
        raw_correlation_id = row.get("normalized_correlation_id")
        if not isinstance(raw_correlation_id, str):
            continue
        correlation_id = raw_correlation_id.strip()
        if not correlation_id or correlation_id.lower() in {"none", "null"}:
            continue
        index = indexes.get(correlation_id)
        if index is None:
            indexes[correlation_id] = len(ordered)
            ordered.append([])
            index = len(ordered) - 1
        ordered[index].append(row)
    return ordered


def _without_last_seq(item: JsonObject) -> JsonObject:
    return {key: value for key, value in item.items() if key != "last_seq"}


__all__ = ["PostgresOperatorReadModel", "PostgresOperatorReadModelConfig"]
