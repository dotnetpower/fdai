"""Describe a failed Foundation attempt without accepting it as handoff or authority."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, NoReturn

from fdai_deployment_cli.private_output import read_private_bytes

_GENERIC = "standalone Foundation orchestration failed; inspect retained status before recovery"
_IMAGE_INCOMPLETE = (
    "standalone Foundation orchestration failed at Runner image exact apply (08/15).\n"
    "Image creation or independent verification is incomplete.\n"
    "Preserve the work directory and its state, plans, and apply claims. "
    "A retained claim permits verification only; recovery needs a separately reviewed exact "
    "plan and new approval."
)


def foundation_failure_summary(
    path: Path, *, previous: int, source_commit: str, run_binding: str
) -> str:
    """Return fixed guidance only for a current, context-matched failed child attempt.

    Call only after the child has exited unsuccessfully. This bounded private read never accepts
    a success record, returns operational state, prints payload values, or changes execution.
    Missing, malformed, stale, unreadable, or unrecognized evidence retains the generic failure.
    """
    try:
        value = json.loads(
            read_private_bytes(path, max_bytes=1_048_576).decode("utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except (OSError, ValueError, RecursionError):
        return _GENERIC
    if not isinstance(value, dict):
        return _GENERIC
    attempt, sequence = value.get("attempt"), value.get("sequence")
    if (
        value.get("schema_version") != "fdai.genesis-orchestration-status.v2"
        or type(attempt) is not int
        or attempt != previous + 1
        or type(sequence) is not int
        or sequence < 1
        or value.get("source_commit") != source_commit
        or value.get("target_binding") != run_binding
        or value.get("mode") != "apply"
        or value.get("state") not in ("blocked", "failed")
        or value.get("route") != "private-runner"
    ):
        return _GENERIC
    if (
        value.get("current_stage") == "runner-image-apply"
        and value.get("reason_code") == "runner_image_apply_or_verification_failed"
    ):
        return _IMAGE_INCOMPLETE
    return _GENERIC


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate Foundation diagnostic key")
        result[key] = value
    return result


def _reject_constant(_value: str) -> NoReturn:
    raise ValueError("nonfinite Foundation diagnostic value")
