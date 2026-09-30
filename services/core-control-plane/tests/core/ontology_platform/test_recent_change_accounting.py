"""A bounded change read states exactly how many changed Resources it does not list."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fdai.core.ontology_platform.functions import FunctionInvocationContext
from fdai.core.ontology_platform.query_source_handlers import _query_table
from fdai.core.ontology_platform.query_values import QueryRow, QueryTable
from fdai.core.ontology_platform.recent_resource_changes import (
    RECENT_RESOURCE_CHANGES_FUNCTION_NAME,
    RecentResourceChange,
    RecentResourceChangeRead,
    recent_resource_changes_function,
    recent_resource_changes_function_type,
)
from fdai.shared.contracts.models import CeilingRole
from fdai.shared.ontology.release import build_ontology_release

NOW = datetime(2026, 9, 30, tzinfo=UTC)


def _change(index: int) -> RecentResourceChange:
    return RecentResourceChange(
        subject_ref=f"resource-{index}",
        subject_name=f"resource-{index}",
        subject_type="container-app",
        operation="update",
        operation_status="succeeded",
        mutation_kind="upsert",
        observation_kind="change_hint",
        occurred_at=NOW - timedelta(minutes=index),
        source_identity="azure_event_grid.resource_change",
        evidence_ref=f"inventory-observation:observation-{index}",
    )


class _Reader:
    def __init__(self, read: RecentResourceChangeRead) -> None:
        self._read = read

    async def read_recent_resource_changes(self, **_arguments: Any) -> RecentResourceChangeRead:
        return self._read


async def _evaluate(read: RecentResourceChangeRead) -> dict[str, Any]:
    declaration = recent_resource_changes_function_type()
    release = build_ontology_release(function_types=(declaration,))
    evaluate = recent_resource_changes_function(release, reader=_Reader(read))
    result = await evaluate(
        {
            "start_at": (NOW - timedelta(days=1)).isoformat(),
            "end_at": NOW.isoformat(),
            "known_at": NOW.isoformat(),
            "limit": 20,
        },
        FunctionInvocationContext(
            caller_agent="Bragi",
            caller_role=CeilingRole.READER,
            purposes=("operations-review",),
        ),
    )
    assert isinstance(result, dict)
    return result


async def test_a_cut_read_keeps_the_exact_total_through_the_query_table() -> None:
    changes = tuple(_change(index) for index in range(20))
    cut = await _evaluate(RecentResourceChangeRead(changes, False, "result_limit", total=57))
    whole = await _evaluate(RecentResourceChangeRead(changes[:3], True, None, total=3))

    assert cut["total_rows"] == 57 and _query_table(cut).total_rows == 57
    # A complete read has nothing it does not list, so no total is added to its content.
    assert "total_rows" not in whole and _query_table(whole).total_rows is None
    assert RECENT_RESOURCE_CHANGES_FUNCTION_NAME == "query.recent_resource_changes"
    schema = recent_resource_changes_function_type().output_schema["properties"]
    assert schema["total_rows"] == {"type": "integer", "minimum": 0}


def test_a_table_total_never_undercounts_its_rows_or_contradicts_completeness() -> None:
    row = QueryRow.from_values("row-a", {"name": "a"})

    assert (
        json.loads(QueryTable((row,), False, "result_limit", total_rows=5).canonical_json())[
            "total_rows"
        ]
        == 5
    )
    for total, complete in ((0, False), (2, True), (True, False)):
        with pytest.raises(ValueError, match="total rows"):
            QueryTable((row,), complete, None if complete else "result_limit", total_rows=total)
