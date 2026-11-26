"""Catalog-driven bounded Azure Monitor Log Analytics KQL compiler and execution engine.

Allows agents to directly query any of the 867 public Azure Monitor Log Analytics
tables across all 12 categories without raw KQL interpolation. Enforces table and
column allowlists, case-insensitive ARM resource_id filtering, server-side timespan
bounds, row budgets, and read-only no-authority execution receipts.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from fdai.delivery.azure.monitor_log_catalog import (
    MonitorLogPublicCatalog,
    load_monitor_log_catalog,
)
from fdai.shared.providers.observation import LogQueryProvider


class MonitorLogFilterOperator(StrEnum):
    """Typed filter operators permitted in catalog-compiled Monitor Log KQL queries."""

    EQUALS = "equals"
    IN = "in"
    CONTAINS_CI = "contains_ci"
    NOT_EMPTY = "not_empty"


def _escape_kql_literal(value: str) -> str:
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in value) or len(value) > 512:
        raise ValueError("Monitor Log filter literal MUST be bounded printable text")
    escaped = value.replace("\\", "\\\\").replace("'", "\\'")
    return f"'{escaped}'"


@dataclass(frozen=True, slots=True)
class MonitorLogWherePredicate:
    """One validated column predicate for an Azure Monitor Log Analytics table query."""

    column: str
    operator: MonitorLogFilterOperator
    values: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.column.strip():
            raise ValueError("MonitorLogWherePredicate.column MUST be non-empty")
        if self.operator is MonitorLogFilterOperator.NOT_EMPTY:
            if self.values:
                raise ValueError("NOT_EMPTY predicate MUST NOT carry literal values")
        elif self.operator is MonitorLogFilterOperator.IN:
            if not 1 <= len(self.values) <= 64 or any(not v.strip() for v in self.values):
                raise ValueError("IN predicate MUST carry 1..64 non-empty values")
        else:
            if len(self.values) != 1 or not self.values[0].strip():
                raise ValueError(f"{self.operator.value} predicate MUST carry 1 non-empty value")


@dataclass(frozen=True, slots=True)
class MonitorCatalogQueryRequest:
    """Typed request to compile and execute a bounded query against any of the 867 Log tables."""

    table_name: str
    lookback_seconds: int = 900
    resource_id: str | None = None
    where_predicates: tuple[MonitorLogWherePredicate, ...] = ()
    project_columns: tuple[str, ...] = ()
    limit: int = 200

    def __post_init__(self) -> None:
        if not self.table_name.strip():
            raise ValueError("MonitorCatalogQueryRequest.table_name MUST be non-empty")
        if type(self.lookback_seconds) is not int or not 60 <= self.lookback_seconds <= 604_800:
            raise ValueError("MonitorCatalogQueryRequest.lookback_seconds MUST be in 60..604800")
        if self.resource_id is not None and not self.resource_id.strip():
            raise ValueError("MonitorCatalogQueryRequest.resource_id MUST be non-empty when set")
        if type(self.limit) is not int or not 1 <= self.limit <= 1000:
            raise ValueError("MonitorCatalogQueryRequest.limit MUST be an integer in 1..1000")
        if len(self.where_predicates) > 16:
            raise ValueError("MonitorCatalogQueryRequest.where_predicates MUST contain <= 16 items")


def compile_monitor_catalog_query(
    request: MonitorCatalogQueryRequest,
    *,
    catalog: MonitorLogPublicCatalog | None = None,
) -> str:
    """Compile a deterministic, injection-free KQL query for any of the 867 Log tables."""
    resolved_catalog = catalog or load_monitor_log_catalog()
    spec = resolved_catalog.get_table(request.table_name)
    allowed = frozenset(spec.allowed_columns)
    lines: list[str] = [spec.table_name]
    lines.append(
        "| extend _fdai_resource_id = tolower(tostring(coalesce("
        "column_ifexists('_ResourceId', ''), "
        "column_ifexists('ResourceId', ''), "
        "column_ifexists('ClusterId', ''))))"
    )
    if request.resource_id is not None:
        lit = _escape_kql_literal(request.resource_id.strip().lower())
        lines.append(f"| where _fdai_resource_id == {lit}")
    for pred in request.where_predicates:
        col = pred.column.strip()
        if col not in allowed:
            raise ValueError(f"Column {col!r} is not in allowed_columns for {spec.table_name}")
        expr = f"tostring(column_ifexists('{col}', ''))"
        if pred.operator is MonitorLogFilterOperator.NOT_EMPTY:
            lines.append(f"| where isnotempty({expr})")
        elif pred.operator is MonitorLogFilterOperator.EQUALS:
            lit = _escape_kql_literal(pred.values[0].strip())
            lines.append(f"| where tolower({expr}) == tolower({lit})")
        elif pred.operator is MonitorLogFilterOperator.IN:
            lits = [_escape_kql_literal(v.strip().lower()) for v in pred.values]
            lines.append(f"| where tolower({expr}) in ({', '.join(lits)})")
        elif pred.operator is MonitorLogFilterOperator.CONTAINS_CI:
            lit = _escape_kql_literal(pred.values[0].strip())
            lines.append(f"| where {expr} contains {lit}")
    if request.project_columns:
        proj_exprs: list[str] = [
            f"{spec.time_column}=column_ifexists('{spec.time_column}', datetime(null))",
            "resource_id=_fdai_resource_id",
        ]
        for col in request.project_columns:
            clean_col = col.strip()
            if clean_col not in allowed:
                raise ValueError(f"Project column {col!r} is not in allowed_columns")
            if clean_col != spec.time_column:
                proj_exprs.append(f"{clean_col}=column_ifexists('{clean_col}', '')")
        lines.append(f"| project {', '.join(proj_exprs)}")
    lines.append(f"| order by {spec.time_column} desc")
    lines.append(f"| take {request.limit}")
    return "\n".join(lines)


@dataclass(frozen=True, slots=True)
class MonitorCatalogQueryResult:
    """Bounded read-only result of one catalog-compiled Azure Monitor Log query."""

    table_name: str
    primary_category: str
    owner_agent: str
    compiled_kql: str
    query_digest: str
    rows: tuple[Mapping[str, Any], ...]
    truncated: bool
    observed_at: datetime
    execution_authority: bool = False

    def __post_init__(self) -> None:
        if type(self.execution_authority) is not bool or self.execution_authority:
            raise ValueError(
                "MonitorCatalogQueryResult MUST remain read-only (execution_authority=False)"
            )


class MonitorCatalogQueryEngine:
    """Execute catalog-compiled Monitor Log queries over any of the 867 public tables."""

    def __init__(
        self,
        *,
        provider: LogQueryProvider,
        catalog: MonitorLogPublicCatalog | None = None,
    ) -> None:
        self._provider = provider
        self._catalog = catalog or load_monitor_log_catalog()

    async def execute(
        self,
        request: MonitorCatalogQueryRequest,
        *,
        now: datetime | None = None,
    ) -> MonitorCatalogQueryResult:
        """Compile and execute a bounded Log Analytics query against any of the 867 tables."""
        spec = self._catalog.get_table(request.table_name)
        kql = compile_monitor_catalog_query(request, catalog=self._catalog)
        digest = "sha256:" + hashlib.sha256(kql.encode("utf-8")).hexdigest()
        until = (now or datetime.now(UTC)).astimezone(UTC)
        res = await self._provider.query_log(
            query=kql,
            window=f"PT{request.lookback_seconds}S",
            max_rows=request.limit,
        )
        return MonitorCatalogQueryResult(
            table_name=spec.table_name,
            primary_category=spec.primary_category,
            owner_agent=spec.owner_agent,
            compiled_kql=kql,
            query_digest=digest,
            rows=tuple(dict(r) for r in res.rows),
            truncated=res.truncated,
            observed_at=until,
        )


__all__ = [
    "MonitorCatalogQueryEngine",
    "MonitorCatalogQueryRequest",
    "MonitorCatalogQueryResult",
    "MonitorLogFilterOperator",
    "MonitorLogWherePredicate",
    "compile_monitor_catalog_query",
]
