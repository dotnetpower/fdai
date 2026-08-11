#!/usr/bin/env python3
"""Dispatch only policy-relevant tool calls to the full FDAI pre-tool guard."""

from __future__ import annotations

import json
import sys

POLICY_TOOL_NAMES = frozenset(
    {"apply_patch", "create_file", "read_file", "run_in_terminal", "runTests"}
)
CONTEXT_DOCUMENT_SUFFIXES = (".json", ".md", ".yaml", ".yml")
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


def _requires_policy(payload: Payload) -> bool:
    tool_name = _tool_name(payload)
    if tool_name not in POLICY_TOOL_NAMES:
        return False
    if tool_name != "read_file":
        return True
    tool_input = _tool_input(payload)
    raw_path = tool_input.get("filePath") or tool_input.get("path")
    return bool(raw_path and str(raw_path).endswith(CONTEXT_DOCUMENT_SUFFIXES))


def _run_policy(payload: Payload) -> Payload:
    from scripts.agent.design_context import pre_tool_use

    return pre_tool_use(payload)


def dispatch(payload: Payload) -> Payload:
    """Return immediately unless the tool can trigger an FDAI pre-tool policy."""
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
