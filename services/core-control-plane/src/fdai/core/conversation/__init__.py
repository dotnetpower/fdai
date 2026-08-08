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

from fdai.core.conversation.adapter_health import (
    AdapterFallbackAuthorizer,
    AdapterFallbackNotifier,
    AdapterFallbackRoute,
    AdapterHealthAuthorizer,
    AdapterHealthConfig,
    AdapterHealthService,
)
from fdai.core.conversation.attachment_directive import (
    AttachmentDirective,
    parse_attachment_directive,
)
from fdai.core.conversation.binding_delivery_context import (
    ChannelScopeResolver,
    VerifiedBindingDeliveryContextResolver,
)
from fdai.core.conversation.busy_input import (
    BusyInput,
    BusyInputDecision,
    BusyInputDisposition,
    BusyInputKind,
    BusyInputMode,
    BusyPendingStatus,
    BusySessionState,
    PendingBusyInput,
    arbitrate_busy_input,
    consume_pending_input,
    finish_active_turn,
)
from fdai.core.conversation.busy_input_coordinator import (
    ActiveConversationTurn,
    BusyInputCoordinator,
    BusyInputMetrics,
)
from fdai.core.conversation.busy_input_store import (
    BusyInputConflictError,
    BusyInputStore,
    InMemoryBusyInputStore,
)
from fdai.core.conversation.channel_access import (
    ChannelAccessError,
    ChannelAccessMode,
    ChannelAccessService,
    ChannelIdentityDirectory,
    ChannelPairingStore,
    ChannelSenderKey,
    InMemoryChannelPairingStore,
    PairingApprovalAuthorizer,
    PairingChallenge,
    PairingCreateResult,
    PairingRequest,
)
from fdai.core.conversation.channel_gateway import (
    AttachmentIngestionResult,
    ChannelAttachmentIngestor,
    ChannelBusyInputModeResolver,
    ChannelDeliveryContext,
    ChannelDeliveryContextResolver,
    ChannelMessageLedger,
    ChannelPrincipalResolver,
    ConversationChannelGateway,
    DurableChannelDelivery,
    SessionLoader,
)
from fdai.core.conversation.context_bridge import (
    assemble_turn_context,
    operator_memory_to_entries,
    session_to_working_context,
)
from fdai.core.conversation.coordinator import (
    ConversationCoordinator,
    CoordinatorConfig,
)
from fdai.core.conversation.creation import (
    CreateIncidentCommand,
    CreateScheduledTaskCommand,
    CreationForbiddenError,
)
from fdai.core.conversation.identity_links import (
    CrossChannelIdentityLink,
    CrossChannelIdentityLinkError,
    CrossChannelIdentityLinkService,
    CrossChannelIdentityLinkStore,
    InMemoryCrossChannelIdentityLinkStore,
)
from fdai.core.conversation.identity_verification import (
    AuthorizedChannelPrincipal,
    ChannelIdentityVerificationError,
    ChannelIdentityVerificationHooks,
    ChannelPrincipalAuthorizationMapping,
    PrincipalScopeAuthorization,
)
from fdai.core.conversation.narrator import (
    ClarificationNarrator,
    ContextualNarrator,
    DeterministicKeywordNarrator,
    GroundedAnswerNarrator,
    Narrator,
    ReadPlanNarrator,
    ToolSchema,
    default_tool_schemas,
    format_prompt_tool_list,
)
from fdai.core.conversation.outbound_delivery import (
    DurableOutboundDeliveryConfig,
    DurableOutboundDeliveryCoordinator,
)
from fdai.core.conversation.principal_binding import (
    PrincipalConversationBindingAuthorizer,
    PrincipalConversationBindingService,
    PrincipalConversationBindingStore,
)
from fdai.core.conversation.session import (
    ConversationSession,
    Principal,
    Role,
    Turn,
)
from fdai.core.conversation.skill_discovery import (
    DescribeRuntimeSkillBundleTool,
    DescribeRuntimeSkillTool,
    ListRuntimeSkillBundlesTool,
    ListRuntimeSkillsTool,
    LoadRuntimeSkillBundleTool,
    LoadRuntimeSkillTool,
    ReadRuntimeSkillReferenceTool,
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
    SearchConversationsTool,
)
from fdai.core.conversation.tool_discovery import (
    DescribeRuntimeTool,
    RuntimeToolDiscovery,
    SearchRuntimeToolsTool,
    ToolDescriptor,
    ToolDiscoveryError,
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
    "AdapterFallbackAuthorizer",
    "AdapterFallbackNotifier",
    "AdapterFallbackRoute",
    "AdapterHealthAuthorizer",
    "AdapterHealthConfig",
    "AdapterHealthService",
    "ActivateBreakGlassTool",
    "ActiveConversationTurn",
    "ApproveHilTool",
    "AuditReader",
    "AuditWriter",
    "AttachmentIngestionResult",
    "AttachmentDirective",
    "AuthorizedChannelPrincipal",
    "BusyInput",
    "BusyInputConflictError",
    "BusyInputCoordinator",
    "BusyInputDecision",
    "BusyInputDisposition",
    "BusyInputKind",
    "BusyInputMode",
    "BusyInputMetrics",
    "BusyInputStore",
    "BusyPendingStatus",
    "BusySessionState",
    "ChannelAccessError",
    "ChannelAccessMode",
    "ChannelAccessService",
    "ChannelAttachmentIngestor",
    "ChannelBusyInputModeResolver",
    "ChannelDeliveryContext",
    "ChannelDeliveryContextResolver",
    "ChannelIdentityDirectory",
    "ChannelMessageLedger",
    "ChannelPairingStore",
    "ChannelPrincipalResolver",
    "ChannelPrincipalAuthorizationMapping",
    "ChannelScopeResolver",
    "ChannelSenderKey",
    "ClarificationNarrator",
    "ContextualNarrator",
    "CrossChannelIdentityLink",
    "CrossChannelIdentityLinkError",
    "CrossChannelIdentityLinkService",
    "CrossChannelIdentityLinkStore",
    "ConversationCoordinator",
    "ConversationChannelGateway",
    "ConversationSession",
    "CoordinatorConfig",
    "CorrelateIncidentTool",
    "CreateIncidentCommand",
    "CreateScheduledTaskCommand",
    "CreationForbiddenError",
    "DescribeEventTool",
    "DescribeRuntimeTool",
    "DescribeRuntimeSkillTool",
    "DescribeRuntimeSkillBundleTool",
    "DurableChannelDelivery",
    "DurableOutboundDeliveryConfig",
    "DurableOutboundDeliveryCoordinator",
    "DeterministicKeywordNarrator",
    "GroundedAnswerNarrator",
    "ExplainVerdictTool",
    "ExploreCatalogTool",
    "InventoryProvider",
    "InMemoryBusyInputStore",
    "InMemoryChannelPairingStore",
    "InMemoryCrossChannelIdentityLinkStore",
    "ChannelIdentityVerificationError",
    "ChannelIdentityVerificationHooks",
    "ListHilTool",
    "ListRuntimeSkillsTool",
    "ListRuntimeSkillBundlesTool",
    "LoadRuntimeSkillBundleTool",
    "LoadRuntimeSkillTool",
    "Narrator",
    "ReadPlanNarrator",
    "Principal",
    "PrincipalConversationBindingAuthorizer",
    "PrincipalConversationBindingService",
    "PrincipalConversationBindingStore",
    "PrincipalScopeAuthorization",
    "parse_attachment_directive",
    "PairingApprovalAuthorizer",
    "PairingChallenge",
    "PairingCreateResult",
    "PairingRequest",
    "PendingBusyInput",
    "QueryAuditTool",
    "QueryDeploymentsTool",
    "QueryInventoryTool",
    "QueryLogTool",
    "QueryMetricTool",
    "QueryOperatorMemoryTool",
    "ReadRuntimeSkillReferenceTool",
    "Role",
    "RunRunbookTool",
    "SearchConversationsTool",
    "SearchRuntimeToolsTool",
    "RuntimeToolDiscovery",
    "SessionLoader",
    "SimulateChangeTool",
    "SystemConsoleTool",
    "ToolResult",
    "ToolDescriptor",
    "ToolDiscoveryError",
    "ToolSchema",
    "Turn",
    "VerifiedBindingDeliveryContextResolver",
    "arbitrate_busy_input",
    "assemble_turn_context",
    "consume_pending_input",
    "default_tool_schemas",
    "format_prompt_tool_list",
    "finish_active_turn",
    "operator_memory_to_entries",
    "session_to_working_context",
]
