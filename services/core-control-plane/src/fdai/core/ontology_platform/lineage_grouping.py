"""Deterministic nearest-container grouping over lineage rows."""

from __future__ import annotations

import json
from collections.abc import Mapping

from .query_values import QueryRow, QueryTable

_MAX_GROUPS = 1_000


def count_by_nearest_container(table: QueryTable, *, limit: int) -> QueryTable:
    """Count each member under its nearest root and account equal-depth ties.

    Input rows are lineage candidates with ``member_id``, ``root_id``, ``depth``,
    ``path_evidence``, and ``source_generation`` values. A member with two nearest
    roots at the same depth is excluded from every root and contributes to the
    ``ambiguous_membership`` row.
    """

    candidates: dict[str, list[_Candidate]] = {}
    generations: set[str] = set()
    for row in table.rows:
        candidate = _candidate(row.values)
        candidates.setdefault(candidate.member_id, []).append(candidate)
        generations.add(candidate.source_generation)
    if not candidates:
        # No member reached a container of the kind, so every group count is zero.
        return QueryTable(
            rows=(),
            complete=table.complete,
            truncation_reason=table.truncation_reason,
            numeric_fields=("value", "ambiguous_membership"),
            source_generation=table.source_generation,
        )
    if len(generations) != 1:
        raise ValueError("lineage grouping requires exactly one source generation")
    grouped: dict[str, int] = {}
    ambiguous = 0
    for member_id, member_candidates in candidates.items():
        del member_id
        nearest_depth = min(item.depth for item in member_candidates)
        nearest = [item for item in member_candidates if item.depth == nearest_depth]
        roots = {item.root_id for item in nearest}
        if len(roots) != 1:
            ambiguous += 1
            continue
        root = next(iter(roots))
        grouped[root] = grouped.get(root, 0) + 1
    rows = [
        QueryRow.from_values(
            f"container-group:{root_id}",
            {
                "group": {"lineage.nearest_container": root_id},
                "operation": "count_by_nearest_container",
                "value": count,
            },
        )
        for root_id, count in sorted(grouped.items())
    ]
    if ambiguous:
        rows.append(
            QueryRow.from_values(
                "ambiguous_membership",
                {
                    "group": {"lineage.nearest_container": "ambiguous_membership"},
                    "operation": "count_by_nearest_container",
                    "value": ambiguous,
                    "ambiguous_membership": ambiguous,
                },
            )
        )
    if len(rows) > _MAX_GROUPS:
        raise ValueError("lineage grouping exceeds the maximum group count")
    limited = len(rows) > limit
    return QueryTable(
        rows=tuple(rows[:limit]),
        complete=table.complete and not limited,
        truncation_reason="result_limit" if limited else table.truncation_reason,
        numeric_fields=("value", "ambiguous_membership"),
        source_generation=next(iter(generations), None),
        # Only a complete input gives an exact group count; a cut input states none.
        total_rows=len(rows) if limited and table.complete else None,
    )


class _Candidate:
    def __init__(
        self,
        *,
        member_id: str,
        root_id: str,
        depth: int,
        path_evidence: str,
        source_generation: str,
    ) -> None:
        self.member_id = member_id
        self.root_id = root_id
        self.depth = depth
        self.path_evidence = path_evidence
        self.source_generation = source_generation


def _candidate(values: Mapping[str, object]) -> _Candidate:
    member_id = _text(values, "member_id")
    root_id = _text(values, "root_id")
    source_generation = _text(values, "source_generation")
    path_evidence = _text(values, "path_evidence")
    depth = values.get("depth")
    if isinstance(depth, bool) or not isinstance(depth, int) or depth < 1:
        raise ValueError("lineage grouping depth MUST be a positive integer")
    # Keep path evidence machine-readable and deterministic; it is evidence, not grouping logic.
    try:
        parsed = json.loads(path_evidence)
    except json.JSONDecodeError as exc:
        raise ValueError("lineage grouping path evidence MUST be JSON") from exc
    if not isinstance(parsed, list) or not parsed:
        raise ValueError("lineage grouping path evidence MUST be a non-empty list")
    return _Candidate(
        member_id=member_id,
        root_id=root_id,
        depth=depth,
        path_evidence=path_evidence,
        source_generation=source_generation,
    )


def _text(values: Mapping[str, object], key: str) -> str:
    value = values.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"lineage grouping {key} MUST be a non-empty string")
    return value


__all__ = ["count_by_nearest_container"]
