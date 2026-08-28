"""Small model boundary for social versus operational conversation routing."""

from __future__ import annotations

import logging
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Annotated, Any, Literal, Protocol

from fdai_service_contracts.ontology_query import QueryContract, canonical_json, content_digest
from fdai_service_contracts.semantic_judgment import SemanticDirectResponseDraft
from pydantic import Field, ValidationError, model_validator

from .model_observation import ConversationModelObservation, ConversationModelResponse

_MAX_UTTERANCE_CHARS = 32_000
_MAX_CONTEXT_ITEMS = 4
_MAX_CONTEXT_CHARS = 4_000
_MAX_PROFILE_BYTES = 16_384
_MAX_SCHEMA_ATTEMPTS = 2
_LOGGER = logging.getLogger(__name__)


class SocialAct(StrEnum):
    """Optional social meaning that never grants operational authority."""

    NONE = "none"
    GREETING = "greeting"
    ACKNOWLEDGEMENT = "acknowledgement"
    THANKS = "thanks"
    FAREWELL = "farewell"
    SELF_INTRODUCTION = "self_introduction"


DIRECT_SOCIAL_ACTS = frozenset(
    {
        SocialAct.GREETING,
        SocialAct.THANKS,
        SocialAct.FAREWELL,
        SocialAct.SELF_INTRODUCTION,
    }
)
SOCIAL_NARRATOR_CAPABILITY_IDS = MappingProxyType(
    {
        SocialAct.GREETING: "conversation.social-narrator.greeting",
        SocialAct.THANKS: "conversation.social-narrator.thanks",
        SocialAct.FAREWELL: "conversation.social-narrator.farewell",
        SocialAct.SELF_INTRODUCTION: "conversation.social-narrator.self_introduction",
    }
)
if frozenset(SOCIAL_NARRATOR_CAPABILITY_IDS) != DIRECT_SOCIAL_ACTS:
    raise RuntimeError("every direct social act requires one reviewed narrator prompt mapping")


class OperationalSignal(StrEnum):
    """Whether the complete turn requires operational semantic planning."""

    NONE = "none"
    EXPLICIT = "explicit"
    CONTEXTUAL = "contextual"
    MIXED = "mixed"


class ContextDependency(StrEnum):
    """Whether interpreting the turn depends on prior operational state."""

    NONE = "none"
    SOCIAL_CONTINUITY = "social_continuity"
    ACTIVE_THREAD = "active_thread"
    PENDING_DECISION = "pending_decision"
    AMBIGUOUS = "ambiguous"


class ConversationPreflightProposal(QueryContract):
    """Untrusted compact route proposal without user-facing response prose."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    social_act: SocialAct
    operational_signal: OperationalSignal
    context_dependency: ContextDependency
    confidence: Annotated[float, Field(ge=0.0, le=1.0)]
    authority: Literal["candidate_only"] = "candidate_only"
    execution_authority: Literal[False] = False

    @model_validator(mode="after")
    def _route_is_consistent(self) -> ConversationPreflightProposal:
        if not math.isfinite(self.confidence):
            raise ValueError("conversation preflight confidence MUST be finite")
        return self


class ConversationPreflightModel(Protocol):
    """Propose one compact no-authority conversation route."""

    def preflight(
        self,
        *,
        utterance: str,
        context: tuple[str, ...],
        locale: str,
        direct_response_profile: Mapping[str, Any],
        direct_response_profile_digest: str,
        schema_repair: tuple[dict[str, str], ...],
    ) -> Mapping[str, Any] | ConversationModelResponse | None: ...


class SocialResponseNarratorModel(Protocol):
    """Author one bounded response after social routing is validated."""

    def narrate_social(
        self,
        *,
        utterance: str,
        locale: str,
        social_act: str,
        continued: bool,
        direct_response_profile: Mapping[str, Any],
        direct_response_profile_digest: str,
    ) -> Mapping[str, Any] | ConversationModelResponse | None: ...


@dataclass(frozen=True, slots=True)
class ConversationPreflightBinding:
    """One configured T1 preflight model and its prompt provenance."""

    model: ConversationPreflightModel
    model_config_digest: str
    prompt_digest: str


@dataclass(frozen=True, slots=True)
class SocialResponseNarratorBinding:
    """One separately configured social response model."""

    model: SocialResponseNarratorModel
    model_config_digest: str
    prompt_digest: str


@dataclass(frozen=True, slots=True)
class ConversationPreflightResult:
    """One optional validated preflight proposal and measured observations."""

    proposal: ConversationPreflightProposal | None
    observations: tuple[ConversationModelObservation, ...] = ()
    attempted: bool = False
    failure_kind: Literal["provider_unavailable", "malformed"] | None = None


@dataclass(frozen=True, slots=True)
class SocialResponseNarratorResult:
    """One validated social response or a bounded failure."""

    draft: SemanticDirectResponseDraft | None
    observations: tuple[ConversationModelObservation, ...] = ()
    attempted: bool = False


class ConversationPreflightBoundary:
    """Run one compact T1 attempt and fail open only to full semantic judgment."""

    def __init__(
        self,
        *,
        binding: ConversationPreflightBinding | None,
        narrator: SocialResponseNarratorBinding | None = None,
    ) -> None:
        self._binding = binding
        self._narrator = narrator

    def classify(
        self,
        *,
        utterance: str,
        context: Sequence[str],
        locale: str,
        direct_response_profile: Mapping[str, Any],
    ) -> ConversationPreflightResult:
        """Return a validated candidate or no proposal for full-path continuation."""

        if self._binding is None or not utterance.strip() or len(utterance) > _MAX_UTTERANCE_CHARS:
            return ConversationPreflightResult(proposal=None)
        try:
            bounded_context = _bounded_context(context)
            bounded_profile = _bounded_profile(direct_response_profile)
        except (TypeError, ValueError):
            return ConversationPreflightResult(proposal=None)
        response_locale = "ko" if locale.casefold().startswith("ko") else "en"
        profile_digest = content_digest(bounded_profile)
        observations: list[ConversationModelObservation] = []
        schema_repair: tuple[dict[str, str], ...] = ()
        for attempt in range(_MAX_SCHEMA_ATTEMPTS):
            try:
                response = self._binding.model.preflight(
                    utterance=utterance,
                    context=bounded_context,
                    locale=response_locale,
                    direct_response_profile=bounded_profile,
                    direct_response_profile_digest=profile_digest,
                    schema_repair=schema_repair,
                )
            except Exception as exc:  # noqa: BLE001 - full judgment remains the safe fallback
                _LOGGER.warning(
                    "conversation_preflight_model_failed",
                    extra={"failure_type": type(exc).__name__},
                )
                return ConversationPreflightResult(
                    proposal=None,
                    observations=tuple(observations),
                    attempted=True,
                    failure_kind="provider_unavailable",
                )
            if response is None:
                return ConversationPreflightResult(
                    proposal=None,
                    observations=tuple(observations),
                    attempted=True,
                    failure_kind="provider_unavailable",
                )
            raw: Mapping[str, Any]
            if isinstance(response, ConversationModelResponse):
                raw = response.proposal
                observations.append(response.observation)
            else:
                raw = response
            try:
                proposal = ConversationPreflightProposal.model_validate(raw)
            except (TypeError, ValueError, ValidationError) as exc:
                if attempt + 1 < _MAX_SCHEMA_ATTEMPTS:
                    schema_repair = (_repair_instruction(exc),)
                    continue
                return ConversationPreflightResult(
                    proposal=None,
                    observations=tuple(observations),
                    attempted=True,
                    failure_kind="malformed",
                )
            return ConversationPreflightResult(
                proposal=proposal,
                observations=tuple(observations),
                attempted=True,
            )
        raise RuntimeError("conversation preflight attempt bound is unreachable")

    def narrate_social(
        self,
        *,
        utterance: str,
        locale: str,
        social_act: SocialAct,
        continued: bool,
        direct_response_profile: Mapping[str, Any],
    ) -> SocialResponseNarratorResult:
        """Author one response without exposing operational context or capabilities."""

        if self._narrator is None:
            return SocialResponseNarratorResult(draft=None)
        response_locale = "ko" if locale.casefold().startswith("ko") else "en"
        bounded_profile = _bounded_profile(direct_response_profile)
        profile_digest = content_digest(bounded_profile)
        try:
            response = self._narrator.model.narrate_social(
                utterance=utterance,
                locale=response_locale,
                social_act=social_act.value,
                continued=continued,
                direct_response_profile=bounded_profile,
                direct_response_profile_digest=profile_digest,
            )
        except Exception as exc:  # noqa: BLE001 - terminal hold is the safe fallback
            _LOGGER.warning(
                "social_response_narrator_failed",
                extra={"failure_type": type(exc).__name__},
            )
            return SocialResponseNarratorResult(draft=None, attempted=True)
        if response is None:
            return SocialResponseNarratorResult(draft=None, attempted=True)
        observation: ConversationModelObservation | None = None
        raw: Mapping[str, Any]
        if isinstance(response, ConversationModelResponse):
            raw = response.proposal
            observation = response.observation
        else:
            raw = response
        try:
            draft = SemanticDirectResponseDraft.model_validate(raw)
            if draft.locale != response_locale or draft.profile_digest != profile_digest:
                raise ValueError("social response narrator binding mismatch")
        except (TypeError, ValueError, ValidationError):
            return SocialResponseNarratorResult(
                draft=None,
                observations=(observation,) if observation is not None else (),
                attempted=True,
            )
        return SocialResponseNarratorResult(
            draft=draft,
            observations=(observation,) if observation is not None else (),
            attempted=True,
        )


def _bounded_context(context: Sequence[str]) -> tuple[str, ...]:
    selected: list[str] = []
    total = 0
    for item in tuple(context)[-_MAX_CONTEXT_ITEMS:]:
        if not isinstance(item, str):
            raise TypeError("conversation preflight context MUST contain strings")
        total += len(item)
        if total > _MAX_CONTEXT_CHARS:
            raise ValueError("conversation preflight context exceeds its bound")
        selected.append(item)
    return tuple(selected)


def _bounded_profile(profile: Mapping[str, Any]) -> dict[str, Any]:
    selected = dict(profile)
    if len(canonical_json(selected).encode()) > _MAX_PROFILE_BYTES:
        raise ValueError("conversation preflight profile exceeds its byte bound")
    return selected


def _repair_instruction(exc: TypeError | ValueError | ValidationError) -> dict[str, str]:
    reason = str(exc)
    if "locale" in reason:
        return {"path": "direct_response.locale", "reason": "copy the supplied locale exactly"}
    if "profile digest" in reason:
        return {
            "path": "direct_response.profile_digest",
            "reason": "copy direct_response_profile_digest exactly",
        }
    if "honorific" in reason:
        return {
            "path": "direct_response.answer",
            "reason": "Korean sentences require polite honorific endings",
        }
    if "links or markup" in reason:
        return {
            "path": "direct_response.answer",
            "reason": "return plain text without links or markup",
        }
    return {
        "path": "proposal",
        "reason": "return every conditionally required field with a schema-valid value",
    }


__all__ = [
    "ContextDependency",
    "ConversationPreflightBinding",
    "ConversationPreflightBoundary",
    "ConversationPreflightModel",
    "ConversationPreflightProposal",
    "ConversationPreflightResult",
    "DIRECT_SOCIAL_ACTS",
    "OperationalSignal",
    "SOCIAL_NARRATOR_CAPABILITY_IDS",
    "SocialResponseNarratorBinding",
    "SocialResponseNarratorModel",
    "SocialResponseNarratorResult",
    "SocialAct",
]
