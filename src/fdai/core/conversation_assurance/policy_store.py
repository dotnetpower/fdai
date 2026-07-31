"""Scoped persistence contract for chat-policy candidates and transitions."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import Protocol, runtime_checkable

from fdai.core.conversation_assurance.promotion import (
    ChatPolicyCandidate,
    PolicyStage,
    PolicyTransition,
)


@runtime_checkable
class ConversationPolicyCandidateStore(Protocol):
    async def append_candidate(self, candidate: ChatPolicyCandidate) -> bool: ...

    async def get_candidate(
        self,
        *,
        principal_scope: str,
        candidate_id: str,
    ) -> ChatPolicyCandidate | None: ...

    async def apply_transition(
        self,
        *,
        principal_scope: str,
        transition: PolicyTransition,
    ) -> ChatPolicyCandidate: ...

    async def list_transitions(
        self,
        *,
        principal_scope: str,
        candidate_id: str,
        limit: int = 100,
    ) -> tuple[PolicyTransition, ...]: ...


class InMemoryConversationPolicyCandidateStore:
    """Process-local adapter with the same scoped CAS semantics as persistence."""

    def __init__(self) -> None:
        self._candidates: dict[str, ChatPolicyCandidate] = {}
        self._transitions: dict[str, list[PolicyTransition]] = {}
        self._lock = asyncio.Lock()

    async def append_candidate(self, candidate: ChatPolicyCandidate) -> bool:
        async with self._lock:
            if candidate.stage is not PolicyStage.SHADOW:
                raise ValueError("new policy candidates MUST start in shadow")
            existing = self._candidates.get(candidate.candidate_id)
            if existing is not None:
                if existing != candidate:
                    raise ValueError("candidate id already belongs to different content")
                return False
            self._candidates[candidate.candidate_id] = candidate
            return True

    async def get_candidate(
        self,
        *,
        principal_scope: str,
        candidate_id: str,
    ) -> ChatPolicyCandidate | None:
        candidate = self._candidates.get(candidate_id)
        if candidate is None or candidate.principal_scope != principal_scope:
            return None
        return candidate

    async def apply_transition(
        self,
        *,
        principal_scope: str,
        transition: PolicyTransition,
    ) -> ChatPolicyCandidate:
        async with self._lock:
            candidate = self._candidates.get(transition.candidate_id)
            if candidate is None or candidate.principal_scope != principal_scope:
                raise LookupError("policy candidate is unavailable in the principal scope")
            history = self._transitions.setdefault(candidate.candidate_id, [])
            if transition in history:
                return candidate
            if candidate.stage is not transition.from_stage:
                raise ValueError("policy transition from_stage is stale")
            updated = replace(candidate, stage=transition.to_stage)
            self._candidates[candidate.candidate_id] = updated
            history.append(transition)
            return updated

    async def list_transitions(
        self,
        *,
        principal_scope: str,
        candidate_id: str,
        limit: int = 100,
    ) -> tuple[PolicyTransition, ...]:
        _require_limit(limit)
        candidate = self._candidates.get(candidate_id)
        if candidate is None or candidate.principal_scope != principal_scope:
            return ()
        return tuple(self._transitions.get(candidate_id, ())[-limit:])


def _require_limit(limit: int) -> None:
    if isinstance(limit, bool) or not 1 <= limit <= 1_000:
        raise ValueError("policy transition limit MUST be in [1, 1000]")


__all__ = [
    "ConversationPolicyCandidateStore",
    "InMemoryConversationPolicyCandidateStore",
]
