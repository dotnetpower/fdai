"""Workflow-facing widget builders: process steps and before/after comparison."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fdai.core.reporting.models import DataSet, WidgetSpec

_KNOWN_STEP_STATUSES: frozenset[str] = frozenset(
    {
        "pending",
        "running",
        "waiting",
        "succeeded",
        "failed",
        "skipped",
        "cancelled",
        "unknown",
    }
)
_COMPLETED_STEP_STATUSES: frozenset[str] = frozenset(
    {"succeeded", "failed", "skipped", "cancelled"}
)
_MAX_ROWS = 200


class ProcessStepsBuilder:
    """Normalize ordered workflow-step evidence for a read-only stepper.

    Expected rows carry ``id``, ``name``, ``status`` and optional ``message``,
    ``at`` and ``duration_ms`` fields. Unknown statuses become ``unknown`` so a
    producer typo never receives a successful visual treatment.
    """

    type_name = "process_steps"

    def build(self, *, spec: WidgetSpec, data: DataSet) -> Mapping[str, Any]:
        del spec
        steps: list[dict[str, Any]] = []
        completed = 0
        for index, row in enumerate(data.rows[:_MAX_ROWS]):
            status = str(row.get("status", "unknown")).lower()
            if status not in _KNOWN_STEP_STATUSES:
                status = "unknown"
            if status in _COMPLETED_STEP_STATUSES:
                completed += 1
            steps.append(
                {
                    "id": row.get("id") or f"step-{index + 1}",
                    "name": row.get("name") or row.get("id") or f"Step {index + 1}",
                    "status": status,
                    "message": row.get("message"),
                    "at": row.get("at"),
                    "duration_ms": row.get("duration_ms"),
                }
            )
        return {
            "steps": steps,
            "completed": completed,
            "total": len(steps),
            "progress_ratio": (completed / len(steps)) if steps else None,
            "truncated": len(data.rows) > _MAX_ROWS,
        }


class ComparisonBuilder:
    """Normalize field-level before/after evidence.

    Field names are configurable through ``options``. The payload keeps raw
    scalar values and derives ``changed`` by equality only; it never infers
    whether a change is beneficial.
    """

    type_name = "comparison"

    def build(self, *, spec: WidgetSpec, data: DataSet) -> Mapping[str, Any]:
        field_key = str(spec.options.get("field_key", "field"))
        before_key = str(spec.options.get("before_key", "before"))
        after_key = str(spec.options.get("after_key", "after"))
        rows: list[dict[str, Any]] = []
        changed_count = 0
        for index, row in enumerate(data.rows[:_MAX_ROWS]):
            before = row.get(before_key)
            after = row.get(after_key)
            changed = before != after
            if changed:
                changed_count += 1
            rows.append(
                {
                    "field": row.get(field_key) or f"field-{index + 1}",
                    "before": before,
                    "after": after,
                    "changed": changed,
                }
            )
        return {
            "rows": rows,
            "changed_count": changed_count,
            "total": len(rows),
            "truncated": len(data.rows) > _MAX_ROWS,
        }


__all__ = ["ComparisonBuilder", "ProcessStepsBuilder"]
