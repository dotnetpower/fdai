"""Validate and execute bounded read-only conversation tool plans."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from fdai.core.conversation.session import (
    ConversationSession,
    Principal,
    Turn,
    principal_has_role_at_least,
)
from fdai.core.conversation.tools import SystemConsoleTool, ToolResult

MIN_READ_PLAN_STEPS = 2
MAX_READ_PLAN_STEPS = 3
MAX_READ_PLAN_COMMAND_CHARS = 2_000
MAX_CONFLICT_RECORDS = 256
_IDENTITY_FIELDS = ("resource_id", "scope_ref", "id")
_CONFLICT_FIELDS = ("state", "status", "verdict", "mode", "health", "outcome")


@dataclass(frozen=True, slots=True)
class ParsedReadCommand:
    command: str
    tool_name: str
    arguments: Mapping[str, Any]
    confidence: float


@dataclass(frozen=True, slots=True)
class ValidatedReadStep:
    command: str
    tool: SystemConsoleTool
    arguments: Mapping[str, Any]


ParseReadCommand = Callable[[str], ParsedReadCommand | None]


def validate_read_plan(
    commands: Sequence[str],
    *,
    parse: ParseReadCommand,
    tools: Mapping[str, SystemConsoleTool],
    principal: Principal,
    confidence_threshold: float,
) -> tuple[ValidatedReadStep, ...] | None:
    """Return fully validated read steps, or ``None`` before any execution."""

    if not MIN_READ_PLAN_STEPS <= len(commands) <= MAX_READ_PLAN_STEPS:
        return None
    normalized = tuple(command.strip() for command in commands)
    if any(not command or len(command) > MAX_READ_PLAN_COMMAND_CHARS for command in normalized):
        return None
    if len({command.casefold() for command in normalized}) != len(normalized):
        return None
    steps: list[ValidatedReadStep] = []
    for command in normalized:
        parsed = parse(command)
        if parsed is None or parsed.confidence < confidence_threshold:
            return None
        tool = tools.get(parsed.tool_name)
        if (
            tool is None
            or tool.side_effect_class != "read"
            or not principal_has_role_at_least(principal.role, tool.rbac_floor)
        ):
            return None
        steps.append(
            ValidatedReadStep(
                command=command,
                tool=tool,
                arguments=parsed.arguments,
            )
        )
    return tuple(steps)


def execute_read_plan(
    steps: Sequence[ValidatedReadStep],
    *,
    session: ConversationSession,
) -> ToolResult:
    """Execute prevalidated reads serially and return one bounded aggregate."""

    results: list[tuple[ValidatedReadStep, ToolResult]] = []
    for step in steps:
        session.append(
            Turn(
                turn_id=str(uuid.uuid4()),
                direction="tool_call",
                content=step.tool.name,
                tool_name=step.tool.name,
                arguments=dict(step.arguments),
                tier="T0",
            )
        )
        try:
            result = step.tool.call(arguments=step.arguments, principal=session.principal)
        except (TypeError, ValueError) as exc:
            result = ToolResult(
                status="error",
                preview=f"tool {step.tool.name!r} rejected arguments: {exc}",
            )
        session.append(
            Turn(
                turn_id=str(uuid.uuid4()),
                direction="tool_result",
                content=result.preview,
                tool_name=step.tool.name,
                result_preview=result.preview,
                tier="T0",
            )
        )
        results.append((step, result))
        if result.status != "ok":
            break
    status: Literal["ok", "error", "abstain"] = next(
        (result.status for _, result in results if result.status != "ok"), "ok"
    )
    conflicts = _conflicting_facts(results)
    if status == "ok" and conflicts:
        status = "abstain"
    evidence_refs = tuple(
        dict.fromkeys(reference for _, result in results for reference in result.evidence_refs)
    )
    data: dict[str, object] = {
        "results": [
            {
                "command": step.command,
                "tool_name": step.tool.name,
                "status": result.status,
                "data": dict(result.data),
                "preview": result.preview,
                "evidence_refs": list(result.evidence_refs),
            }
            for step, result in results
        ]
    }
    if conflicts:
        data["conflicts"] = conflicts
    preview = "read plan: " + "; ".join(
        f"{step.tool.name}={result.preview}" for step, result in results
    )
    if conflicts:
        preview = "read plan evidence conflict: " + "; ".join(
            f"{item['identity_field']}={item['identity']} {item['field']}" for item in conflicts
        )
    return ToolResult(
        status=status,
        data=data,
        preview=preview,
        evidence_refs=evidence_refs,
    )


def _conflicting_facts(
    results: Sequence[tuple[ValidatedReadStep, ToolResult]],
) -> list[dict[str, object]]:
    observations: dict[tuple[str, str, str], list[tuple[str, object]]] = {}
    for step, result in results:
        for record in _bounded_records(result.data):
            identity = next(
                (
                    (field, str(record[field]))
                    for field in _IDENTITY_FIELDS
                    if _scalar(record.get(field))
                ),
                None,
            )
            if identity is None:
                continue
            identity_field, identity_value = identity
            for field in _CONFLICT_FIELDS:
                value = record.get(field)
                if not _scalar(value):
                    continue
                observations.setdefault((identity_field, identity_value, field), []).append(
                    (step.tool.name, value)
                )
    conflicts: list[dict[str, object]] = []
    for (identity_field, observed_identity, field), values in sorted(observations.items()):
        distinct_values = sorted({str(value) for _, value in values})
        distinct_tools = sorted({tool_name for tool_name, _ in values})
        if len(distinct_values) < 2 or len(distinct_tools) < 2:
            continue
        conflicts.append(
            {
                "identity_field": identity_field,
                "identity": observed_identity,
                "field": field,
                "values": distinct_values,
                "tools": distinct_tools,
            }
        )
    return conflicts


def _bounded_records(value: object) -> tuple[Mapping[str, Any], ...]:
    records: list[Mapping[str, Any]] = []

    def visit(candidate: object) -> None:
        if len(records) >= MAX_CONFLICT_RECORDS:
            return
        if isinstance(candidate, Mapping):
            records.append(candidate)
            for nested in candidate.values():
                visit(nested)
        elif isinstance(candidate, (list, tuple)):
            for nested in candidate:
                visit(nested)

    visit(value)
    return tuple(records)


def _scalar(value: object) -> bool:
    return value is not None and isinstance(value, (str, int, float, bool))


__all__ = [
    "MAX_CONFLICT_RECORDS",
    "MAX_READ_PLAN_COMMAND_CHARS",
    "MAX_READ_PLAN_STEPS",
    "MIN_READ_PLAN_STEPS",
    "ParsedReadCommand",
    "ValidatedReadStep",
    "execute_read_plan",
    "validate_read_plan",
]
