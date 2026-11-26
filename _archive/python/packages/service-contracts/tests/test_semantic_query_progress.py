"""Semantic query progress contract tests."""

from __future__ import annotations

import pytest
from fdai_service_contracts import (
    JsonSchemaContractValidator,
    PackageResourceSchemaRegistry,
    SemanticQueryProgress,
)
from pydantic import ValidationError


def _progress(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "schema_version": "1.0.0",
        "request_id": "request-1",
        "session_id": "session-1",
        "turn_id": "turn-1",
        "turn_sequence": 1,
        "progress_sequence": 1,
        "node_id": "current-state-target",
        "node_kind": "object_set",
        "capability": "query.object_set",
        "arguments": {"object_type": "Resource"},
        "status": "running",
        "step_index": 1,
        "step_total": 2,
        "depends_on": [],
        "started_at": "2026-08-26T11:00:00Z",
        "execution_authority": False,
    }
    value.update(overrides)
    return value


def test_semantic_query_progress_accepts_running_and_terminal_steps() -> None:
    running = SemanticQueryProgress.model_validate(_progress())
    completed = SemanticQueryProgress.model_validate(
        _progress(
            progress_sequence=2,
            status="completed",
            completed_at="2026-08-26T11:00:01Z",
            duration_ms=1000,
            evidence_refs=["ontology-object-set:current-state-target:1"],
        )
    )

    assert running.completed_at is None
    assert running.arguments == {"object_type": "Resource"}
    assert completed.status == "completed"
    assert completed.execution_authority is False
    validator = JsonSchemaContractValidator(PackageResourceSchemaRegistry())
    validator.validate(
        "semantic-query-progress",
        running.model_dump(mode="json"),
        version="1.0.0",
    )
    validator.validate(
        "semantic-query-progress",
        completed.model_dump(mode="json"),
        version="1.0.0",
    )


@pytest.mark.parametrize(
    ("updates", "match"),
    (
        ({"execution_authority": True}, "Input should be False"),
        ({"step_index": 3}, "step index"),
        ({"status": "completed"}, "terminal progress"),
        (
            {
                "status": "running",
                "completed_at": "2026-08-26T11:00:01Z",
            },
            "running progress",
        ),
    ),
)
def test_semantic_query_progress_rejects_invalid_lifecycle(
    updates: dict[str, object],
    match: str,
) -> None:
    with pytest.raises(ValidationError, match=match):
        SemanticQueryProgress.model_validate(_progress(**updates))
