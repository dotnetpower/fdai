"""Secret-safe Kubernetes scheduler event classification."""

from __future__ import annotations

import re
from typing import Final, NamedTuple

_HOST_PORT_CONFLICT: Final = re.compile(
    r"\bdid(?: not|n't) have free ports for (?:the )?requested pod ports\b",
    re.IGNORECASE,
)


class SchedulerFailure(NamedTuple):
    code: str


def classify_scheduler_failure(*, reason: str, message: str) -> SchedulerFailure | None:
    """Classify one reviewed scheduler failure without retaining its raw message."""

    if reason == "FailedScheduling" and _HOST_PORT_CONFLICT.search(message):
        return SchedulerFailure("host_port_conflict")
    return None


__all__ = ["SchedulerFailure", "classify_scheduler_failure"]
