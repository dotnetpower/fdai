#!/usr/bin/env python3
"""Record requested design-document reads and gate edits without post-tool payloads."""

from __future__ import annotations

import fnmatch
import hashlib
import json
import re
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = REPO_ROOT / "scripts/lib/design-routes.json"
EDIT_TOOL_NAMES = frozenset({"apply_patch", "create_file"})
TERMINAL_TOOL_NAMES = frozenset({"run_in_terminal"})
HEAVY_VALIDATION_PATTERNS = (
    re.compile(
        r"(?:^|\s)(?:bash\s+)?scripts/verify\.sh(?:\s+(?:--fast|--all))?"
        r"(?=\s*(?:&&|;|\||$))"
    ),
    re.compile(r"(?:^|\s)make\s+(?:check|test|operator|lint|gates)(?:\s|$)"),
    re.compile(r"scripts/quality/ci/(?:run-python-tests|run-operator-surfaces)\.sh"),
)
PATCH_PATH = re.compile(
    r"^\*\*\* (?:Add|Update|Delete) File: (?P<path>.+?)(?: -> .+)?$",
    re.MULTILINE,
)


def _payload_value(payload: dict[str, Any], *names: str) -> Any:
    for name in names:
        if name in payload:
            return payload[name]
    return None


def _tool_name(payload: dict[str, Any]) -> str:
    raw = _payload_value(payload, "tool_name", "toolName", "tool")
    return str(raw or "").rsplit(".", 1)[-1]


def _tool_input(payload: dict[str, Any]) -> dict[str, Any]:
    raw = _payload_value(payload, "tool_input", "toolInput", "input")
    return raw if isinstance(raw, dict) else {}


def _session_id(payload: dict[str, Any]) -> str:
    raw = _payload_value(payload, "session_id", "sessionId", "conversation_id", "conversationId")
    safe = re.sub(r"[^A-Za-z0-9_.-]", "-", str(raw or "default"))
    return safe[:128] or "default"


def _git_dir() -> Path:
    completed = subprocess.run(
        ["git", "rev-parse", "--git-dir"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    path = Path(completed.stdout.strip())
    return path if path.is_absolute() else REPO_ROOT / path


def _state_path(payload: dict[str, Any]) -> Path:
    return _git_dir() / "fdai-design-context" / f"{_session_id(payload)}.json"


def _load_state(payload: dict[str, Any]) -> dict[str, Any]:
    path = _state_path(payload)
    if not path.is_file():
        return {"version": 1, "reads": {}}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"version": 1, "reads": {}}
    return loaded if isinstance(loaded, dict) else {"version": 1, "reads": {}}


def _save_state(payload: dict[str, Any], state: dict[str, Any]) -> None:
    path = _state_path(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _relative_path(raw: str) -> str | None:
    path = Path(raw)
    absolute = path if path.is_absolute() else REPO_ROOT / path
    try:
        relative = absolute.resolve().relative_to(REPO_ROOT.resolve())
    except ValueError:
        return None
    return relative.as_posix()


def _read_target(payload: dict[str, Any]) -> str | None:
    if _tool_name(payload) != "read_file":
        return None
    tool_input = _tool_input(payload)
    raw = tool_input.get("filePath") or tool_input.get("path")
    return _relative_path(str(raw)) if raw else None


def record_read(payload: dict[str, Any]) -> dict[str, Any]:
    relative = _read_target(payload)
    if relative is None:
        return {"continue": True}
    path = REPO_ROOT / relative
    if not path.is_file():
        return {"continue": True}
    state = _load_state(payload)
    reads = state.setdefault("reads", {})
    reads[relative] = _sha256(path)
    _save_state(payload, state)
    return {"continue": True}


def _edit_targets(payload: dict[str, Any]) -> tuple[str, ...]:
    tool_name = _tool_name(payload)
    if tool_name not in EDIT_TOOL_NAMES:
        return ()
    tool_input = _tool_input(payload)
    candidates: list[str] = []
    if tool_name == "create_file":
        raw = tool_input.get("filePath") or tool_input.get("path")
        if raw:
            candidates.append(str(raw))
    else:
        patch = str(tool_input.get("input") or tool_input.get("patch") or "")
        candidates.extend(match.group("path") for match in PATCH_PATH.finditer(patch))
    relative_paths = {_relative_path(candidate) for candidate in candidates}
    return tuple(sorted(path for path in relative_paths if path is not None))


def _matches(path: str, pattern: str) -> bool:
    return pattern == "**" or fnmatch.fnmatchcase(path, pattern)


def _route_paths(path: str) -> tuple[str, ...]:
    aliases = {
        "services/core-control-plane/src/fdai/": "services/core-control-plane/src/fdai/",
        "services/core-control-plane/tests/": "tests/",
        "services/operator-service/src/fdai_operator_service/": (
            "services/core-control-plane/src/fdai/delivery/operator_api/"
        ),
        "services/operator-service/tests/": (
            "services/core-control-plane/tests/delivery/operator_api/"
        ),
        "services/document-ingestion-api/src/fdai_ingestion_api_service/": (
            "services/core-control-plane/src/fdai/delivery/ingestion_gateway/"
        ),
        "services/document-ingestion-api/tests/": (
            "services/core-control-plane/tests/delivery/ingestion_gateway/"
        ),
        "services/document-processing-worker/src/fdai_document_worker_service/": (
            "services/core-control-plane/src/fdai/delivery/ingestion_gateway/"
        ),
        "services/document-processing-worker/tests/": (
            "services/core-control-plane/tests/delivery/ingestion_gateway/"
        ),
        "services/isolated-executor/src/fdai_executor_service/": (
            "services/core-control-plane/src/fdai/runtime/"
        ),
        "services/isolated-executor/tests/": ("services/core-control-plane/tests/runtime/"),
        "packages/service-contracts/src/fdai_service_contracts/": (
            "services/core-control-plane/src/fdai/shared/contracts/"
        ),
        "packages/service-contracts/tests/": (
            "services/core-control-plane/tests/shared/contracts/"
        ),
    }
    for prefix, replacement in aliases.items():
        if path.startswith(prefix):
            return path, replacement + path.removeprefix(prefix)
    return (path,)


def required_context(targets: tuple[str, ...]) -> tuple[str, ...]:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    required: set[str] = set()
    for route in manifest["routes"]:
        patterns = tuple(route.get("paths", ())) + tuple(route.get("optional_paths", ()))
        if any(
            _matches(candidate, pattern)
            for target in targets
            for candidate in _route_paths(target)
            for pattern in patterns
        ):
            required.update(str(path) for path in route["must_read"])
    return tuple(sorted(required))


def missing_context(payload: dict[str, Any], targets: tuple[str, ...]) -> tuple[str, ...]:
    reads = _load_state(payload).get("reads", {})
    missing: list[str] = []
    for relative in required_context(targets):
        path = REPO_ROOT / relative
        if not path.is_file() or reads.get(relative) != _sha256(path):
            missing.append(relative)
    return tuple(missing)


def enforce_edit(payload: dict[str, Any]) -> dict[str, Any]:
    targets = _edit_targets(payload)
    if not targets:
        return {"continue": True}
    missing = missing_context(payload, targets)
    if not missing:
        return {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "allow",
            }
        }
    target_lines = "\n".join(f"- {path}" for path in targets)
    missing_lines = "\n".join(f"- {path}" for path in missing)
    reason = (
        "FDAI design context is incomplete for this edit. Read every required file with "
        "read_file, state the controlling invariant and a falsifying check, then retry.\n"
        f"Targets:\n{target_lines}\nRequired unread or changed context:\n{missing_lines}"
    )
    return {
        "systemMessage": reason,
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        },
    }


def _has_focused_path(arguments: list[str]) -> bool:
    path_markers = (
        "tests",
        "src",
        "services",
        "packages",
        "scripts",
        "tools",
        "console",
        "cli",
        "evaluation-sdk",
        "benchmarks",
    )
    return any(
        "::" in argument
        or argument in path_markers
        or argument.startswith(tuple(f"{marker}/" for marker in path_markers))
        or any(f"/{marker}/" in argument for marker in path_markers)
        for argument in arguments
    )


def _is_unscoped_cli_check(command: str) -> bool:
    for segment in re.split(r"&&|;|\|\|?", command):
        try:
            tokens = shlex.split(segment)
        except ValueError:
            continue
        for executable in ("pytest", "mypy"):
            if executable in tokens:
                arguments = tokens[tokens.index(executable) + 1 :]
                if not _has_focused_path(arguments):
                    return True
        if (
            "make" in tokens
            and "test-changed" in tokens
            and not any(token.startswith("DIFF=") for token in tokens)
        ):
            return True
    return False


def enforce_validation_route(payload: dict[str, Any]) -> dict[str, Any]:
    tool_name = _tool_name(payload)
    tool_input = _tool_input(payload)
    is_broad_test_tool = tool_name == "runTests" and not tool_input.get("files")
    command = str(tool_input.get("command") or "") if tool_name in TERMINAL_TOOL_NAMES else ""
    is_direct_heavy_command = any(
        pattern.search(command) for pattern in HEAVY_VALIDATION_PATTERNS
    ) or _is_unscoped_cli_check(command)
    if not is_broad_test_tool and not is_direct_heavy_command:
        return {"continue": True}
    reason = (
        "Heavy FDAI validation is centralized to prevent duplicate CPU, memory, and disk load. "
        "Run focused tests in this worker session. The dedicated integration session must run "
        "'make validation-run' for the shared queue, or 'make validation-all' at a merge or "
        "release boundary."
    )
    return {
        "systemMessage": reason,
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        },
    }


def pre_tool_use(payload: dict[str, Any]) -> dict[str, Any]:
    if _tool_name(payload) == "read_file":
        return record_read(payload)
    edit_result = enforce_edit(payload)
    if edit_result.get("hookSpecificOutput", {}).get("permissionDecision") == "deny":
        return edit_result
    return enforce_validation_route(payload)


def main(argv: list[str]) -> int:
    if len(argv) != 2 or argv[1] not in {"record-read", "pre-tool-use"}:
        print("usage: design_context.py record-read|pre-tool-use", file=sys.stderr)
        return 2
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError as exc:
        print(f"design-context: invalid hook JSON: {exc}", file=sys.stderr)
        return 2
    if not isinstance(payload, dict):
        print("design-context: hook payload must be an object", file=sys.stderr)
        return 2
    result = record_read(payload) if argv[1] == "record-read" else pre_tool_use(payload)
    json.dump(result, sys.stdout)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
