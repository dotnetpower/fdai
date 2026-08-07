"""Resolve server-owned user and assurance policies for one conversation turn."""

from __future__ import annotations

from typing import Any

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


async def with_compiled_user_policy(
    view_context: dict[str, Any],
    *,
    user_id: str,
    store: ConversationPolicyStore | None,
) -> dict[str, Any]:
    """Replace client policy input with the principal's compiled server policy."""

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


async def with_assurance_policy(
    view_context: dict[str, Any],
    *,
    user_id: str,
    request_id: str,
    runtime: ConversationPolicyRuntime | None,
) -> dict[str, Any]:
    """Replace client policy input with one server-resolved assurance policy."""

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


__all__ = ["with_assurance_policy", "with_compiled_user_policy"]
