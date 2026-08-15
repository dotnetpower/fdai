#!/usr/bin/env python3
"""Route focused validation and gate only high-risk edits on current design context."""

from __future__ import annotations

import fcntl
import fnmatch
import hashlib
import json
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, cast

from scripts.agent import external_operation_guard

REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = REPO_ROOT / "scripts/lib/design-routes.json"
FRAMEWORK_SURFACE_PATH = REPO_ROOT / "scripts/lib/framework-surface.txt"
EDIT_TOOL_NAMES = frozenset({"apply_patch", "create_file"})
TERMINAL_TOOL_NAMES = frozenset({"run_in_terminal"})
HIGH_RISK_ROUTE_IDS = frozenset({"constitution"})
HIGH_RISK_EXACT_PATHS = frozenset(
    {
        ".github/hooks/design-context.json",
        "scripts/agent/design_context.py",
        "scripts/agent/external_operation_guard.py",
        "scripts/agent/pre_tool_dispatch.py",
        "scripts/lib/design-routes.json",
        "scripts/lib/framework-surface.txt",
    }
)
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
CONTEXT_DOCUMENT_SUFFIXES = frozenset({".json", ".md", ".yaml", ".yml"})
EDIT_RESERVATION_TTL_SECONDS = 30 * 60


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


def _reservation_state_path() -> Path:
    return _git_dir() / "fdai-edit-reservations.json"


def _reservation_lock_path() -> Path:
    return _git_dir() / "fdai-edit-reservations.lock"


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
    if (
        relative is None
        or Path(relative).suffix not in CONTEXT_DOCUMENT_SUFFIXES
        or relative not in _context_documents()
    ):
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


def _target_is_dirty(target: str) -> bool:
    return bool(
        subprocess.run(
            ["git", "status", "--porcelain", "--", target],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
        ).stdout.strip()
    )


def enforce_edit_reservations(payload: dict[str, Any]) -> dict[str, Any]:
    """Reserve dirty edit targets for one active agent session."""
    targets = _edit_targets(payload)
    session = _session_id(payload)
    if not targets or session == "default":
        return {"continue": True}
    state_path = _reservation_state_path()
    lock_path = _reservation_lock_path()
    state_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            loaded: object = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            loaded = {}
        reservations = loaded.get("reservations") if isinstance(loaded, dict) else None
        active = reservations if isinstance(reservations, dict) else {}
        now = time.time()
        for target in targets:
            reservation = active.get(target)
            if not isinstance(reservation, dict) or reservation.get("session") == session:
                continue
            updated_at = reservation.get("updated_at")
            current = isinstance(updated_at, (int, float)) and (
                now - float(updated_at) <= EDIT_RESERVATION_TTL_SECONDS
            )
            if current and _target_is_dirty(target):
                reason = (
                    f"FDAI edit collision: {target} is reserved by another active agent session. "
                    "Wait for its focused commit or edit a non-overlapping path."
                )
                return {
                    "systemMessage": reason,
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": "deny",
                        "permissionDecisionReason": reason,
                    },
                }
        for target in targets:
            active[target] = {"session": session, "updated_at": now}
        state_path.write_text(
            json.dumps({"reservations": active, "version": 1}, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return {"continue": True}


def _matches(path: str, pattern: str) -> bool:
    return pattern == "**" or fnmatch.fnmatchcase(path, pattern)


def _manifest() -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(MANIFEST_PATH.read_text(encoding="utf-8")))


def _context_documents() -> frozenset[str]:
    return frozenset(str(path) for route in _manifest()["routes"] for path in route["must_read"])


def _framework_surface_entries() -> tuple[str, ...]:
    return tuple(
        line
        for raw in FRAMEWORK_SURFACE_PATH.read_text(encoding="utf-8").splitlines()
        if (line := raw.split("#", 1)[0].strip())
    )


def _matches_framework_surface(path: str) -> bool:
    return any(
        path.startswith(entry) if entry.endswith("/") else path == entry
        for entry in _framework_surface_entries()
    )


def _is_high_risk_target(path: str) -> bool:
    if path in HIGH_RISK_EXACT_PATHS or _matches_framework_surface(path):
        return True
    return any(
        route.get("id") in HIGH_RISK_ROUTE_IDS
        and any(
            _matches(path, pattern)
            for pattern in tuple(route.get("paths", ())) + tuple(route.get("optional_paths", ()))
        )
        for route in _manifest()["routes"]
    )


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
    required: set[str] = set()
    for route in _manifest()["routes"]:
        patterns = tuple(route.get("paths", ())) + tuple(route.get("optional_paths", ()))
        if any(
            _matches(candidate, pattern)
            for target in targets
            for candidate in _route_paths(target)
            for pattern in patterns
        ):
            required.update(str(path) for path in route["must_read"])
    return tuple(sorted(required))


def required_validation(targets: tuple[str, ...]) -> tuple[str, ...]:
    """Return deduplicated focused checks for every route matching the targets."""
    required: set[str] = set()
    for route in _manifest()["routes"]:
        patterns = tuple(route.get("paths", ())) + tuple(route.get("optional_paths", ()))
        if any(
            _matches(candidate, pattern)
            for target in targets
            for candidate in _route_paths(target)
            for pattern in patterns
        ):
            required.update(str(command) for command in route.get("validate", ()))
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
    targets = tuple(target for target in _edit_targets(payload) if _is_high_risk_target(target))
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
        "FDAI design context is incomplete for this high-risk edit. Read every required file "
        "with read_file, state the controlling invariant and a falsifying check, then retry.\n"
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
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|")
        lexer.whitespace_split = True
        lexer.commenters = ""
        command_tokens = list(lexer)
    except ValueError:
        return False
    segments: list[list[str]] = [[]]
    for token in command_tokens:
        if token in {";", "&", "&&", "|", "||"}:
            segments.append([])
        else:
            segments[-1].append(token)
    for tokens in segments:
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


def enforce_commit_scope(payload: dict[str, Any]) -> dict[str, Any]:
    if _tool_name(payload) not in TERMINAL_TOOL_NAMES:
        return {"continue": True}
    command = str(_tool_input(payload).get("command") or "")
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|")
        lexer.whitespace_split = True
        lexer.commenters = ""
        tokens = list(lexer)
    except ValueError:
        return {"continue": True}
    segments: list[list[str]] = [[]]
    for token in tokens:
        if token in {";", "&", "&&", "|", "||"}:
            segments.append([])
        else:
            segments[-1].append(token)
    for segment in segments:
        if "git" not in segment or "commit" not in segment:
            continue
        commit_index = segment.index("commit")
        if "--" in segment[commit_index + 1 :]:
            continue
        reason = (
            "Agent commits in the shared FDAI worktree must use an explicit pathspec: "
            "git commit ... -- <owned paths>. A bare commit can include another session's "
            "staged files."
        )
        return {
            "systemMessage": reason,
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            },
        }
    return {"continue": True}


_DESTRUCTIVE_GIT_OPERATIONS = frozenset(
    {"checkout", "clean", "reset", "restore", "stash", "switch"}
)
_DESTRUCTIVE_GIT_APPROVAL = "FDAI_USER_APPROVED_DESTRUCTIVE_GIT=1"
_GIT_GLOBAL_OPTIONS_WITH_VALUE = frozenset({"-C", "-c", "--git-dir", "--namespace", "--work-tree"})


def _git_operation(arguments: list[str]) -> str | None:
    index = 0
    while index < len(arguments):
        argument = arguments[index]
        if argument in _GIT_GLOBAL_OPTIONS_WITH_VALUE:
            index += 2
            continue
        if argument.startswith(("--git-dir=", "--namespace=", "--work-tree=")):
            index += 1
            continue
        if argument.startswith("-"):
            index += 1
            continue
        return argument
    return None


def enforce_destructive_git(payload: dict[str, Any]) -> dict[str, Any]:
    """Require an explicit user-approval marker for destructive Git operations."""
    if _tool_name(payload) not in TERMINAL_TOOL_NAMES:
        return {"continue": True}
    command = str(_tool_input(payload).get("command") or "")
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|")
        lexer.whitespace_split = True
        lexer.commenters = ""
        tokens = list(lexer)
    except ValueError:
        return {"continue": True}
    segments: list[list[str]] = [[]]
    for token in tokens:
        if token in {";", "&", "&&", "|", "||"}:
            segments.append([])
        else:
            segments[-1].append(token)
    for segment in segments:
        if _DESTRUCTIVE_GIT_APPROVAL in segment or "git" not in segment:
            continue
        git_index = segment.index("git")
        arguments = segment[git_index + 1 :]
        operation = _git_operation(arguments)
        if operation not in _DESTRUCTIVE_GIT_OPERATIONS:
            continue
        reason = (
            f"Destructive Git operation 'git {operation}' requires an explicit user request. "
            f"Only after that request, add {_DESTRUCTIVE_GIT_APPROVAL} to the command."
        )
        return {
            "systemMessage": reason,
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            },
        }
    return {"continue": True}


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
    tool_name = _tool_name(payload)
    if tool_name == "read_file":
        return record_read(payload)
    if tool_name in EDIT_TOOL_NAMES:
        reservation_result = enforce_edit_reservations(payload)
        if reservation_result.get("hookSpecificOutput", {}).get("permissionDecision") == "deny":
            return reservation_result
        return enforce_edit(payload)
    if tool_name not in TERMINAL_TOOL_NAMES and tool_name != "runTests":
        return {"continue": True}
    destructive_result = enforce_destructive_git(payload)
    if destructive_result.get("hookSpecificOutput", {}).get("permissionDecision") == "deny":
        return destructive_result
    commit_result = enforce_commit_scope(payload)
    if commit_result.get("hookSpecificOutput", {}).get("permissionDecision") == "deny":
        return commit_result
    validation_result = enforce_validation_route(payload)
    if validation_result.get("hookSpecificOutput", {}).get("permissionDecision") == "deny":
        return validation_result
    return external_operation_guard.enforce_external_operation_order(
        tool_name=tool_name,
        tool_input=_tool_input(payload),
        repo_root=REPO_ROOT,
    )


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
