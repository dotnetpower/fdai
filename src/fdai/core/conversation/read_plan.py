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
    evidence_refs = tuple(
        dict.fromkeys(reference for _, result in results for reference in result.evidence_refs)
    )
    data = {
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
    preview = "read plan: " + "; ".join(
        f"{step.tool.name}={result.preview}" for step, result in results
    )
    return ToolResult(
        status=status,
        data=data,
        preview=preview,
        evidence_refs=evidence_refs,
    )


__all__ = [
    "MAX_READ_PLAN_COMMAND_CHARS",
    "MAX_READ_PLAN_STEPS",
    "MIN_READ_PLAN_STEPS",
    "ParsedReadCommand",
    "ValidatedReadStep",
    "execute_read_plan",
    "validate_read_plan",
]
