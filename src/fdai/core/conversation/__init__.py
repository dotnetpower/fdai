"""Operator console (conversational surface) - Layer 2 coordinator.

Implements the pull-direction console described in
[operator-console.md](../../../../docs/roadmap/interfaces/operator-console.md).

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

- :mod:`fdai.core.conversation.tools` - shipped tool
  implementations.
- :mod:`fdai.core.conversation.coordinator` - dispatch entry
  point.
- :mod:`fdai.core.conversation.session` - session data model,
  projected from the audit log.
"""

from __future__ import annotations

from fdai.core.conversation.context_bridge import session_to_working_context
from fdai.core.conversation.coordinator import (
    ConversationCoordinator,
    CoordinatorConfig,
)
from fdai.core.conversation.creation import (
    CreateIncidentCommand,
    CreateScheduledTaskCommand,
    CreationForbiddenError,
)
from fdai.core.conversation.narrator import (
    DeterministicKeywordNarrator,
    Narrator,
    ToolSchema,
    default_tool_schemas,
    format_prompt_tool_list,
)
from fdai.core.conversation.session import (
    ConversationSession,
    Principal,
    Role,
    Turn,
)
from fdai.core.conversation.system_tools import (
    AuditReader,
    CorrelateIncidentTool,
    DescribeEventTool,
    ExplainVerdictTool,
    InventoryProvider,
    QueryAuditTool,
    QueryDeploymentsTool,
    QueryInventoryTool,
    QueryLogTool,
    QueryMetricTool,
    QueryOperatorMemoryTool,
)
from fdai.core.conversation.tools import (
    AbstainResult,
    ExploreCatalogTool,
    SystemConsoleTool,
    ToolResult,
)
from fdai.core.conversation.write_tools import (
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
    "CorrelateIncidentTool",
    "CreateIncidentCommand",
    "CreateScheduledTaskCommand",
    "CreationForbiddenError",
    "DescribeEventTool",
    "DeterministicKeywordNarrator",
    "ExplainVerdictTool",
    "ExploreCatalogTool",
    "InventoryProvider",
    "ListHilTool",
    "Narrator",
    "Principal",
    "QueryAuditTool",
    "QueryDeploymentsTool",
    "QueryInventoryTool",
    "QueryLogTool",
    "QueryMetricTool",
    "QueryOperatorMemoryTool",
    "Role",
    "RunRunbookTool",
    "SimulateChangeTool",
    "SystemConsoleTool",
    "ToolResult",
    "ToolSchema",
    "Turn",
    "default_tool_schemas",
    "format_prompt_tool_list",
    "session_to_working_context",
]
