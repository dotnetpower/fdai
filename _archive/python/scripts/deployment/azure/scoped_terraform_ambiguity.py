"""Keep an ambiguous Run Command outcome verification-only until the host command settles.

A local transport timeout or a missing result line does not stop the command on the managed host.
The coordinator records the ambiguity for the state target, refuses new plans and applies, and
permits only `verify` for the same operation after the Azure Activity Log reports a terminal
status for every Run Command invocation since the ambiguous one started.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

Runner = Callable[[tuple[str, ...], int], str]
RUN_COMMAND_OPERATION = "Microsoft.Compute/virtualMachines/runCommand/action"
TERMINAL = ("Succeeded", "Failed", "Canceled")
CLOCK_SKEW = timedelta(seconds=120)


class AmbiguousOutcomeError(Exception):
    """The previous invocation for this state target has no confirmed outcome."""


def marker_path(state_root: Path, target_key: str) -> Path:
    return state_root / "ambiguous" / f"{target_key}.json"


def record(
    state_root: Path, target_key: str, *, operation_id: str, operation: str, started_at: datetime
) -> None:
    path = marker_path(state_root, target_key)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    value = {
        "operation_id": operation_id,
        "operation": operation,
        "started_at": started_at.astimezone(UTC).replace(microsecond=0).isoformat(),
    }
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(value, handle, sort_keys=True)


def _moment(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def invocation_state(run: Runner, vm_resource_id: str, since: datetime) -> str:
    """Classify Run Command invocations on the VM since `since` from the Azure Activity Log.

    Returns `settled` when at least one invocation is recorded and every one has a terminal
    status, `running` when any lacks one, and `unrecorded` while the Activity Log shows none.
    """

    offset_hours = max(1, int((datetime.now(UTC) - since).total_seconds() // 3600) + 1)
    events = json.loads(
        run(
            (
                "az",
                "monitor",
                "activity-log",
                "list",
                "--resource-id",
                vm_resource_id,
                "--offset",
                f"{min(offset_hours, 72)}h",
                "--query",
                f"[?operationName.value=='{RUN_COMMAND_OPERATION}']"
                ".{t:eventTimestamp,s:status.value,c:correlationId}",
                "-o",
                "json",
            ),
            180,
        )
    )
    threshold = since - CLOCK_SKEW
    invocations: dict[str, set[str]] = {}
    for event in events:
        if _moment(str(event["t"])) >= threshold:
            invocations.setdefault(str(event["c"]), set()).add(str(event["s"]))
    if not invocations:
        return "unrecorded"
    if all(statuses & set(TERMINAL) for statuses in invocations.values()):
        return "settled"
    return "running"


def require_settled(
    run: Runner,
    state_root: Path,
    target_key: str,
    *,
    vm_resource_id: str,
    operation_id: str,
    operation: str,
) -> bool:
    """Raise unless this invocation is safe; return True when it resolves a recorded ambiguity."""

    path = marker_path(state_root, target_key)
    if not path.is_file():
        return False
    marker = json.loads(path.read_text(encoding="utf-8"))
    state = invocation_state(run, vm_resource_id, _moment(str(marker["started_at"])))
    if state != "settled":
        raise AmbiguousOutcomeError(
            f"the previous {marker['operation']} Run Command is {state} in the Activity Log;"
            " wait for its terminal status, then run verify"
        )
    if operation != "verify" or operation_id != marker["operation_id"]:
        raise AmbiguousOutcomeError(
            f"the previous {marker['operation']} outcome is unknown; run verify for operation"
            f" {marker['operation_id']} before any new plan or apply"
        )
    return True


def clear(state_root: Path, target_key: str) -> None:
    marker_path(state_root, target_key).unlink(missing_ok=True)
