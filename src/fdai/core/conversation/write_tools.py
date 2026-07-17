"""Compatibility facade for conversation write-class tools.

Implementations live in private sibling modules grouped by responsibility.
This module preserves the original import surface for composition and tests.
"""

from __future__ import annotations

from uuid import UUID

from fdai.core.conversation._write_audit import (
    AuditWriter,
)
from fdai.core.conversation._write_audit import (
    _extract_resource_type as _extract_resource_type,
)
from fdai.core.conversation._write_break_glass_tool import (
    ActivateBreakGlassTool,
)
from fdai.core.conversation._write_break_glass_tool import (
    _redact_secrets as _redact_secrets,
)
from fdai.core.conversation._write_hil_tools import (
    ApproveHilTool,
    ListHilTool,
)
from fdai.core.conversation._write_hil_tools import (
    _project_pending_item as _project_pending_item,
)
from fdai.core.conversation._write_runbook_tool import RunRunbookTool
from fdai.core.conversation._write_simulation_tool import (
    SimulateChangeTool,
)
from fdai.core.conversation._write_simulation_tool import (
    _build_synthetic_event as _build_synthetic_event,
)
from fdai.core.conversation._write_simulation_tool import (
    _enum_value as _enum_value,
)
from fdai.core.conversation._write_simulation_tool import (
    _preview as _preview,
)

_ = UUID

__all__ = [
    "ActivateBreakGlassTool",
    "ApproveHilTool",
    "AuditWriter",
    "ListHilTool",
    "RunRunbookTool",
    "SimulateChangeTool",
]
