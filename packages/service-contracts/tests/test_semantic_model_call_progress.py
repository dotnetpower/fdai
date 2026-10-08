"""Model-call progress stays content-free, bounded, and consistent with its schema."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fdai_service_contracts.schema import (
    ContractValidationError,
    JsonSchemaContractValidator,
    PackageResourceSchemaRegistry,
)
from fdai_service_contracts.semantic_model_call_progress import SemanticModelCallProgress
from pydantic import ValidationError

_STARTED = datetime(2026, 10, 8, 6, 0, tzinfo=UTC)


def _record(**overrides: object) -> SemanticModelCallProgress:
    values: dict[str, object] = {
        "request_id": "request-1",
        "session_id": "session-1",
        "turn_id": "turn-1",
        "turn_sequence": 1,
        "progress_sequence": 1,
        "call_index": 1,
        "stage": "form",
        "status": "running",
        "model": "narrator-gpt-5-4-mini",
        "started_at": _STARTED,
    }
    values.update(overrides)
    return SemanticModelCallProgress.model_validate(values)


@pytest.mark.parametrize(
    "overrides",
    [
        {},
        {
            "status": "completed",
            "completed_at": _STARTED + timedelta(seconds=2),
            "duration_ms": 2000,
            "prompt_tokens": 5796,
            "completion_tokens": 211,
        },
        {"status": "failed", "completed_at": _STARTED, "duration_ms": 0, "model": None},
    ],
)
def test_each_lifecycle_record_matches_its_schema(overrides: dict[str, object]) -> None:
    payload = _record(**overrides).model_dump(mode="json")
    validator = JsonSchemaContractValidator(PackageResourceSchemaRegistry())

    validator.validate("semantic-model-call-progress", payload, version="1.0.0")
    assert payload["record_kind"] == "model_call_progress"
    assert payload["execution_authority"] is False


@pytest.mark.parametrize(
    ("overrides", "match"),
    [
        ({"status": "completed"}, "ended model call"),
        ({"completed_at": _STARTED, "duration_ms": 1}, "ended model call"),
        ({"prompt_tokens": 1}, "running model call"),
        (
            {
                "status": "completed",
                "completed_at": _STARTED - timedelta(seconds=1),
                "duration_ms": 0,
            },
            "end before",
        ),
    ],
)
def test_an_inconsistent_lifecycle_is_rejected(overrides: dict[str, object], match: str) -> None:
    with pytest.raises(ValidationError, match=match):
        _record(**overrides)


@pytest.mark.parametrize(
    "overrides",
    [
        {"stage": "answer_author"},
        {"model": "deployment with spaces"},
        {"call_index": 33},
        {"execution_authority": True},
        {"prompt": "the question text"},
    ],
)
def test_content_and_unbounded_values_are_rejected(overrides: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        _record(**overrides)


def test_the_schema_rejects_a_running_record_with_an_end() -> None:
    payload = _record().model_dump(mode="json")
    validator = JsonSchemaContractValidator(PackageResourceSchemaRegistry())

    with pytest.raises(ContractValidationError):
        validator.validate(
            "semantic-model-call-progress", {**payload, "duration_ms": 5}, version="1.0.0"
        )
