"""Operator console (conversational surface) - Layer 2 coordinator.

Implements the pull-direction console described in
[operator-console.md](../../../../docs/roadmap/operator-console.md).

This module is deliberately kept **minimal at Day 1**: it ships the five
read-only :class:`SystemConsoleTool` implementations plus a
:class:`ConversationCoordinator` that maps a natural-language turn onto
one tool call via a Chat T0 intent matcher (regex / keyword; no LLM).
The narrator LLM tier lands in a later wave.

Design points enforced here:

- **LLM is not a judge.** The coordinator never grants execution
  eligibility; it only dispatches read-only tool calls. Write-class
  tools (approve_hil, run_runbook, ...) land in Wave W1 with a
  verifier re-check.
- **Read-only tools are provably side-effect-free.** Every shipped
  :class:`SystemConsoleTool` has ``side_effect_class = 'read'`` and is
  exercised in the module tests to prove no mutation surface is
  touched.
- **Fail closed.** An intent that does not match any Chat T0 pattern
  returns an ``AbstainResult`` with the tool list; the coordinator
  never fabricates a call.

See also:

- :mod:`aiopspilot.core.conversation.tools` - shipped tool
  implementations.
- :mod:`aiopspilot.core.conversation.coordinator` - dispatch entry
  point.
- :mod:`aiopspilot.core.conversation.session` - session data model,
  projected from the audit log.
"""

from __future__ import annotations

from aiopspilot.core.conversation.coordinator import (
    ConversationCoordinator,
    CoordinatorConfig,
)
from aiopspilot.core.conversation.session import (
    ConversationSession,
    Principal,
    Role,
    Turn,
)
from aiopspilot.core.conversation.system_tools import (
    AuditReader,
    DescribeEventTool,
    ExplainVerdictTool,
    InventoryProvider,
    QueryAuditTool,
    QueryInventoryTool,
    QueryOperatorMemoryTool,
)
from aiopspilot.core.conversation.tools import (
    AbstainResult,
    ExploreCatalogTool,
    SystemConsoleTool,
    ToolResult,
)
from aiopspilot.core.conversation.write_tools import (
    ActivateBreakGlassTool,
    ApproveHilTool,
    AuditWriter,
    ListHilTool,
    RunRunbookTool,
    SimulateChangeTool,
)

__all__ = [
    "AbstainResult",
    "ActivateBreakGlassTool",
    "ApproveHilTool",
    "AuditReader",
    "AuditWriter",
    "ConversationCoordinator",
    "ConversationSession",
    "CoordinatorConfig",
    "DescribeEventTool",
    "ExplainVerdictTool",
    "ExploreCatalogTool",
    "InventoryProvider",
    "ListHilTool",
    "Principal",
    "QueryAuditTool",
    "QueryInventoryTool",
    "QueryOperatorMemoryTool",
    "Role",
    "RunRunbookTool",
    "SimulateChangeTool",
    "SystemConsoleTool",
    "ToolResult",
    "Turn",
]
