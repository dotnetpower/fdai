"""Shared validation, metadata, and policy helpers for chat routes."""

from __future__ import annotations

import hashlib
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, Final

from starlette.requests import Request

from fdai.core.conversation.policy_prompt import UserPolicyCompiler
from fdai.core.conversation_assurance import (
    ChatPolicyTarget,
    ConversationPolicyRuntime,
    assurance_principal_scope,
)
from fdai.delivery.operator_api.application.conversation.prompt import (
    _ASSURANCE_POLICY_KEY,
    _COMPILED_USER_POLICY_KEY,
)
from fdai.shared.providers.briefing import ConversationPolicyStore

DEFAULT_MAX_BODY_BYTES: Final[int] = 200_000


# The chat routes accept up to DEFAULT_MAX_IMAGES inline base64 images as
# read-only vision evidence, so their body cap is raised to fit that bounded
# payload: DEFAULT_MAX_IMAGES (4) * DEFAULT_MAX_IMAGE_BYTES (4 MiB) * 4/3
# (base64 expansion) plus headroom for the prompt, history, and JSON framing.
DEFAULT_MAX_CHAT_BODY_BYTES: Final[int] = 26 * 1024 * 1024


def _turn_metadata(
    *,
    model: str,
    view_context: Mapping[str, Any],
    answer_planning: Mapping[str, object] | None = None,
) -> dict[str, Any]:
    """Persist replay evidence while keeping it out of the browser payload."""

    metadata: dict[str, Any] = {"model": model}
    web = view_context.get("_web_evidence")
    if isinstance(web, Mapping):
        metadata["web_evidence"] = dict(web)
    if answer_planning is not None:
        metadata["answer_planning"] = dict(answer_planning)
    return metadata


def _metering_correlation_id(user_id: str, session_id: str) -> str:
    """Return an opaque, stable metering key for one operator conversation."""
    digest = hashlib.sha256(f"{user_id}\0{session_id}".encode()).hexdigest()[:32]
    return f"chat-{digest}"


def _uses_evidence_fast_path(view_context: Mapping[str, Any]) -> bool:
    """Return whether server evidence can render the answer without a model."""

    if isinstance(view_context.get("_behavior_evidence"), Mapping):
        return True
    graph_evidence = view_context.get("_intent_graph_evidence")
    if isinstance(graph_evidence, Mapping) and graph_evidence.get("status") != "completed":
        return True
    tool = view_context.get("_tool_evidence")
    if isinstance(tool, Mapping) and tool.get("tool") in {
        "describe_read_sources",
        "get_current_time",
        "get_kpi",
        "list_hil",
        "list_incidents",
        "query_action_context",
        "query_audit",
        "query_conversation_context",
        "query_inventory",
        "query_knowledge_context",
        "query_detection_readiness",
        "query_log",
        "query_llm_usage",
        "query_network_reachability",
        "query_subscription_scope",
        "query_subscription_health",
    }:
        return True
    raw = view_context.get("_operational_evidence")
    return isinstance(raw, Mapping)


AuthorizeFn = Callable[[Request], Awaitable[str]]


async def _with_compiled_user_policy(
    view_context: dict[str, Any],
    *,
    user_id: str,
    store: ConversationPolicyStore | None,
) -> dict[str, Any]:
    enriched = dict(view_context)
    enriched.pop(_COMPILED_USER_POLICY_KEY, None)
    if store is None:
        return enriched
    policies = tuple(await store.list_for_principal(principal_id=user_id))
    compiled = UserPolicyCompiler().compile(policies)
    if compiled is None:
        return enriched
    enriched[_COMPILED_USER_POLICY_KEY] = {
        "text": compiled.system_text,
        "policy_refs": list(compiled.policy_refs),
        "compiler_version": compiled.compiler_version,
    }
    return enriched


async def _with_assurance_policy(
    view_context: dict[str, Any],
    *,
    user_id: str,
    request_id: str,
    runtime: ConversationPolicyRuntime | None,
) -> dict[str, Any]:
    """Replace any client value with one server-resolved canary policy."""

    enriched = dict(view_context)
    enriched.pop(_ASSURANCE_POLICY_KEY, None)
    if runtime is None:
        return enriched
    policy = await runtime.resolve(
        principal_scope=assurance_principal_scope(user_id),
        target=ChatPolicyTarget.NARRATOR_PROMPT,
        assignment_key=request_id,
    )
    if policy is None:
        return enriched
    enriched[_ASSURANCE_POLICY_KEY] = {
        "candidate_id": policy.candidate_id,
        "policy_digest": policy.policy_digest,
        "stage": policy.stage.value,
        "target": policy.target.value,
        "text": policy.policy_text,
    }
    return enriched
