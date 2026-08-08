"""Persist and validate resumable changed-test failures."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TypedDict

from scripts.automation.validation_queue_support import QueuePaths, atomic_write, git


class ChangedTestResume(TypedDict):
    """A prior failed changed-test run that can be continued safely."""

    failed_head: str
    nodeids: list[str]


def changed_test_cache_dir(paths: QueuePaths, head: str) -> Path:
    """Return the persistent pytest cache for one validated commit."""
    return paths.stage_cache / "pytest" / head


def _safe_nodeids(values: object, validation_root: Path) -> list[str]:
    if not isinstance(values, (dict, list)):
        return []
    nodeids: list[str] = []
    for value in values:
        if not isinstance(value, str) or value.startswith("-"):
            continue
        test_path = Path(value.split("::", 1)[0])
        if test_path.is_absolute() or ".." in test_path.parts:
            continue
        if (validation_root / test_path).is_file():
            nodeids.append(value)
    return sorted(nodeids)


def failed_nodeids(cache_dir: Path, validation_root: Path) -> list[str]:
    """Read valid failed pytest node IDs from a persistent cache."""
    try:
        payload: object = json.loads(
            (cache_dir / "v" / "cache" / "lastfailed").read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError):
        return []
    return _safe_nodeids(payload, validation_root)


def changed_test_resume_context(
    cache_context: dict[str, str], dependency_fingerprint: str
) -> dict[str, str]:
    """Build the cross-commit context required to reuse passed tests."""
    return {key: value for key, value in cache_context.items() if key != "head"} | {
        "dependency_fingerprint": dependency_fingerprint
    }


def write_changed_test_failure(
    paths: QueuePaths,
    *,
    head: str,
    context: dict[str, str],
    nodeids: list[str],
) -> None:
    """Persist one completed changed-test failure for a descendant retry."""
    failures = paths.stage_cache / "changed-tests"
    failures.mkdir(parents=True, exist_ok=True)
    atomic_write(
        failures / f"{head}.json",
        json.dumps(
            {"context": context, "failed_head": head, "nodeids": nodeids},
            sort_keys=True,
        )
        + "\n",
    )


def _resume_control_inputs_changed(paths: QueuePaths, failed_head: str, head: str) -> bool:
    output = git(
        "diff",
        "--name-only",
        "--no-renames",
        f"{failed_head}..{head}",
        cwd=paths.repo_root,
    ).stdout
    exact_inputs = {
        "scripts/automation/resolve_test_impact.py",
        "scripts/automation/resolve_test_ownership.py",
        "scripts/automation/tests-for-diff.sh",
    }
    return any(
        relative in exact_inputs
        or relative.startswith("scripts/automation/validation_queue")
        or relative == "conftest.py"
        or relative.endswith("/conftest.py")
        for relative in output.splitlines()
    )


def load_changed_test_resume(
    paths: QueuePaths,
    *,
    history: list[str],
    head: str,
    context: dict[str, str],
    validation_root: Path,
) -> ChangedTestResume | None:
    """Return the nearest safe ancestor failure for an incremental retry."""
    if context.get("integration") != "0":
        return None
    for candidate in reversed(history):
        if candidate == head:
            continue
        path = paths.stage_cache / "changed-tests" / f"{candidate}.json"
        try:
            payload: object = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict) or payload.get("context") != context:
            continue
        if _resume_control_inputs_changed(paths, candidate, head):
            continue
        nodeids = _safe_nodeids(payload.get("nodeids"), validation_root)
        if nodeids:
            return {"failed_head": candidate, "nodeids": nodeids}
    return None
