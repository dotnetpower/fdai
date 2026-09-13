"""Bind Foundation supervision to a fresh, target-matched private status snapshot."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fdai_deployment_cli.private_output import read_private_bytes


def prior_attempt(path: Path) -> int:
    """Read the existing attempt without treating absence as successful Foundation evidence."""

    try:
        value = _read(path)
    except FileNotFoundError:
        return 0
    return _attempt(value)


def current_status(
    path: Path, *, previous: int, source_commit: str, run_binding: str
) -> dict[str, Any]:
    """Require a newer writer attempt and exact execution context after a successful child exit.

    This validates the status handoff, not operational effects. Existing exact plan, approval,
    receipt, and independent verification checks remain required by the caller.
    """

    try:
        value = _read(path)
    except FileNotFoundError as exc:
        raise ValueError(
            "orchestrator did not publish current Foundation status; inspect retained evidence"
        ) from exc
    sequence = value.get("sequence")
    state = value.get("state")
    if (
        value.get("schema_version") != "fdai.genesis-orchestration-status.v2"
        or _attempt(value) != previous + 1
        or type(sequence) is not int
        or sequence < 1
        or value.get("source_commit") != source_commit
        or value.get("target_binding") != run_binding
        or value.get("mode") != "apply"
        or not isinstance(state, str)
        or state not in {"waiting", "complete"}
    ):
        raise ValueError(
            "current Foundation status is stale or mismatched; inspect retained evidence"
        )
    return value


def _attempt(value: dict[str, Any]) -> int:
    attempt = value.get("attempt")
    if type(attempt) is not int or attempt < 1:
        raise ValueError("current Foundation status has an invalid attempt")
    return attempt


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(read_private_bytes(path, max_bytes=1_048_576))
    if not isinstance(value, dict):
        raise ValueError("current Foundation status must be an object")
    return {str(key): item for key, item in value.items()}
