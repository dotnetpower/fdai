"""FDAI pantheon runtime.

The pantheon is a fixed upstream set of 15 named agents that own the
runtime control plane. This package exposes the agent contract, the
registry, and the topic naming convention. Behavior for individual
agents lands wave-by-wave (see
`docs/roadmap/agents/agent-pantheon-implementation.md`); Wave 1 ships the
scaffolding only.

Design authority: `docs/roadmap/agents/agent-pantheon.md`.
"""

from fdai.agents._framework.base import Agent, AgentSpec, Layer
from fdai.agents._framework.bus import PantheonBus
from fdai.agents._framework.bus_bridge import AgentHandlerObserver, AgentHandlerPhase
from fdai.agents._framework.divergence import ShadowDivergenceLedger
from fdai.agents._framework.factory import instantiate_pantheon
from fdai.agents._framework.pantheon import (
    HARD_DEPENDENCY_AGENTS,
    LLM_HOT_PATH_ALLOWLIST,
    PANTHEON_NAMES,
    PANTHEON_SPECS,
)
from fdai.agents._framework.registry import PantheonRegistry, load_pantheon
from fdai.agents._framework.runtime import PantheonRuntime
from fdai.agents._framework.topics import (
    OWNED_OBJECT_TOPICS,
    partition_key_for,
    topic_for_object_type,
)
from fdai.agents._framework.workflows import WORKFLOWS, WorkflowSpec
from fdai.agents.norns import Norns

__all__ = [
    "Agent",
    "AgentHandlerObserver",
    "AgentHandlerPhase",
    "AgentSpec",
    "Layer",
    "Norns",
    "PantheonBus",
    "PantheonRegistry",
    "PantheonRuntime",
    "ShadowDivergenceLedger",
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
