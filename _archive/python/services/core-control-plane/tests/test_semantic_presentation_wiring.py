"""Core semantic presentation metadata wiring regressions."""

from __future__ import annotations

from datetime import UTC, datetime
from types import MappingProxyType

from fdai.core.ontology_platform import QueryNodeResult, QueryPlanExecution
from fdai.core.ontology_platform.query_values import QueryRow, QueryTable
from fdai_core_service.semantic_turn_processor import _render_query_answer
from fdai_service_contracts import SemanticTurnRequest


def _request() -> SemanticTurnRequest:
    return SemanticTurnRequest.model_validate(
        {
            "utterance": "Show verified observations.",
            "principal": {"subject_id": "operator-1", "roles": ["Reader"]},
            "session_id": "session-1",
            "turn_id": "turn-1",
            "turn_sequence": 1,
            "locale": "en",
            "purpose": "operations-review",
            "deadline_at": datetime(2026, 8, 22, 1, 0, tzinfo=UTC),
            "execution_authority": False,
        }
    )


def _execution(rows: tuple[QueryRow, ...]) -> QueryPlanExecution:
    return QueryPlanExecution(
        plan_digest="sha256:" + ("a" * 64),
        status="completed",
        results=MappingProxyType(
            {
                "result": QueryNodeResult(
                    value=QueryTable(rows=rows, complete=True),
                    evidence_refs=("inventory:evidence-1",),
                )
            }
        ),
        receipts=(),
        output_node_ids=("result",),
    )


def test_query_renderer_wires_proven_semantics_into_terminal_context() -> None:
    rows = tuple(
        QueryRow.from_values(
            f"sample-{index}",
            {
                "timestamp": f"2026-08-22T00:0{index}:00Z",
                "metric": "requests",
                "unit": "count",
                "value": value,
            },
        )
        for index, value in enumerate((1, 3, 2))
    )

    answer, technical_details = _render_query_answer(
        _request(),
        _execution(rows),
        operation="select",
        output_shape="target_resource_metric_series",
    )

    assert answer is not None
    assert technical_details is not None
    assert technical_details["presentation_context"] == {
        "operation": "select",
        "output_shape": "target_resource_metric_series",
        "presentation_semantics": {"shape": "temporal_series", "fields": {}},
    }


def test_query_renderer_omits_ambiguous_semantics_from_terminal_context() -> None:
    rows = (
        QueryRow.from_values("category-a", {"category": "A", "value": 3}),
        QueryRow.from_values("category-b", {"category": "B", "value": 5}),
    )

    answer, technical_details = _render_query_answer(
        _request(),
        _execution(rows),
        operation="select",
        output_shape="aggregation_table",
    )

    assert answer is not None
    assert technical_details is not None
    presentation_context = technical_details["presentation_context"]
    assert isinstance(presentation_context, dict)
    assert "presentation_semantics" not in presentation_context
