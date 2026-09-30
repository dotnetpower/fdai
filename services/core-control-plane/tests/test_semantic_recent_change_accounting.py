"""A recent change answer states exactly how many changed Resources its read did not list."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, cast

from fdai_core_service.semantic_turn_processor import _render_general_query_answer
from fdai_service_contracts.semantic_turn import SemanticTurnRequest

from tests.test_semantic_turn_processor import _request

NOW = datetime(2026, 9, 30, tzinfo=UTC)


def _output(total: int | None, rows: int = 20) -> dict[str, Any]:
    output: dict[str, Any] = {
        "node_id": "recent-resource-changes",
        "rows": [
            {
                "row_id": f"resource-{index}",
                "values": {
                    "subject_name": f"app-{index}",
                    "operation": "Microsoft.Web/sites/write",
                    "mutation_kind": "upsert",
                    "observation_kind": "change_hint",
                    "occurred_at": (NOW - timedelta(minutes=index)).isoformat(),
                    "source_identity": "azure_event_grid.resource_change",
                    "execution_authority": False,
                },
            }
            for index in range(rows)
        ],
        "returned_rows": rows,
        "total_rows": rows,
        "source_complete": total is None,
        "source_truncation_reason": None if total is None else "result_limit",
        "display_truncated": False,
    }
    if total is not None:
        output["source_total_rows"] = total
    return output


def _answer(locale: str, output: dict[str, Any]) -> str:
    request = cast(dict[str, object], _request(locale=locale)["semantic_turn"])
    return _render_general_query_answer(
        SemanticTurnRequest.model_validate(request),
        [output],
        output_shape="resource_changes",
        measure_concepts=("resource_change.observed",),
    )


def test_a_cut_change_read_states_its_exact_remaining_count() -> None:
    english = _answer("en", _output(57))
    korean = _answer("ko", _output(57))

    assert "- 37 of the 57 changed resources in this window are not listed." in english
    assert "- 이 기간에 변경된 리소스 57개 중 37개는 목록에 없습니다." in korean
    # A read that listed every change states no remaining count.
    assert "not listed" not in _answer("en", _output(None, rows=3))
