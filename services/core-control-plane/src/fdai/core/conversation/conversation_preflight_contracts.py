"""Contracts and model bindings for conversation preflight routing."""

from __future__ import annotations

import asyncio
import math
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Annotated, Any, Literal, Protocol

from fdai_service_contracts.ontology_query import QueryContract
from fdai_service_contracts.semantic_judgment import (
    SemanticDirectResponseDraft,
    SemanticTarget,
    is_polite_korean_answer,
)
from pydantic import Field, model_validator

from .conversation_preflight_answer_safety import (
    general_answer_contains_link,
    general_answer_contains_operational_claim,
)
from .conversation_preflight_validation import discard_generic_collection_filter_targets
from .model_observation import ConversationModelObservation, ConversationModelResponse

Digest = Annotated[str, Field(pattern=r"^sha256:[a-f0-9]{64}$")]


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


class GeneralKnowledgeSignal(StrEnum):
    """Whether the turn explicitly requests environment-independent knowledge."""

    NONE = "none"
    EXPLICIT = "explicit"


class GeneralKnowledgeDraft(QueryContract):
    """One bounded no-authority answer authored with the routing decision."""

    locale: Literal["en", "ko"]
    answer: Annotated[str, Field(min_length=1, max_length=400)]
    profile_digest: Digest
    execution_authority: Literal[False] = False

    @model_validator(mode="after")
    def _answer_is_usable(self) -> GeneralKnowledgeDraft:
        if self.answer != self.answer.strip():
            raise ValueError("general knowledge answer MUST be trimmed")
        if general_answer_contains_link(self.answer):
            raise ValueError("general knowledge answer MUST NOT contain links")
        if self.locale == "ko" and not is_polite_korean_answer(self.answer):
            raise ValueError("Korean general knowledge answer MUST use polite honorific endings")
        if general_answer_contains_operational_claim(self.answer):
            raise ValueError("general knowledge answer MUST NOT claim operational observation")
        return self


class OperationalPreflightFamily(StrEnum):
    """Small reviewed operational family set that can skip full judgment."""

    NONE = "none"
    INVENTORY_DOCUMENT = "inventory_document"
    RESOURCE_COLLECTION = "resource_collection"
    RESOURCE_CURRENT_STATE = "resource_current_state"
    SUBSCRIPTION_SCOPE_IDENTITY = "subscription_scope_identity"
    SUBSCRIPTION_SERVICE_HEALTH = "subscription_service_health"
    RECENT_RESOURCE_CHANGES = "recent_resource_changes"
    RECENT_RESOURCE_STATE_CHANGES = "recent_resource_state_changes"
    RESOURCE_CONFIGURATION_CHANGES = "resource_configuration_changes"
    GATEWAY_DIAGNOSTIC_EVIDENCE = "gateway_diagnostic_evidence"


class OperationalWindowMode(StrEnum):
    """Typed temporal posture for one reviewed operational preflight family."""

    NONE = "none"
    PAST_HOUR = "past_hour"
    SERVER_RECENT_DEFAULT = "server_recent_default"


class ConversationPreflightProposal(QueryContract):
    """Untrusted compact route proposal without user-facing response prose."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    social_act: SocialAct
    operational_signal: OperationalSignal
    context_dependency: ContextDependency
    knowledge_signal: GeneralKnowledgeSignal = GeneralKnowledgeSignal.NONE
    general_answer: GeneralKnowledgeDraft | None = None
    operational_family: OperationalPreflightFamily = OperationalPreflightFamily.NONE
    operational_window: OperationalWindowMode = OperationalWindowMode.NONE
    operational_targets: Annotated[tuple[SemanticTarget, ...], Field(max_length=4)] = ()
    operational_facets: Annotated[tuple[str, ...], Field(max_length=24)] = ()
    operational_result_limit: Annotated[int, Field(ge=1, le=20)] | None = None
    confidence: Annotated[float, Field(ge=0.0, le=1.0)]
    authority: Literal["candidate_only"] = "candidate_only"
    execution_authority: Literal[False] = False

    @model_validator(mode="before")
    @classmethod
    def _discard_generic_collection_filter_targets(cls, value: object) -> object:
        return discard_generic_collection_filter_targets(value)

    @model_validator(mode="after")
    def _route_is_consistent(self) -> ConversationPreflightProposal:
        if not math.isfinite(self.confidence):
            raise ValueError("conversation preflight confidence MUST be finite")
        known_operational = self.operational_family is not OperationalPreflightFamily.NONE
        if known_operational != bool(self.operational_targets or self.operational_facets):
            raise ValueError("known operational preflight family requires typed details")
        if known_operational and self.operational_signal is not OperationalSignal.EXPLICIT:
            raise ValueError("operational preflight family requires an explicit operational signal")
        if not known_operational and self.operational_window is not OperationalWindowMode.NONE:
            raise ValueError("operational preflight window requires a known operational family")
        if len(self.operational_facets) != len(set(self.operational_facets)):
            raise ValueError("operational preflight facets MUST be unique")
        pure_general = (
            self.social_act is SocialAct.NONE
            and self.knowledge_signal is GeneralKnowledgeSignal.EXPLICIT
            and self.operational_signal is OperationalSignal.NONE
            and self.context_dependency is ContextDependency.NONE
        )
        if pure_general != (self.general_answer is not None):
            raise ValueError("pure general knowledge requires exactly one bounded answer")
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


class CancellableConversationPreflightModel(ConversationPreflightModel, Protocol):
    """Preflight provider that explicitly supports cancellation propagation."""

    def preflight(
        self,
        *,
        utterance: str,
        context: tuple[str, ...],
        locale: str,
        direct_response_profile: Mapping[str, Any],
        direct_response_profile_digest: str,
        schema_repair: tuple[dict[str, str], ...],
        cancelled: asyncio.Event | None = None,
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
    supports_cancellation: bool = False


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
    input_digest: str | None = None
    proposal_digest: str | None = None
    model_config_digest: str | None = None
    prompt_digest: str | None = None
    direct_response_profile_digest: str | None = None


@dataclass(frozen=True, slots=True)
class SocialResponseNarratorResult:
    """One validated social response or a bounded failure."""

    draft: SemanticDirectResponseDraft | None
    observations: tuple[ConversationModelObservation, ...] = ()
    attempted: bool = False
