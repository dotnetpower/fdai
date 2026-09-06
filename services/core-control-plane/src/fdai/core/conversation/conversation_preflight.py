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
from fdai_service_contracts.semantic_judgment import (
    SemanticDirectResponseDraft,
    SemanticJudgmentProposal,
    SemanticTarget,
)
from pydantic import Field, ValidationError, model_validator

from .model_observation import ConversationModelObservation, ConversationModelResponse

_MAX_UTTERANCE_CHARS = 32_000
_MAX_CONTEXT_ITEMS = 4
_MAX_CONTEXT_CHARS = 4_000
_MAX_PROFILE_BYTES = 16_384
_MAX_SCHEMA_ATTEMPTS = 2
_OPERATIONAL_PROMOTION_CONFIDENCE = 0.9
_INVENTORY_FACETS = frozenset(
    {"resource_inventory", "subscription", "complete_content", "download"}
)
_CONFIGURATION_FACETS = frozenset(
    {
        "before_after",
        "capacity_units",
        "configuration_changes",
        "historical_coverage",
        "last_hour",
        "tpm",
    }
)
_GATEWAY_FACETS = frozenset(
    {
        "apim",
        "application_gateway",
        "backend",
        "backend_connect_time",
        "backend_response_code",
        "before_after",
        "configuration_changes",
        "first_byte_time",
        "gateway_response_code",
        "gpt",
        "http_status",
        "last_byte_time",
        "last_hour",
        "latency",
        "status_429",
        "status_500",
        "status_503",
        "topology",
        "total_time",
    }
)
_ONE_HOUR_EXPRESSIONS = frozenset(
    {
        "last hour",
        "past hour",
        "previous hour",
        "the last hour",
        "the past hour",
        "the previous hour",
        "지난 1시간",
        "지난 한 시간",
        "최근 1시간",
        "최근 한 시간",
    }
)
_GENERIC_OPERATIONAL_TARGETS = frozenset(
    {
        "api management",
        "api management service",
        "apim",
        "apim gateway",
        "apim service",
        "application gateway",
        "appgw",
        "azure api management",
        "azure api management gateway",
        "azure api management service",
        "azure application gateway",
        "backend",
        "backend service",
        "deployment",
        "gateway",
        "gpt",
        "gpt deployment",
        "gpt model",
        "model",
        "selected deployment",
        "selected gateway",
        "this deployment",
        "this gateway",
        "게이트웨이",
        "모델",
        "배포",
        "백엔드",
        "애플리케이션 게이트웨이",
    }
)
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


class OperationalPreflightFamily(StrEnum):
    """Small reviewed operational family set that can skip full judgment."""

    NONE = "none"
    INVENTORY_DOCUMENT = "inventory_document"
    RESOURCE_CONFIGURATION_CHANGES = "resource_configuration_changes"
    GATEWAY_DIAGNOSTIC_EVIDENCE = "gateway_diagnostic_evidence"


class ConversationPreflightProposal(QueryContract):
    """Untrusted compact route proposal without user-facing response prose."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    social_act: SocialAct
    operational_signal: OperationalSignal
    context_dependency: ContextDependency
    operational_family: OperationalPreflightFamily = OperationalPreflightFamily.NONE
    operational_targets: Annotated[tuple[SemanticTarget, ...], Field(max_length=4)] = ()
    operational_facets: Annotated[tuple[str, ...], Field(max_length=24)] = ()
    confidence: Annotated[float, Field(ge=0.0, le=1.0)]
    authority: Literal["candidate_only"] = "candidate_only"
    execution_authority: Literal[False] = False

    @model_validator(mode="after")
    def _route_is_consistent(self) -> ConversationPreflightProposal:
        if not math.isfinite(self.confidence):
            raise ValueError("conversation preflight confidence MUST be finite")
        known_operational = self.operational_family is not OperationalPreflightFamily.NONE
        if known_operational != bool(self.operational_targets or self.operational_facets):
            raise ValueError("known operational preflight family requires typed details")
        if known_operational and self.operational_signal is not OperationalSignal.EXPLICIT:
            raise ValueError("operational preflight family requires an explicit operational signal")
        if len(self.operational_facets) != len(set(self.operational_facets)):
            raise ValueError("operational preflight facets MUST be unique")
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
    input_digest: str | None = None
    proposal_digest: str | None = None
    model_config_digest: str | None = None
    prompt_digest: str | None = None


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
                input_digest=_preflight_input_digest(utterance),
                proposal_digest=content_digest(proposal.model_dump(mode="json")),
                model_config_digest=self._binding.model_config_digest,
                prompt_digest=self._binding.prompt_digest,
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
        try:
            bounded_profile = _bounded_profile(direct_response_profile)
        except (TypeError, ValueError):
            return SocialResponseNarratorResult(draft=None)
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


def preflight_operational_judgment(
    result: ConversationPreflightResult,
    *,
    utterance: str,
) -> SemanticJudgmentProposal | None:
    """Promote a bounded preflight family to candidate judgment after source checks."""
    proposal = result.proposal
    if proposal is None:
        return _reject_operational_promotion("proposal_absent")
    checks = (
        (result.attempted, "preflight_not_attempted"),
        (result.failure_kind is None, "preflight_failed"),
        (
            proposal.operational_family is not OperationalPreflightFamily.NONE,
            "family_absent",
        ),
        (
            proposal.operational_signal is OperationalSignal.EXPLICIT,
            "signal_not_explicit",
        ),
        (
            proposal.context_dependency is ContextDependency.NONE,
            "context_dependent",
        ),
        (
            proposal.confidence >= _OPERATIONAL_PROMOTION_CONFIDENCE,
            "confidence_below_threshold",
        ),
        (
            result.input_digest == _preflight_input_digest(utterance),
            "input_digest_mismatch",
        ),
        (
            result.proposal_digest == content_digest(proposal.model_dump(mode="json")),
            "proposal_digest_mismatch",
        ),
        (result.model_config_digest is not None, "model_provenance_absent"),
        (result.prompt_digest is not None, "prompt_provenance_absent"),
    )
    for passed, reason in checks:
        if not passed:
            return _reject_operational_promotion(reason)
    normalized_targets: list[SemanticTarget] = []
    for target in proposal.operational_targets:
        if utterance[target.source_start : target.source_end] != target.value:
            source_start = utterance.find(target.value)
            if source_start < 0 or utterance.find(target.value, source_start + 1) >= 0:
                return _reject_operational_promotion("target_not_unique_in_source")
            target = target.model_copy(
                update={
                    "source_start": source_start,
                    "source_end": source_start + len(target.value),
                }
            )
        if target.kind == "time_range":
            if (
                target.canonical_value != "duration.PT1H"
                or " ".join(target.value.casefold().split()) not in _ONE_HOUR_EXPRESSIONS
            ):
                return _reject_operational_promotion("unsupported_time_canonicalization")
        if target.kind not in {"resource", "time_range", "backend", "model"}:
            return _reject_operational_promotion("unsupported_target_kind")
        if target.kind != "time_range" and operational_target_is_generic(target.value):
            return _reject_operational_promotion("generic_target_identity")
        normalized_targets.append(target)
    primary_intent = {
        OperationalPreflightFamily.INVENTORY_DOCUMENT: "create.document",
        OperationalPreflightFamily.RESOURCE_CONFIGURATION_CHANGES: (
            "query.resource_configuration_changes"
        ),
        OperationalPreflightFamily.GATEWAY_DIAGNOSTIC_EVIDENCE: (
            "query.gateway_diagnostic_evidence"
        ),
    }.get(proposal.operational_family)
    target_kinds = tuple(target.kind for target in normalized_targets)
    facets = frozenset(proposal.operational_facets)
    if proposal.operational_family is OperationalPreflightFamily.INVENTORY_DOCUMENT:
        family_valid = not target_kinds and facets == _INVENTORY_FACETS
    elif proposal.operational_family is OperationalPreflightFamily.RESOURCE_CONFIGURATION_CHANGES:
        family_valid = (
            target_kinds.count("resource") == 1
            and target_kinds.count("time_range") == 1
            and len(target_kinds) == 2
            and not next(
                target.value.casefold().startswith("/subscriptions/")
                for target in normalized_targets
                if target.kind == "resource"
            )
            and bool(facets)
            and facets <= _CONFIGURATION_FACETS
        )
    else:
        family_valid = (
            target_kinds.count("resource") == 1
            and target_kinds.count("time_range") == 1
            and target_kinds.count("backend") <= 1
            and target_kinds.count("model") <= 1
            and len(target_kinds) == len(set(target_kinds))
            and bool(facets)
            and facets <= _GATEWAY_FACETS
        )
    if primary_intent is None or not family_valid:
        _LOGGER.info(
            "conversation_preflight_operational_shape_rejected",
            extra={
                "family": proposal.operational_family.value,
                "target_kinds": ",".join(target_kinds),
                "facets": ",".join(sorted(facets)),
            },
        )
        return _reject_operational_promotion("invalid_family_shape")
    return SemanticJudgmentProposal(
        primary_intent=primary_intent,
        targets=tuple(normalized_targets),
        requested_facets=proposal.operational_facets,
        confidence=proposal.confidence,
        ambiguous=False,
        action_posture="advise_only",
        action_subject="none",
        authority="candidate_only",
        execution_authority=False,
    )


def _preflight_input_digest(utterance: str) -> str:
    return content_digest({"utterance": utterance})


def operational_target_is_generic(value: str) -> bool:
    """Return whether source text names only a generic operational category."""
    normalized = " ".join(value.casefold().split()).strip(".,:;!?()[]{}")
    prefixes = (
        "the ",
        "this ",
        "selected ",
        "current ",
        "our ",
        "my ",
        "your ",
        "their ",
        "its ",
        "해당 ",
        "선택한 ",
        "현재 ",
        "우리 ",
        "내 ",
    )
    while normalized.startswith(prefixes):
        normalized = normalized.removeprefix(
            next(prefix for prefix in prefixes if normalized.startswith(prefix))
        )
    return normalized in _GENERIC_OPERATIONAL_TARGETS


def _reject_operational_promotion(reason: str) -> SemanticJudgmentProposal | None:
    _LOGGER.info(
        "conversation_preflight_operational_promotion_rejected",
        extra={"reason": reason},
    )
    return None


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
    "OperationalPreflightFamily",
    "OperationalSignal",
    "SOCIAL_NARRATOR_CAPABILITY_IDS",
    "SocialResponseNarratorBinding",
    "SocialResponseNarratorModel",
    "SocialResponseNarratorResult",
    "SocialAct",
    "operational_target_is_generic",
    "preflight_operational_judgment",
]
