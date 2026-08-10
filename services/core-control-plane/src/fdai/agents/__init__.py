"""FDAI pantheon runtime.

The pantheon is a fixed upstream set of 15 named agents that own the
runtime control plane. This package exposes the agent contract, the
registry, and the topic naming convention. Behavior for individual
agents lands wave-by-wave (see
`docs/roadmap/agents/agent-pantheon-implementation.md`); Wave 1 ships the
scaffolding only.

Design authority: `docs/roadmap/agents/agent-pantheon.md`.
"""

from fdai.agents._framework.adapters import (
    AdminCard,
    AdminNotificationAdapter,
    GitHubIssue,
    IssueTrackerAdapter,
)
from fdai.agents._framework.base import (
    Agent,
    AgentSpec,
    ConversationCharter,
    ConversationTool,
    Layer,
)
from fdai.agents._framework.bus import PantheonBus
from fdai.agents._framework.bus_bridge import AgentHandlerObserver, AgentHandlerPhase
from fdai.agents._framework.catalog_review_wiring import CatalogReviewBindings
from fdai.agents._framework.conversation_prompt import (
    BASELINE_LAYER_IDS,
    CONSTRAINT_LAYER_IDS,
    ComposedConversationPrompt,
    ConversationSituation,
)
from fdai.agents._framework.conversation_tools import AgentToolResult, AgentToolStatus
from fdai.agents._framework.deliberation import (
    DeliberationClaim,
    DeliberationRequest,
    SynthesisOutcome,
    T2ConversationSynthesizer,
)
from fdai.agents._framework.divergence import ShadowDivergenceLedger
from fdai.agents._framework.factory import instantiate_pantheon
from fdai.agents._framework.introspection import agent_state_evidence_ref
from fdai.agents._framework.pantheon import (
    HARD_DEPENDENCY_AGENTS,
    LLM_HOT_PATH_ALLOWLIST,
    PANTHEON_NAMES,
    PANTHEON_SPECS,
)
from fdai.agents._framework.provider_adapters import (
    StateStoreActionRunStore,
    StateStoreAuditChainAdapter,
)
from fdai.agents._framework.registry import PantheonRegistry, load_pantheon
from fdai.agents._framework.runtime import PantheonRuntime
from fdai.agents._framework.semantic_routing import SemanticRouterConfig
from fdai.agents._framework.tool_planner import (
    MAX_TOOL_PLANS,
    ConversationToolPlan,
    plan_conversation_tools,
)
from fdai.agents._framework.tool_semantic import SemanticToolConfig, SemanticToolPlanner
from fdai.agents._framework.topics import (
    OWNED_OBJECT_TOPICS,
    partition_key_for,
    topic_for_object_type,
)
from fdai.agents._framework.workflows import WORKFLOWS, WorkflowSpec
from fdai.agents.bragi import Bragi
from fdai.agents.forseti import Forseti
from fdai.agents.heimdall import Heimdall
from fdai.agents.norns import Norns
from fdai.agents.saga import Saga
from fdai.agents.vidar import Vidar

__all__ = [
    "Agent",
    "AdminCard",
    "AdminNotificationAdapter",
    "BASELINE_LAYER_IDS",
    "CONSTRAINT_LAYER_IDS",
    "AgentHandlerObserver",
    "AgentHandlerPhase",
    "AgentSpec",
    "MAX_TOOL_PLANS",
    "AgentToolResult",
    "AgentToolStatus",
    "ConversationToolPlan",
    "SemanticToolConfig",
    "SemanticToolPlanner",
    "agent_state_evidence_ref",
    "Bragi",
    "CatalogReviewBindings",
    "ComposedConversationPrompt",
    "ConversationCharter",
    "ConversationSituation",
    "ConversationTool",
    "DeliberationClaim",
    "DeliberationRequest",
    "Forseti",
    "Heimdall",
    "GitHubIssue",
    "IssueTrackerAdapter",
    "Layer",
    "Norns",
    "PantheonBus",
    "PantheonRegistry",
    "PantheonRuntime",
    "Saga",
    "SemanticRouterConfig",
    "ShadowDivergenceLedger",
    "StateStoreActionRunStore",
    "StateStoreAuditChainAdapter",
    "SynthesisOutcome",
    "T2ConversationSynthesizer",
    "Vidar",
    "plan_conversation_tools",
    "load_pantheon",
    "instantiate_pantheon",
    "PANTHEON_SPECS",
    "PANTHEON_NAMES",
    "HARD_DEPENDENCY_AGENTS",
    "LLM_HOT_PATH_ALLOWLIST",
    "OWNED_OBJECT_TOPICS",
    "topic_for_object_type",
    "partition_key_for",
    "WORKFLOWS",
    "WorkflowSpec",
]
