"""A compiled list of another ObjectType is never presented as a list of Resources."""

from __future__ import annotations

from typing import Any, cast

from fdai_core_service.semantic_turn_processor import _render_general_query_answer
from fdai_service_contracts.semantic_turn import SemanticTurnRequest

from tests.test_semantic_turn_processor import _request


def _output(values: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "node_id": "g1-collection",
        "rows": [{"row_id": f"row-{index}", "values": item} for index, item in enumerate(values)],
        "returned_rows": len(values),
        "total_rows": len(values),
        "source_complete": True,
        "source_truncation_reason": None,
        "display_truncated": False,
    }


def _answer(locale: str, output: dict[str, Any]) -> str:
    request = cast(dict[str, object], _request(locale=locale)["semantic_turn"])
    return _render_general_query_answer(
        SemanticTurnRequest.model_validate(request),
        [output],
        output_shape="resource_list",
        subject_constraints=("Incident",),
        measure_concepts=("reasoning.select",),
    )


def test_incident_rows_render_as_verified_rows_instead_of_unnamed_resources() -> None:
    incidents = _output(
        [
            {"id": "inc-1", "status": "open", "severity": "sev2"},
            {"id": "inc-2", "status": "open", "severity": "sev3"},
        ]
    )
    resources = _output([{"name": "vm-app-01", "type": "compute.vm", "status": "running"}])

    english = _answer("en", incidents)
    korean = _answer("ko", incidents)

    assert "matching Resources" not in english and "name unavailable" not in english
    assert "Verified 2 of 2 rows." in english
    assert "inc-1" in english and "inc-2" in english
    assert "일치하는 리소스" not in korean
    # A row that names a Resource keeps the Resource list.
    assert "## 1 matching Resources" in _answer("en", resources)
