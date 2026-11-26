"""Catalog-driven bounded Azure Resource Graph (ARG) query compiler and execution engine.

Allows agents (Huginn, Heimdall, Njord, Vidar) to directly query any of the 50 public
ARG tables and 1,908 / 3,405 ARM resource types using typed predicates without raw
KQL string interpolation. Enforces subscription scope, column allowlists, row and
byte budgets, and read-only no-authority execution receipts.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Final

import httpx

from fdai.delivery.azure.arg_public_catalog import ArgPublicCatalog, load_arg_public_catalog
from fdai.shared.providers.workload_identity import WorkloadIdentity

_ARG_ENDPOINT: Final[str] = (
    "https://management.azure.com/providers/Microsoft.ResourceGraph/resources"
)
_ARG_API_VERSION: Final[str] = "2022-10-01"
_ARM_AUDIENCE: Final[str] = "https://management.azure.com/.default"
_SUBSCRIPTION_RE: Final[re.Pattern[str]] = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
_SAFE_RG_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9._()-]{1,90}$")
_SAFE_PROP_PATH_RE: Final[re.Pattern[str]] = re.compile(
    r"^properties(?:\.[A-Za-z0-9_]{1,64}){1,6}$"
)


class ArgFilterOperator(StrEnum):
    """Typed filter operators permitted in catalog-compiled ARG KQL queries."""

    EQUALS = "equals"
    IN = "in"
    CONTAINS_CI = "contains_ci"
    STARTSWITH_CI = "startswith_ci"
    NOT_EMPTY = "not_empty"


def _escape_kql_literal(value: str) -> str:
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in value) or len(value) > 512:
        raise ValueError("ARG filter literal MUST be bounded printable text")
    escaped = value.replace("\\", "\\\\").replace("'", "\\'")
    return f"'{escaped}'"


@dataclass(frozen=True, slots=True)
class ArgWherePredicate:
    """One validated column or property-path predicate for an ARG table query."""

    column: str
    operator: ArgFilterOperator
    values: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.column.strip():
            raise ValueError("ArgWherePredicate.column MUST be non-empty")
        if self.operator is ArgFilterOperator.NOT_EMPTY:
            if self.values:
                raise ValueError("NOT_EMPTY predicate MUST NOT carry literal values")
        elif self.operator is ArgFilterOperator.IN:
            if not 1 <= len(self.values) <= 64 or any(not v.strip() for v in self.values):
                raise ValueError("IN predicate MUST carry 1..64 non-empty values")
        else:
            if len(self.values) != 1 or not self.values[0].strip():
                raise ValueError(f"{self.operator.value} predicate MUST carry exactly 1 value")


@dataclass(frozen=True, slots=True)
class ArgCatalogQueryRequest:
    """Typed request to compile and execute a bounded query against any of the 50 ARG tables."""

    table_name: str
    subscription_ids: tuple[str, ...]
    resource_types: tuple[str, ...] = ()
    resource_groups: tuple[str, ...] = ()
    where_predicates: tuple[ArgWherePredicate, ...] = ()
    project_columns: tuple[str, ...] = ()
    order_by_column: str = "id"
    order_descending: bool = False
    limit: int = 200

    def __post_init__(self) -> None:
        if not self.table_name.strip():
            raise ValueError("ArgCatalogQueryRequest.table_name MUST be non-empty")
        if not 1 <= len(self.subscription_ids) <= 64:
            raise ValueError("ArgCatalogQueryRequest.subscription_ids MUST contain 1..64 IDs")
        normalized_subs: list[str] = []
        for sub in self.subscription_ids:
            clean = sub.strip() if isinstance(sub, str) else ""
            if _SUBSCRIPTION_RE.fullmatch(clean) is None:
                raise ValueError(f"Invalid subscription_id in ArgCatalogQueryRequest: {sub!r}")
            normalized_subs.append(clean.lower())
        object.__setattr__(self, "subscription_ids", tuple(dict.fromkeys(normalized_subs)))
        for rg in self.resource_groups:
            if _SAFE_RG_RE.fullmatch(rg.strip()) is None:
                raise ValueError(f"Invalid resource_group in ArgCatalogQueryRequest: {rg!r}")
        if type(self.limit) is not int or not 1 <= self.limit <= 1000:
            raise ValueError("ArgCatalogQueryRequest.limit MUST be an integer in 1..1000")
        if type(self.order_descending) is not bool:
            raise ValueError("ArgCatalogQueryRequest.order_descending MUST be a boolean")
        if len(self.where_predicates) > 16:
            raise ValueError("ArgCatalogQueryRequest.where_predicates MUST contain <= 16 items")


def _validate_column_or_prop(column: str, allowed_columns: frozenset[str]) -> str:
    clean = column.strip()
    if clean in allowed_columns:
        return clean
    if _SAFE_PROP_PATH_RE.fullmatch(clean) is not None and "properties" in allowed_columns:
        return f"tostring({clean})"
    raise ValueError(f"Column {column!r} is not permitted for this ARG table")


def compile_arg_catalog_query(
    request: ArgCatalogQueryRequest,
    *,
    catalog: ArgPublicCatalog | None = None,
) -> str:
    """Compile a deterministic, injection-free KQL query for any of the 50 ARG tables."""
    resolved_catalog = catalog or load_arg_public_catalog()
    spec = resolved_catalog.get_table(request.table_name)
    allowed = frozenset(spec.allowed_columns)
    lines: list[str] = [spec.table_name]
    if request.resource_types:
        cleaned_types = []
        for rt in request.resource_types:
            clean_rt = rt.strip().lower()
            if not clean_rt or "/" not in clean_rt:
                raise ValueError(f"Invalid ARM resource_type filter: {rt!r}")
            cleaned_types.append(_escape_kql_literal(clean_rt))
        lines.append(f"| where tolower(type) in ({', '.join(cleaned_types)})")
    if request.resource_groups:
        rgs = [_escape_kql_literal(rg.strip().lower()) for rg in request.resource_groups]
        lines.append(f"| where tolower(resourceGroup) in ({', '.join(rgs)})")
    for pred in request.where_predicates:
        expr = _validate_column_or_prop(pred.column, allowed)
        if pred.operator is ArgFilterOperator.NOT_EMPTY:
            lines.append(f"| where isnotempty({expr})")
        elif pred.operator is ArgFilterOperator.EQUALS:
            lit = _escape_kql_literal(pred.values[0].strip())
            lines.append(f"| where tolower(tostring({expr})) == tolower({lit})")
        elif pred.operator is ArgFilterOperator.IN:
            lits = [_escape_kql_literal(v.strip().lower()) for v in pred.values]
            lines.append(f"| where tolower(tostring({expr})) in ({', '.join(lits)})")
        elif pred.operator is ArgFilterOperator.CONTAINS_CI:
            lit = _escape_kql_literal(pred.values[0].strip())
            lines.append(f"| where tostring({expr}) contains {lit}")
        elif pred.operator is ArgFilterOperator.STARTSWITH_CI:
            lit = _escape_kql_literal(pred.values[0].strip())
            lines.append(f"| where tostring({expr}) startswith {lit}")
    order_col = request.order_by_column.strip()
    if order_col not in allowed:
        raise ValueError(f"order_by_column {order_col!r} is not in allowed_columns")
    project_cols = request.project_columns or (
        "id",
        "name",
        "type",
        "location",
        "resourceGroup",
        "subscriptionId",
        "properties",
    )
    validated_projects: list[str] = []
    for col in project_cols:
        clean_col = col.strip()
        if clean_col not in allowed:
            raise ValueError(f"project column {col!r} is not in allowed_columns")
        if clean_col not in validated_projects:
            validated_projects.append(clean_col)
    if order_col not in validated_projects:
        validated_projects.append(order_col)
    lines.append(f"| project {', '.join(validated_projects)}")
    direction = "desc" if request.order_descending else "asc"
    lines.append(f"| order by {order_col} {direction}")
    lines.append(f"| take {request.limit}")
    return "\n".join(lines)


@dataclass(frozen=True, slots=True)
class ArgCatalogQueryResult:
    """Bounded read-only result of one catalog-compiled ARG table query."""

    table_name: str
    owner_agent: str
    domain: str
    compiled_kql: str
    query_digest: str
    rows: tuple[Mapping[str, Any], ...]
    truncated: bool
    observed_at: datetime
    execution_authority: bool = False

    def __post_init__(self) -> None:
        if type(self.execution_authority) is not bool or self.execution_authority:
            raise ValueError(
                "ArgCatalogQueryResult MUST remain read-only (execution_authority=False)"
            )


class ArgCatalogQueryEngine:
    """Execute catalog-compiled ARG queries across all 50 tables with strict read bounds."""

    def __init__(
        self,
        *,
        http: httpx.AsyncClient,
        identity: WorkloadIdentity,
        catalog: ArgPublicCatalog | None = None,
        timeout_seconds: float = 15.0,
        max_response_bytes: int = 2_000_000,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if (
            type(timeout_seconds) is bool
            or not math.isfinite(timeout_seconds)
            or not 0 < timeout_seconds <= 60
        ):
            raise ValueError("ArgCatalogQueryEngine timeout_seconds MUST be in (0, 60]")
        if type(max_response_bytes) is not int or not 1024 <= max_response_bytes <= 10_000_000:
            raise ValueError("ArgCatalogQueryEngine max_response_bytes MUST be in 1024..10000000")
        self._http = http
        self._identity = identity
        self._catalog = catalog or load_arg_public_catalog()
        self._timeout = timeout_seconds
        self._max_bytes = max_response_bytes
        self._clock = clock

    async def execute(self, request: ArgCatalogQueryRequest) -> ArgCatalogQueryResult:
        """Compile and execute a bounded ARG query for any of the 50 public ARG tables."""
        spec = self._catalog.get_table(request.table_name)
        kql = compile_arg_catalog_query(request, catalog=self._catalog)
        digest = "sha256:" + hashlib.sha256(kql.encode("utf-8")).hexdigest()
        token = await self._identity.get_token(_ARM_AUDIENCE)
        payload = {
            "subscriptions": list(request.subscription_ids),
            "query": kql,
            "options": {"$top": request.limit, "resultFormat": "objectArray"},
        }
        response = await self._http.post(
            _ARG_ENDPOINT,
            params={"api-version": _ARG_API_VERSION},
            json=payload,
            headers={"Authorization": f"Bearer {token.token}", "Accept": "application/json"},
            timeout=self._timeout,
            follow_redirects=False,
        )
        if response.status_code != 200 or len(response.content) > self._max_bytes:
            raise RuntimeError(
                f"ARG catalog query failed or exceeded byte budget: HTTP {response.status_code}"
            )
        body = json.loads(response.content)
        data = body.get("data")
        if not isinstance(data, list) or any(not isinstance(row, Mapping) for row in data):
            raise RuntimeError("ARG catalog query response data MUST be an objectArray")
        truncated = bool(body.get("$skipToken")) or len(data) > request.limit
        rows = tuple(dict(row) for row in data[: request.limit])
        return ArgCatalogQueryResult(
            table_name=spec.table_name,
            owner_agent=spec.owner_agent,
            domain=spec.domain,
            compiled_kql=kql,
            query_digest=digest,
            rows=rows,
            truncated=truncated,
            observed_at=self._clock(),
        )


__all__ = [
    "ArgCatalogQueryEngine",
    "ArgCatalogQueryRequest",
    "ArgCatalogQueryResult",
    "ArgFilterOperator",
    "ArgWherePredicate",
    "compile_arg_catalog_query",
]
