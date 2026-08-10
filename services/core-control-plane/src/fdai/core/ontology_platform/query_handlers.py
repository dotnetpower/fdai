"""Built-in handlers for the closed generic ontology query algebra."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation, localcontext
from functools import partial
from typing import Any, Literal, cast

from fdai_service_contracts.ontology_query import OntologyQueryNode, QueryNodeKind

from .query_execution import QueryNodeResult
from .query_values import QueryRow, QueryTable, combine_incompleteness

_MAX_FIELDS = 64
_MAX_GROUP_FIELDS = 4
_MAX_ROWS = 1_000


class SetOperationNodeHandler:
    """Apply deterministic union, intersection, or subtraction by stable row id."""

    def __init__(self, operation: Literal["union", "intersection", "subtraction"]) -> None:
        self._operation = operation

    async def __call__(
        self,
        node: OntologyQueryNode,
        dependencies: Mapping[str, QueryNodeResult],
    ) -> QueryNodeResult:
        expected_kind = QueryNodeKind(self._operation)
        if node.kind is not expected_kind:
            raise ValueError("set operation handler is bound to the wrong node kind")
        tables = _dependency_tables(node, dependencies, minimum=2)
        if self._operation == "subtraction" and len(tables) != 2:
            raise ValueError("subtraction node requires exactly two dependencies")
        by_table = [dict((row.row_id, row) for row in table.rows) for table in tables]
        if self._operation == "union":
            selected_ids = set().union(*(set(rows) for rows in by_table))
        elif self._operation == "intersection":
            selected_ids = set(by_table[0]).intersection(*(set(rows) for rows in by_table[1:]))
        else:
            selected_ids = set(by_table[0]) - set(by_table[1])
        selected: list[QueryRow] = []
        for row_id in sorted(selected_ids):
            candidates = [rows[row_id] for rows in by_table if row_id in rows]
            if any(item.values_json != candidates[0].values_json for item in candidates[1:]):
                raise ValueError("set operation found conflicting payloads for one row id")
            selected.append(candidates[0])
        table = QueryTable(
            rows=tuple(selected),
            complete=all(item.complete for item in tables),
            truncation_reason=combine_incompleteness(tables),
        )
        return _table_result(table, dependencies)


class OrderNodeHandler:
    """Sort one bounded table by reviewed scalar paths and apply a hard limit."""

    async def __call__(
        self,
        node: OntologyQueryNode,
        dependencies: Mapping[str, QueryNodeResult],
    ) -> QueryNodeResult:
        table = _single_table(node, dependencies)
        raw_keys = node.arguments.get("keys")
        if not isinstance(raw_keys, list) or not 1 <= len(raw_keys) <= _MAX_GROUP_FIELDS:
            raise ValueError(f"order keys MUST contain 1 to {_MAX_GROUP_FIELDS} entries")
        keys: list[tuple[str, bool]] = []
        for raw_key in raw_keys:
            if not isinstance(raw_key, dict) or set(raw_key) != {"field", "direction"}:
                raise ValueError("order key MUST contain only field and direction")
            field = _field_name(raw_key["field"])
            direction = raw_key["direction"]
            if direction not in {"ascending", "descending"}:
                raise ValueError("order direction MUST be ascending or descending")
            keys.append((field, direction == "descending"))
        rows = list(table.rows)
        for field, reverse in reversed(keys):
            values = [_scalar_sort_value(_path_value(row.values, field)) for row in rows]
            if len({kind for kind, _value in values}) > 1:
                raise ValueError("order field values MUST have one scalar type")
            rows.sort(
                key=partial(_row_sort_value, path=field),
                reverse=reverse,
            )
        limit = _limit(node.arguments)
        limited = len(rows) > limit
        reason = "result_limit" if limited else table.truncation_reason
        result = QueryTable(
            rows=tuple(rows[:limit]),
            complete=table.complete and not limited,
            truncation_reason=reason,
        )
        return _table_result(result, dependencies)


class ProjectNodeHandler:
    """Project reviewed field paths without changing source row identity."""

    async def __call__(
        self,
        node: OntologyQueryNode,
        dependencies: Mapping[str, QueryNodeResult],
    ) -> QueryNodeResult:
        table = _single_table(node, dependencies)
        raw_fields = node.arguments.get("fields")
        if not isinstance(raw_fields, list) or not 1 <= len(raw_fields) <= _MAX_FIELDS:
            raise ValueError(f"project fields MUST contain 1 to {_MAX_FIELDS} entries")
        fields = tuple(_field_name(item) for item in raw_fields)
        if len(fields) != len(set(fields)):
            raise ValueError("project fields MUST be unique")
        rows = tuple(
            QueryRow.from_values(
                row.row_id,
                {field: _path_value(row.values, field) for field in fields},
            )
            for row in table.rows
        )
        result = QueryTable(
            rows=rows,
            complete=table.complete,
            truncation_reason=table.truncation_reason,
        )
        return _table_result(result, dependencies)


class AggregateNodeHandler:
    """Compute bounded count or exact decimal aggregates over one table."""

    async def __call__(
        self,
        node: OntologyQueryNode,
        dependencies: Mapping[str, QueryNodeResult],
    ) -> QueryNodeResult:
        table = _single_table(node, dependencies)
        operation = node.arguments.get("operation")
        if operation not in {"count", "sum", "minimum", "maximum", "average"}:
            raise ValueError("aggregate operation is unsupported")
        field_raw = node.arguments.get("field")
        if operation == "count":
            if field_raw is not None:
                raise ValueError("count aggregate MUST NOT declare field")
            field = None
        else:
            field = _field_name(field_raw)
        raw_group_by = node.arguments.get("group_by", [])
        if not isinstance(raw_group_by, list) or len(raw_group_by) > _MAX_GROUP_FIELDS:
            raise ValueError(f"aggregate group_by exceeds {_MAX_GROUP_FIELDS} fields")
        group_by = tuple(_field_name(item) for item in raw_group_by)
        if len(group_by) != len(set(group_by)):
            raise ValueError("aggregate group_by fields MUST be unique")
        groups: dict[str, tuple[dict[str, object], list[QueryRow]]] = {}
        for row in table.rows:
            group_values = {name: _path_value(row.values, name) for name in group_by}
            group_key = json.dumps(
                group_values,
                allow_nan=False,
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            )
            groups.setdefault(group_key, (group_values, []))[1].append(row)
        if not groups and not group_by:
            groups["{}"] = ({}, [])
        aggregate_rows: list[QueryRow] = []
        for group_key, (group_values, rows) in sorted(groups.items()):
            value: object
            if operation == "count":
                value = len(rows)
            else:
                if field is None:  # pragma: no cover - operation validation invariant
                    raise RuntimeError("numeric aggregate field is unavailable")
                numbers = tuple(_decimal(_path_value(row.values, field)) for row in rows)
                if not numbers:
                    raise ValueError("numeric aggregate requires at least one row")
                if operation == "sum":
                    calculated = sum(numbers, Decimal(0))
                elif operation == "minimum":
                    calculated = min(numbers)
                elif operation == "maximum":
                    calculated = max(numbers)
                else:
                    with localcontext() as context:
                        context.prec = 128
                        calculated = sum(numbers, Decimal(0)) / Decimal(len(numbers))
                value = _decimal_text(calculated)
            row_id = "aggregate:" + _sha256(group_key)
            aggregate_rows.append(
                QueryRow.from_values(
                    row_id,
                    {"group": group_values, "operation": operation, "value": value},
                )
            )
        limit = _limit(node.arguments)
        limited = len(aggregate_rows) > limit
        result = QueryTable(
            rows=tuple(aggregate_rows[:limit]),
            complete=table.complete and not limited,
            truncation_reason="result_limit" if limited else table.truncation_reason,
        )
        return _table_result(result, dependencies)


def _dependency_tables(
    node: OntologyQueryNode,
    dependencies: Mapping[str, QueryNodeResult],
    *,
    minimum: int,
) -> tuple[QueryTable, ...]:
    if len(dependencies) < minimum or set(dependencies) != set(node.depends_on):
        raise ValueError("query node dependencies do not match its declared inputs")
    values = tuple(dependencies[item].value for item in node.depends_on)
    if not all(isinstance(value, QueryTable) for value in values):
        raise TypeError("query node dependencies MUST be QueryTable values")
    return cast(tuple[QueryTable, ...], values)


def _single_table(
    node: OntologyQueryNode,
    dependencies: Mapping[str, QueryNodeResult],
) -> QueryTable:
    if len(dependencies) != 1:
        return _fail()
    return _dependency_tables(node, dependencies, minimum=1)[0]


def _fail() -> QueryTable:
    raise ValueError("query node requires exactly one dependency")


def _table_result(
    table: QueryTable,
    dependencies: Mapping[str, QueryNodeResult],
) -> QueryNodeResult:
    return QueryNodeResult(
        value=table,
        evidence_refs=_evidence_refs(dependencies) + (f"ontology-query-table:{table.digest}",),
    )


def _evidence_refs(dependencies: Mapping[str, QueryNodeResult]) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            evidence_ref
            for result in dependencies.values()
            for evidence_ref in result.evidence_refs
        )
    )


def _field_name(value: object) -> str:
    if not isinstance(value, str) or not value or len(value) > 256:
        raise ValueError("query field MUST contain between 1 and 256 characters")
    parts = value.split(".")
    if any(not part or not part.replace("_", "").replace("-", "").isalnum() for part in parts):
        raise ValueError("query field MUST be a dot-separated identifier")
    return value


def _path_value(values: Mapping[str, Any], path: str) -> object:
    current: object = values
    for part in path.split("."):
        if not isinstance(current, Mapping) or part not in current:
            raise ValueError(f"query field {path!r} is absent")
        current = current[part]
    return current


def _scalar_sort_value(value: object) -> tuple[str, str | int | float]:
    if isinstance(value, bool):
        return "boolean", int(value)
    if isinstance(value, str):
        return "string", value
    if isinstance(value, int):
        return "number", value
    if isinstance(value, float):
        return "number", value
    raise ValueError("order fields MUST contain scalar string, number, or boolean values")


def _row_sort_value(row: QueryRow, *, path: str) -> str | int | float:
    return _scalar_sort_value(_path_value(row.values, path))[1]


def _limit(arguments: Mapping[str, Any]) -> int:
    value = arguments.get("limit", _MAX_ROWS)
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= _MAX_ROWS:
        raise ValueError(f"query limit MUST be in [1, {_MAX_ROWS}]")
    return cast(int, value)


def _decimal(value: object) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("numeric aggregate field MUST contain numbers")
    try:
        number = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError("numeric aggregate field MUST contain numbers") from exc
    if not number.is_finite():
        raise ValueError("numeric aggregate field MUST be finite")
    if len(number.as_tuple().digits) > 128 or abs(number.adjusted()) > 128:
        raise ValueError("numeric aggregate field exceeds decimal bounds")
    return number


def _decimal_text(value: Decimal) -> str:
    normalized = value.normalize()
    text = format(normalized, "f")
    return "0" if text in {"-0", ""} else text


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


__all__ = [
    "AggregateNodeHandler",
    "OrderNodeHandler",
    "ProjectNodeHandler",
    "SetOperationNodeHandler",
]
