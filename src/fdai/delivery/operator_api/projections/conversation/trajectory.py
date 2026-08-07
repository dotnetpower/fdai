"""Bounded terminal projection of observed chat trajectory detail.

Responsibility: Reduce observed progress records into one bounded replay value.
Boundary: Accept request-local event mappings and return JSON-serializable data.
Authority and state: Read-only, request-local, and free of durable writes.
Dependencies: Python collection and serialization primitives only.
Deployment: Runs in-process within the Operator API without a network boundary.
"""

from __future__ import annotations

import json
from collections import OrderedDict
from collections.abc import Mapping
from copy import deepcopy
from typing import Any, Final

_MAX_ACTIVITIES: Final[int] = 8
_MAX_BRANCHES: Final[int] = 4
_MAX_MILESTONES: Final[int] = 16
_MAX_DETAIL_BYTES: Final[int] = 64 * 1024
_MAX_HISTORY_OUTPUT_CHARS: Final[int] = 32 * 1024
_MAX_TERMINAL_FRAME_BYTES: Final[int] = 256 * 1024
_TERMINAL_WRAPPER_RESERVE_BYTES: Final[int] = 4 * 1024

_ACTIVITY_FIELDS: Final[tuple[str, ...]] = (
    "activity_id",
    "kind",
    "status",
    "label",
    "agent",
    "detail",
    "completed",
    "total",
    "authority",
    "observed_at",
    "branch_id",
)
_EXECUTION_FIELDS: Final[tuple[str, ...]] = (
    "tool",
    "command",
    "input_kind",
    "redacted",
    "output",
    "output_truncated",
    "exit_code",
    "started_at",
    "completed_at",
    "duration_ms",
)
_BRANCH_FIELDS: Final[tuple[str, ...]] = (
    "branch_id",
    "branch_kind",
    "parent_branch_id",
    "status",
    "summary",
    "started_at",
    "completed_at",
    "duration_ms",
    "evidence_refs",
)
_MILESTONE_FIELDS: Final[tuple[str, ...]] = (
    "message_id",
    "text",
    "agent",
    "recorded_at",
)


class TrajectoryDetailCollector:
    """Keep final observed progress records for the terminal replay payload."""

    def __init__(self) -> None:
        self._activities: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._branches: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._milestones: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._omitted = {"activities": 0, "branches": 0, "milestones": 0}
        self._omitted_ids = {
            "activities": set[str](),
            "branches": set[str](),
            "milestones": set[str](),
        }

    def observe(self, event: Mapping[str, Any]) -> None:
        event_name = event.get("event")
        if event_name == "activity":
            self._upsert(
                self._activities,
                _project_activity(event),
                key="activity_id",
                cap=_MAX_ACTIVITIES,
                omitted_key="activities",
            )
        elif event_name == "branch":
            self._upsert(
                self._branches,
                _project(event, _BRANCH_FIELDS),
                key="branch_id",
                cap=_MAX_BRANCHES,
                omitted_key="branches",
            )
        elif event_name == "milestone":
            self._upsert(
                self._milestones,
                _project(event, _MILESTONE_FIELDS),
                key="message_id",
                cap=_MAX_MILESTONES,
                omitted_key="milestones",
            )

    def snapshot(self, *, max_bytes: int = _MAX_DETAIL_BYTES) -> dict[str, Any] | None:
        if not self._activities and not self._branches and not self._milestones:
            return None
        effective_max_bytes = max(0, min(max_bytes, _MAX_DETAIL_BYTES))
        activities = [deepcopy(item) for item in self._activities.values()]
        branches = [deepcopy(item) for item in self._branches.values()]
        milestones = [deepcopy(item) for item in self._milestones.values()]
        omitted = dict(self._omitted)
        payload = _payload(
            activities=activities,
            branches=branches,
            milestones=milestones,
            omitted=omitted,
        )
        while _serialized_size(payload) > effective_max_bytes:
            if milestones:
                milestones.pop(0)
                omitted["milestones"] += 1
            elif activities:
                activities.pop(0)
                omitted["activities"] += 1
            elif branches:
                branches.pop(0)
                omitted["branches"] += 1
            else:
                break
            payload = _payload(
                activities=activities,
                branches=branches,
                milestones=milestones,
                omitted=omitted,
            )
        return payload if _serialized_size(payload) <= effective_max_bytes else None

    def _upsert(
        self,
        target: OrderedDict[str, dict[str, Any]],
        projected: dict[str, Any],
        *,
        key: str,
        cap: int,
        omitted_key: str,
    ) -> None:
        identity = projected.get(key)
        if not isinstance(identity, str) or not identity:
            return
        if identity not in target and len(target) >= cap:
            if identity not in self._omitted_ids[omitted_key]:
                self._omitted_ids[omitted_key].add(identity)
                self._omitted[omitted_key] += 1
            return
        target[identity] = projected


def _project_activity(event: Mapping[str, Any]) -> dict[str, Any]:
    projected = _project(event, _ACTIVITY_FIELDS)
    execution = event.get("execution")
    if isinstance(execution, Mapping) and execution.get("redacted") is True:
        projected_execution = _project(execution, _EXECUTION_FIELDS)
        output = projected_execution.get("output")
        if isinstance(output, str):
            bounded_output, was_truncated = _bounded_history_output(output)
            projected_execution["output"] = bounded_output
        else:
            was_truncated = False
        if was_truncated:
            projected_execution["output_truncated"] = True
        projected["execution"] = projected_execution
    return projected


def _project(source: Mapping[str, Any], fields: tuple[str, ...]) -> dict[str, Any]:
    return {field: deepcopy(source[field]) for field in fields if field in source}


def _bounded_history_output(value: str) -> tuple[str, bool]:
    if _json_string_size(value) <= _MAX_HISTORY_OUTPUT_CHARS:
        return value, False
    low = 0
    high = len(value)
    while low < high:
        middle = (low + high + 1) // 2
        if _json_string_size(value[:middle]) <= _MAX_HISTORY_OUTPUT_CHARS:
            low = middle
        else:
            high = middle - 1
    return value[:low], True


def _json_string_size(value: str) -> int:
    return len(json.dumps(value, ensure_ascii=True, separators=(",", ":")).encode("ascii"))


def _payload(
    *,
    activities: list[dict[str, Any]],
    branches: list[dict[str, Any]],
    milestones: list[dict[str, Any]],
    omitted: dict[str, int],
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "activities": activities,
        "branches": branches,
        "milestones": milestones,
        "omitted": omitted,
        "truncated_outputs": sum(
            1
            for activity in activities
            if isinstance(activity.get("execution"), Mapping)
            and activity["execution"].get("output_truncated") is True
        ),
    }


def _serialized_size(payload: Mapping[str, Any]) -> int:
    return len(
        json.dumps(
            payload,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii")
    )


def trajectory_detail_budget(payload: Mapping[str, Any]) -> int:
    available = (
        _MAX_TERMINAL_FRAME_BYTES - _TERMINAL_WRAPPER_RESERVE_BYTES - _serialized_size(payload)
    )
    return max(0, min(_MAX_DETAIL_BYTES, available))


__all__ = ["TrajectoryDetailCollector", "trajectory_detail_budget"]
