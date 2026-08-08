"""Runtime selection contract for promoted conversation policies."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from fdai.core.conversation_assurance.promotion import ChatPolicyTarget, PolicyStage

BASE_POLICY_DIGEST = "0" * 64

_TRAFFIC_PERCENT = {
    PolicyStage.SHADOW: 0,
    PolicyStage.CANARY_1: 1,
    PolicyStage.CANARY_5: 5,
    PolicyStage.CANARY_25: 25,
    PolicyStage.ACTIVE: 100,
    PolicyStage.ROLLED_BACK: 0,
}


@dataclass(frozen=True, slots=True)
class AppliedChatPolicy:
    candidate_id: str
    principal_scope: str
    target: ChatPolicyTarget
    policy_digest: str
    policy_text: str
    stage: PolicyStage

    def __post_init__(self) -> None:
        if not self.candidate_id.strip() or not self.principal_scope.strip():
            raise ValueError("applied chat policy identity MUST be non-empty")
        if not self.policy_text.strip() or len(self.policy_text) > 2_000:
            raise ValueError("applied chat policy text MUST contain 1..2000 characters")
        if hashlib.sha256(self.policy_text.encode()).hexdigest() != self.policy_digest:
            raise ValueError("applied chat policy text MUST match policy_digest")


def policy_is_assigned(policy: AppliedChatPolicy, *, assignment_key: str) -> bool:
    """Return a stable canary assignment for one server-owned turn key."""

    if not assignment_key.strip():
        raise ValueError("chat policy assignment_key MUST be non-empty")
    percent = _TRAFFIC_PERCENT[policy.stage]
    if percent in {0, 100}:
        return percent == 100
    material = "\0".join((policy.principal_scope, assignment_key, policy.candidate_id))
    bucket = int.from_bytes(hashlib.sha256(material.encode()).digest()[:8], "big") % 100
    return bucket < percent


@runtime_checkable
class ConversationPolicyRuntime(Protocol):
    async def current_digest(
        self,
        *,
        principal_scope: str,
        target: ChatPolicyTarget,
    ) -> str: ...

    async def resolve(
        self,
        *,
        principal_scope: str,
        target: ChatPolicyTarget,
        assignment_key: str,
    ) -> AppliedChatPolicy | None: ...


__all__ = [
    "BASE_POLICY_DIGEST",
    "AppliedChatPolicy",
    "ConversationPolicyRuntime",
    "policy_is_assigned",
]
