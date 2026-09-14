"""Bounded ActionRun identity and workflow-lineage helpers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def optional_bounded_text(value: object, *, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip() or len(value) > 512:
        raise ValueError(f"durable ActionRun {field_name} MUST be bounded text")
    return value


def bounded_workflow_action(raw: object) -> dict[str, Any] | None:
    if not isinstance(raw, Mapping):
        return None
    required = {"process_id", "step_id", "proposal_ref"}
    if not required.issubset(raw) or not set(raw).issubset(required | {"attempt"}):
        return None
    bounded: dict[str, Any] = {key: str(raw[key]).strip() for key in required}
    if any(not item or len(item) > 512 for item in bounded.values()):
        return None
    if "attempt" in raw:
        attempt = raw["attempt"]
        if isinstance(attempt, bool) or not isinstance(attempt, int) or attempt < 1:
            return None
        bounded["attempt"] = attempt
    return bounded


def validate_action_run_lineage(
    action_id: str | None,
    workflow_action: dict[str, Any] | None,
) -> None:
    if action_id is not None and (
        not action_id.strip() or action_id != action_id.strip() or len(action_id) > 512
    ):
        raise ValueError("ActionRun action_id MUST be canonical and bounded")
    if workflow_action is not None and bounded_workflow_action(workflow_action) != workflow_action:
        raise ValueError("ActionRun workflow_action MUST be canonical and bounded")


__all__ = [
    "bounded_workflow_action",
    "optional_bounded_text",
    "validate_action_run_lineage",
]
