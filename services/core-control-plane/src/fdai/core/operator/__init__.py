"""Operator domain facade for the core package (G-1 phase 1, tracker #14).

Groups these subsystems: conversation, operator_memory, rbac, notifications, report_feed.

Phase 1 (this commit) creates the facade only - the physical subsystems
stay at ``fdai.core.<subsystem>`` and this package re-exports them so
new code can already write ``from fdai.core.operator import <subsystem>``
while pre-existing callsites continue to work unchanged.

Phase 2 (deferred, per tracker #14): physically ``git mv`` each
subsystem into this directory + codemod all callsites. That is a
mass-mv touching hundreds of imports; sequencing it as a separate PR
keeps the diff readable and the safety-core coverage boundary clean.

Why the two phases split matters: the docs already describe this
taxonomy as the target state, and the CI gates (check-file-loc,
check-subsystem-fanout) already stabilize the file-level shape. This
facade is the "code catches up with the docs" bridge - it makes the
taxonomy real at the Python-package level without a mass move.
"""

from __future__ import annotations

from fdai.core import conversation as conversation  # noqa: F401 - facade re-export
from fdai.core import notifications as notifications  # noqa: F401 - facade re-export
from fdai.core import operator_memory as operator_memory  # noqa: F401 - facade re-export
from fdai.core import rbac as rbac  # noqa: F401 - facade re-export
from fdai.core import report_feed as report_feed  # noqa: F401 - facade re-export

__all__ = [
    "conversation",
    "operator_memory",
    "rbac",
    "notifications",
    "report_feed",
]
