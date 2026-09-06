"""Compose bounded, server-owned conversation profiles without runtime prose."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol

from fdai.core.conversation.model_observation import ConversationModelResponse
from fdai.shared.contracts.models import LifecycleOwner

ADAPTIVE_STAGES = ("plan", "answer", "review", "refine", "verify")
ADAPTIVE_STAGE_PACK_IDS = frozenset(f"adaptive-{stage}" for stage in ADAPTIVE_STAGES)
MAX_ADAPTIVE_SYSTEM_TOKENS = 8_192


class AdaptiveModel(Protocol):
    """Propose one structured record without retries or execution authority."""

    async def complete(
        self,
        *,
        stage: str,
        system_prompt: str,
        payload: Mapping[str, object],
        schema: Mapping[str, object],
        escalated: bool = False,
    ) -> ConversationModelResponse | None:
        """Return measured output, or ``None`` when this single attempt is unavailable."""


class ConversationRelationshipKind(StrEnum):
    """Presentation-only relationships, never roles or permission grants."""

    COLLABORATOR = "collaborator"
    STEWARD = "steward"


@dataclass(frozen=True, slots=True)
class VerifiedConversationRelationship:
    """Current server-verified relationship facts with no free-text fields.

    Only authenticated server context may construct this value. The caller must
    recheck the authoritative revision each turn; this value is not an identity
    credential and must never be deserialized from an operator request.
    Source revisions stay on this audit value, not in the model's system text.
    """

    kind: ConversationRelationshipKind
    target_agent: str
    source_revision: str
    verified_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.kind, ConversationRelationshipKind):
            raise ValueError("conversation relationship kind MUST be a closed enum")
        if self.target_agent not in {owner.value for owner in LifecycleOwner}:
            raise ValueError("conversation relationship MUST bind a canonical target")
        if (
            not isinstance(self.source_revision, str)
            or not 1 <= len(self.source_revision) <= 256
            or any(not 33 <= ord(char) <= 126 for char in self.source_revision)
            or self.source_revision.casefold() in {"unversioned", "unknown", "unavailable"}
        ):
            raise ValueError("conversation relationship MUST have a bounded source revision")
        if not _aware(self.verified_at) or not _aware(self.expires_at):
            raise ValueError("conversation relationship timestamps MUST be timezone-aware")
        if not 0 < (self.expires_at - self.verified_at).total_seconds() <= 300:
            raise ValueError("conversation relationship lifetime MUST be in (0, 300] seconds")

    def is_current_for(self, agent: str, now: datetime) -> bool:
        """Check target and expiry without interpreting the proof as authorization."""
        return (
            self.target_agent == agent and _aware(now) and self.verified_at <= now < self.expires_at
        )


def _aware(value: object) -> bool:
    return (
        isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() is not None
    )


@dataclass(frozen=True, slots=True)
class ConversationProfile:
    """Immutable presentation profile, constructed from a Pantheon descriptor.

    Composition validates the agent against the fixed Pantheon and supplies its
    role directive. Core deliberately does not import agents. Neither this
    profile nor its optional relationship confers approval or execution rights.
    """

    agent: str
    role_directive: str
    locale: str = "en"
    relationship: VerifiedConversationRelationship | None = None

    def __post_init__(self) -> None:
        if self.agent not in {owner.value for owner in LifecycleOwner}:
            raise ValueError("conversation agent MUST be a canonical server-selected name")
        if (
            not isinstance(self.role_directive, str)
            or not self.role_directive.strip()
            or len(self.role_directive.encode("utf-8")) > 4_096
        ):
            raise ValueError("conversation role directive MUST be server-owned and bounded")
        if self.locale not in {"en", "ko"}:
            raise ValueError("conversation locale MUST be en or ko")
        if self.relationship is not None and not isinstance(
            self.relationship, VerifiedConversationRelationship
        ):
            raise ValueError("conversation relationship MUST be verified server context")
        if self.relationship is not None and self.relationship.target_agent != self.agent:
            raise ValueError("conversation relationship MUST bind the selected profile agent")


def compose_adaptive_prompt(
    profile: ConversationProfile,
    stage: str,
    base_text: str,
    *,
    max_system_tokens: int = MAX_ADAPTIVE_SYSTEM_TOKENS,
    now: datetime | None = None,
) -> str:
    """Append only trusted profile facts to a catalog-composed stage prompt.

    ``base_text`` must contain the common policy and exactly the selected stage
    pack. Operator, history, document, and tool prose belong exclusively in the
    model's user-message data envelope. UTF-8 byte count is a conservative token
    upper bound; over-budget prompts fail intact rather than truncating policy.
    Expired relationships become explicitly unknown without removing the fixed role.
    """

    if stage not in ADAPTIVE_STAGES:
        raise ValueError("adaptive prompt stage is unsupported")
    if not isinstance(base_text, str) or not base_text.strip():
        raise ValueError("adaptive prompt requires catalog-owned policy")
    if type(max_system_tokens) is not int or not 1 <= max_system_tokens <= 32_768:
        raise ValueError("adaptive system token budget MUST be in [1, 32768]")
    relationship = profile.relationship
    if relationship is not None and not relationship.is_current_for(
        profile.agent, now if now is not None else datetime.now(UTC)
    ):
        relationship = None
    server_profile: dict[str, object] = {
        "agent": profile.agent,
        "role_directive": profile.role_directive,
        "locale": profile.locale,
        "stage": stage,
        "relationship": (
            {
                "kind": relationship.kind.value,
                "current": True,
            }
            if relationship is not None
            else None
        ),
        "relationship_status": "verified" if relationship is not None else "unknown",
        "execution_authority": False,
    }
    prompt = (
        base_text
        + "\n\n"
        + json.dumps({"server_profile": server_profile}, ensure_ascii=False, sort_keys=True)
    )
    if len(prompt.encode("utf-8")) > max_system_tokens:
        raise ValueError("adaptive prompt exceeds its conservative system token budget")
    return prompt


__all__ = [
    "ADAPTIVE_STAGES",
    "ADAPTIVE_STAGE_PACK_IDS",
    "MAX_ADAPTIVE_SYSTEM_TOKENS",
    "AdaptiveModel",
    "ConversationProfile",
    "ConversationRelationshipKind",
    "VerifiedConversationRelationship",
    "compose_adaptive_prompt",
]
