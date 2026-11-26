"""Permanent facade-only Operator domain for the core package.

Groups these subsystems: conversation, operator_memory, rbac, notifications, report_feed.

Physical subsystems stay at ``fdai.core.<subsystem>``. This facade-only
layout is the final G-1 architecture: grouped imports provide navigation,
while direct imports preserve compatibility and keep subsystem gates precise.
A future physical move requires its own reviewed design.
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
