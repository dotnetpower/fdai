#!/usr/bin/env python3
"""Dispatch only policy-relevant tool calls to the full FDAI pre-tool guard."""

from __future__ import annotations

import json
import re
import sys

POLICY_TOOL_NAMES = frozenset(
    {"apply_patch", "create_file", "read_file", "run_in_terminal", "runTests"}
)
CONTEXT_DOCUMENT_SUFFIXES = (".json", ".md", ".yaml", ".yml")
PARALLEL_TOOL_NAME = "parallel"
TERMINAL_POLICY_HINTS = (
    "pytest",
    "mypy",
    "make ",
    "scripts/verify.sh",
    "scripts/quality/ci/",
    "gh ",
    "terraform",
    "tofu",
    "azd",
    "docker",
    "podman",
    "az ",
    "scripts/deployment/azure/",
    "scripts/deployment/release/",
)
GIT_POLICY_OPERATION = re.compile(r"(?:^|[\s'\";&|])(?:[^\s'\";&|]*/)?git\b")
Payload = dict[str, object]


def _payload_value(payload: Payload, *names: str) -> object | None:
    for name in names:
        if name in payload:
            return payload[name]
    return None


def _tool_name(payload: Payload) -> str:
    raw = _payload_value(payload, "tool_name", "toolName", "tool")
    return str(raw or "").rsplit(".", 1)[-1]


def _tool_input(payload: Payload) -> dict[object, object]:
    raw = _payload_value(payload, "tool_input", "toolInput", "input")
    return raw if isinstance(raw, dict) else {}


def _terminal_requires_policy(tool_input: dict[object, object]) -> bool:
    normalized = " ".join(str(tool_input.get("command") or "").casefold().split())
    if GIT_POLICY_OPERATION.search(normalized):
        return True
    if (
        normalized.startswith(("gh run list", "gh workflow list", "gh workflow view"))
        or (normalized.startswith("gh run view") and " --log" not in normalized)
        or (normalized.startswith("gh pr checks") and " --watch" not in normalized)
    ):
        return False
    command = f" {normalized} "
    return any(hint in command for hint in TERMINAL_POLICY_HINTS)


def _parallel_payloads(payload: Payload) -> tuple[Payload, ...]:
    if _tool_name(payload) != PARALLEL_TOOL_NAME:
        return ()
    raw_calls = _tool_input(payload).get("tool_uses")
    if not isinstance(raw_calls, list):
        return ()
    session_fields = {
        name: payload[name]
        for name in ("session_id", "sessionId", "conversation_id", "conversationId")
        if name in payload
    }
    nested: list[Payload] = []
    for raw_call in raw_calls:
        if not isinstance(raw_call, dict):
            continue
        parameters = raw_call.get("parameters")
        nested.append(
            {
                **session_fields,
                "tool_name": str(raw_call.get("recipient_name") or ""),
                "tool_input": parameters if isinstance(parameters, dict) else {},
            }
        )
    return tuple(nested)


def _requires_policy(payload: Payload) -> bool:
    tool_name = _tool_name(payload)
    if tool_name not in POLICY_TOOL_NAMES:
        return False
    tool_input = _tool_input(payload)
    if tool_name == "run_in_terminal":
        return _terminal_requires_policy(tool_input)
    if tool_name != "read_file":
        return True
    raw_path = tool_input.get("filePath") or tool_input.get("path")
    return bool(raw_path and str(raw_path).endswith(CONTEXT_DOCUMENT_SUFFIXES))


def _run_policy(payload: Payload) -> Payload:
    from scripts.agent.design_context import pre_tool_use

    return pre_tool_use(payload)


def _is_denied(result: Payload) -> bool:
    output = result.get("hookSpecificOutput")
    return isinstance(output, dict) and output.get("permissionDecision") == "deny"


def dispatch(payload: Payload) -> Payload:
    """Return immediately unless the tool can trigger an FDAI pre-tool policy."""
    nested = tuple(item for item in _parallel_payloads(payload) if _requires_policy(item))
    if nested:
        ordered = sorted(nested, key=lambda item: _tool_name(item) == "read_file")
        for item in ordered:
            result = _run_policy(item)
            if _is_denied(result):
                return result
        return {"continue": True}
    if not _requires_policy(payload):
        return {"continue": True}
    return _run_policy(payload)


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError as exc:
        print(f"pre-tool-dispatch: invalid hook JSON: {exc}", file=sys.stderr)
        return 2
    if not isinstance(payload, dict):
        print("pre-tool-dispatch: hook payload must be an object", file=sys.stderr)
        return 2
    json.dump(dispatch(payload), sys.stdout)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
