"""Run bounded model-backed semantic judgment without execution authority."""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from fdai_service_contracts.ontology_query import canonical_json, content_digest
from fdai_service_contracts.semantic_judgment import (
    SemanticJudgmentDisposition,
    SemanticJudgmentProposal,
    SemanticJudgmentReceipt,
    SemanticJudgmentTier,
)
from fdai_service_contracts.semantic_turn import SemanticConversationModelTier
from pydantic import ValidationError

from . import semantic_judgment_capabilities as capability_normalization
from . import semantic_judgment_grounding as grounding
from . import semantic_judgment_review as review_policy
from . import semantic_judgment_schema_repair as schema_repair_policy
from .conversation_preflight import (
    ConversationPreflightBoundary,
    ConversationPreflightResult,
    SocialAct,
    SocialResponseNarratorResult,
)
from .model_observation import ConversationModelObservation, ConversationModelResponse

_MAX_UTTERANCE_CHARS = 32_000
_MAX_CONTEXT_ITEMS = 8
_MAX_CONTEXT_CHARS = 12_000
_MAX_CAPABILITIES = 512
_MAX_CAPABILITY_BYTES = 524_288
_MAX_SCHEMA_ATTEMPTS_PER_BINDING = 3
_MACHINE_TOKEN_SEPARATOR = re.compile(r"[^a-z0-9_.-]+")
_LOGGER = logging.getLogger(__name__)


class SemanticJudgmentModel(Protocol):
    """Propose candidate-only structured meaning without authority."""

    def judge(
        self,
        *,
        utterance: str,
        context: tuple[str, ...],
        capabilities: tuple[dict[str, Any], ...],
        locale: str,
        direct_response_profile: Mapping[str, Any],
        direct_response_profile_digest: str,
        profile_id: str,
        profile_version: str,
        schema_repair: tuple[dict[str, str], ...],
    ) -> Mapping[str, Any] | SemanticJudgmentModelResponse | None: ...


SemanticJudgmentObservation = ConversationModelObservation
SemanticJudgmentModelResponse = ConversationModelResponse


@dataclass(frozen=True, slots=True)
class SemanticJudgmentBinding:
    """One configured model tier and its content-free provenance."""

    tier: SemanticJudgmentTier
    model: SemanticJudgmentModel
    model_config_digest: str
    prompt_digest: str


@dataclass(frozen=True, slots=True)
class SemanticJudgmentResult:
    """One terminal semantic outcome with no execution authority."""

    proposal: SemanticJudgmentProposal | None
    receipt: SemanticJudgmentReceipt
    observations: tuple[SemanticJudgmentObservation, ...] = ()

    @property
    def accepted(self) -> bool:
        """Admit accepted meaning or a low-confidence candidate that can only become a draft."""

        return self.receipt.disposition is SemanticJudgmentDisposition.ACCEPTED or (
            self.receipt.disposition is SemanticJudgmentDisposition.LOW_CONFIDENCE
            and self.proposal is not None
            and self.proposal.action_posture == "draft_only"
        )


class SemanticJudgmentBoundary:
    """Run bounded T1/T2 semantic judgment and validate every proposal."""

    def __init__(
        self,
        *,
        profile_id: str,
        profile_version: str,
        primary: SemanticJudgmentBinding | None,
        schema_repair: SemanticJudgmentBinding | None = None,
        escalation: SemanticJudgmentBinding | None = None,
        preflight: ConversationPreflightBoundary | None = None,
        confidence_threshold: float = 0.75,
        strict_intent_grounding: bool = False,
    ) -> None:
        if primary is not None and primary.tier is not SemanticJudgmentTier.T1:
            raise ValueError("primary semantic judgment binding MUST use T1")
        if schema_repair is not None and schema_repair.tier is not SemanticJudgmentTier.T1:
            raise ValueError("schema-repair semantic judgment binding MUST use T1")
        if escalation is not None and escalation.tier is not SemanticJudgmentTier.T2:
            raise ValueError("escalation semantic judgment binding MUST use T2")
        review_policy.validate_independent_bindings(primary, escalation)
        if not 0.0 < confidence_threshold <= 1.0:
            raise ValueError("semantic judgment confidence threshold MUST be in (0, 1]")
        self.profile_id = profile_id
        self.profile_version = profile_version
        self._primary = primary
        self._schema_repair = schema_repair
        self._escalation = escalation
        self._bindings = tuple(
            item for item in (primary, schema_repair, escalation) if item is not None
        )
        self._preflight = preflight
        self._confidence_threshold = confidence_threshold
        self._strict_intent_grounding = strict_intent_grounding

    def preflight(
        self,
        *,
        utterance: str,
        context: Sequence[str],
        locale: str,
        direct_response_profile: Mapping[str, Any],
        cancelled: asyncio.Event | None = None,
        conversation_model_tier: SemanticConversationModelTier | None = None,
    ) -> ConversationPreflightResult:
        """Run the compact social/operational preflight when it is configured."""

        if self._preflight is None:
            return ConversationPreflightResult(proposal=None)
        return self._preflight.classify(
            utterance=utterance,
            context=context,
            locale=locale,
            direct_response_profile=direct_response_profile,
            cancelled=cancelled,
            conversation_model_tier=conversation_model_tier,
        )

    def narrate_social(
        self,
        *,
        utterance: str,
        locale: str,
        social_act: SocialAct,
        continued: bool,
        direct_response_profile: Mapping[str, Any],
    ) -> SocialResponseNarratorResult:
        """Use the separately bound social narrator after routing is validated."""

        if self._preflight is None:
            return SocialResponseNarratorResult(draft=None)
        return self._preflight.narrate_social(
            utterance=utterance,
            locale=locale,
            social_act=social_act,
            continued=continued,
            direct_response_profile=direct_response_profile,
        )

    def judge(
        self,
        *,
        utterance: str,
        context: Sequence[str],
        capabilities: Sequence[Mapping[str, Any]],
        allow_escalation: bool = True,
        bound_subject_types: Sequence[str] = (),
        locale: str = "en",
        direct_response_profile: Mapping[str, Any] | None = None,
    ) -> SemanticJudgmentResult:
        """Return one bounded judgment, optionally restricting evaluation to T1."""

        started = time.monotonic()
        bounded_context = _bounded_context(context)
        bounded_capabilities = _bounded_capabilities(capabilities)
        response_locale = "ko" if locale.casefold().startswith("ko") else "en"
        bounded_response_profile = _bounded_direct_response_profile(direct_response_profile)
        response_profile_digest = content_digest(bounded_response_profile)
        bounded_subject_types = _bounded_subject_types(
            bound_subject_types,
            capabilities=bounded_capabilities,
        )
        input_digest = content_digest({"utterance": utterance})
        context_digest = content_digest(
            {
                "context": list(bounded_context),
                "direct_response_profile": bounded_response_profile,
                "locale": response_locale,
            }
        )
        capability_digest = content_digest({"capabilities": list(bounded_capabilities)})
        if not utterance.strip() or len(utterance) > _MAX_UTTERANCE_CHARS:
            return self._result(
                started=started,
                input_digest=input_digest,
                context_digest=context_digest,
                capability_digest=capability_digest,
                disposition=SemanticJudgmentDisposition.MALFORMED,
                reason_code="utterance_out_of_bounds",
            )
        if not self._bindings:
            return self._result(
                started=started,
                input_digest=input_digest,
                context_digest=context_digest,
                capability_digest=capability_digest,
                disposition=SemanticJudgmentDisposition.UNAVAILABLE,
                reason_code="model_unbound",
            )

        final_disposition = SemanticJudgmentDisposition.UNAVAILABLE
        final_reason = "model_attempts_unavailable"
        final_binding: SemanticJudgmentBinding | None = None
        final_proposal: SemanticJudgmentProposal | None = None
        schema_fallback_binding: SemanticJudgmentBinding | None = None
        schema_fallback_proposal: SemanticJudgmentProposal | None = None
        review_primary_binding: SemanticJudgmentBinding | None = None
        review_primary_proposal: SemanticJudgmentProposal | None = None
        observations: list[SemanticJudgmentObservation] = []
        bindings = tuple(
            item
            for item in (self._primary, self._schema_repair, self._escalation)
            if item is not None
        )
        for binding in bindings:
            if (
                binding is self._escalation
                and not allow_escalation
                and review_primary_proposal is None
            ):
                continue
            if review_primary_proposal is not None and binding is self._schema_repair:
                continue
            strict_grounding = self._strict_intent_grounding or binding is self._schema_repair
            schema_repair: tuple[dict[str, str], ...] = ()
            for attempt in range(_MAX_SCHEMA_ATTEMPTS_PER_BINDING):
                try:
                    model_response = binding.model.judge(
                        utterance=utterance,
                        context=bounded_context,
                        capabilities=bounded_capabilities,
                        locale=response_locale,
                        direct_response_profile=bounded_response_profile,
                        direct_response_profile_digest=response_profile_digest,
                        profile_id=self.profile_id,
                        profile_version=self.profile_version,
                        schema_repair=schema_repair,
                    )
                except Exception as exc:  # noqa: BLE001 - provider detail stays content-free
                    _LOGGER.warning(
                        "semantic_judgment_model_failed",
                        extra={"tier": binding.tier.value, "failure_type": type(exc).__name__},
                    )
                    final_disposition = SemanticJudgmentDisposition.UNAVAILABLE
                    final_reason = "model_provider_error"
                    break
                if model_response is None:
                    break
                if isinstance(model_response, SemanticJudgmentModelResponse):
                    raw = model_response.proposal
                    observations.append(model_response.observation)
                else:
                    raw = model_response
                try:
                    proposal = SemanticJudgmentProposal.model_validate(
                        _canonicalize_machine_tokens(raw)
                    )
                    proposal = grounding.ground_unique_source_spans(
                        proposal,
                        utterance=utterance,
                        capabilities=bounded_capabilities,
                        allow_context_target_drop=not strict_grounding,
                    )
                    proposal = grounding.normalize_schema_object_type_suffix(proposal)
                    proposal = grounding.recover_unique_schema_subject(
                        proposal,
                        utterance=utterance,
                        capabilities=bounded_capabilities,
                    )
                    grounding.validate_forbidden_action_canonical_values(
                        proposal,
                        capabilities=bounded_capabilities,
                    )
                    proposal = capability_normalization.normalize_primary_intent(
                        proposal,
                        capabilities=bounded_capabilities,
                    )
                    proposal = grounding.normalize_incident_mitigation_identity_clarification(
                        proposal,
                        bound_incident="Incident" in bounded_subject_types,
                        locale=response_locale,
                    )
                    if strict_grounding:
                        proposal = grounding.normalize_intents_from_typed_facets(
                            proposal,
                            capabilities=bounded_capabilities,
                        )
                        proposal = grounding.normalize_overlapping_target_fragments(proposal)
                        proposal = grounding.normalize_target_shape(proposal)
                        proposal = grounding.normalize_required_identity_clarification(
                            proposal,
                            locale=response_locale,
                        )
                        proposal = grounding.normalize_complete_target_ambiguity(proposal)
                        proposal = grounding.normalize_action_advice_identity_ambiguity(proposal)
                        proposal = grounding.normalize_unsupplied_time_canonical_values(
                            proposal,
                            capabilities=bounded_capabilities,
                        )
                        grounding.validate_capability_grounding(
                            proposal,
                            capabilities=bounded_capabilities,
                        )
                    proposal = capability_normalization.normalize_collection_identity_ambiguity(
                        proposal,
                        capabilities=bounded_capabilities,
                    )
                    proposal = schema_repair_policy.normalize_identity_ambiguity(
                        proposal,
                        capabilities=bounded_capabilities,
                    )
                    if strict_grounding:
                        proposal = grounding.normalize_exact_resource_identity_ambiguity(proposal)
                    _validate_intent_target_compatibility(proposal)
                    if strict_grounding:
                        grounding.validate_action_target_ambiguity(proposal)
                        grounding.validate_required_target_shape(proposal)
                    _validate_direct_response(
                        proposal,
                        locale=response_locale,
                        profile_digest=response_profile_digest,
                    )
                    grounding.validate_source_spans(proposal, utterance=utterance)
                except (TypeError, ValueError, ValidationError) as exc:
                    recovered_trace = (
                        None
                        if strict_grounding
                        else _recover_safe_ontology_trace_proposal(
                            raw,
                            utterance=utterance,
                            capabilities=bounded_capabilities,
                        )
                    )
                    if recovered_trace is not None:
                        return self._result(
                            started=started,
                            input_digest=input_digest,
                            context_digest=context_digest,
                            capability_digest=capability_digest,
                            disposition=SemanticJudgmentDisposition.ACCEPTED,
                            reason_code="accepted_safe_trace_hold",
                            binding=binding,
                            proposal=recovered_trace,
                            observations=tuple(observations),
                        )
                    recovered_proposal = (
                        None
                        if strict_grounding
                        else _recover_bound_subject_proposal(
                            raw,
                            utterance=utterance,
                            capabilities=bounded_capabilities,
                            bound_subject_types=bounded_subject_types,
                        )
                    )
                    if recovered_proposal is not None:
                        return self._result(
                            started=started,
                            input_digest=input_digest,
                            context_digest=context_digest,
                            capability_digest=capability_digest,
                            disposition=SemanticJudgmentDisposition.ACCEPTED,
                            reason_code="accepted",
                            binding=binding,
                            proposal=recovered_proposal,
                            observations=tuple(observations),
                        )
                    latest_repair = schema_repair_policy.repair_feedback(exc)
                    schema_repair = schema_repair_policy.merge_feedback(
                        schema_repair, latest_repair
                    )
                    schema_repair_policy.log_rejection(
                        exc,
                        validation_reason=schema_repair,
                        logger=_LOGGER,
                    )
                    final_disposition = SemanticJudgmentDisposition.MALFORMED
                    final_reason = "proposal_invalid"
                    if attempt + 1 < _MAX_SCHEMA_ATTEMPTS_PER_BINDING:
                        _LOGGER.info(
                            "semantic_judgment_proposal_retry",
                            extra={"tier": binding.tier.value, "attempt": attempt + 1},
                        )
                        continue
                    break
                if review_primary_proposal is not None and binding is self._escalation:
                    if not review_policy.proposals_match(
                        review_primary_proposal,
                        proposal,
                        confidence_threshold=self._confidence_threshold,
                    ):
                        return self._result(
                            started=started,
                            input_digest=input_digest,
                            context_digest=context_digest,
                            capability_digest=capability_digest,
                            disposition=SemanticJudgmentDisposition.UNAVAILABLE,
                            reason_code="semantic_judgment_review_conflict",
                            observations=tuple(observations),
                        )
                    return self._result(
                        started=started,
                        input_digest=input_digest,
                        context_digest=context_digest,
                        capability_digest=capability_digest,
                        disposition=SemanticJudgmentDisposition.ACCEPTED,
                        reason_code="accepted_independent_review",
                        binding=review_primary_binding,
                        proposal=review_primary_proposal,
                        observations=tuple(observations),
                    )
                if (
                    binding is self._primary
                    and self._schema_repair is not None
                    and schema_repair_policy.repair_required(proposal)
                ):
                    schema_fallback_binding = binding
                    schema_fallback_proposal = proposal
                    break
                if (
                    binding is self._schema_repair
                    and schema_fallback_proposal is not None
                    and not schema_repair_policy.repair_preserves_family(
                        schema_fallback_proposal,
                        proposal,
                    )
                ):
                    final_disposition = SemanticJudgmentDisposition.MALFORMED
                    final_reason = "schema_repair_family_mismatch"
                    break
                if proposal.ambiguous:
                    final_disposition = SemanticJudgmentDisposition.CLARIFICATION
                    final_reason = "clarification_required"
                    if binding is not bindings[-1]:
                        break
                    if schema_fallback_binding is not None and schema_fallback_proposal is not None:
                        return self._result(
                            started=started,
                            input_digest=input_digest,
                            context_digest=context_digest,
                            capability_digest=capability_digest,
                            disposition=SemanticJudgmentDisposition.ACCEPTED,
                            reason_code="accepted_schema_repair_fallback",
                            binding=schema_fallback_binding,
                            proposal=schema_fallback_proposal,
                            observations=tuple(observations),
                        )
                    return self._result(
                        started=started,
                        input_digest=input_digest,
                        context_digest=context_digest,
                        capability_digest=capability_digest,
                        disposition=final_disposition,
                        reason_code=final_reason,
                        binding=binding,
                        proposal=proposal,
                        observations=tuple(observations),
                    )
                if proposal.confidence < self._confidence_threshold:
                    final_disposition = SemanticJudgmentDisposition.LOW_CONFIDENCE
                    final_reason = "confidence_below_threshold"
                    final_binding = binding
                    final_proposal = proposal
                    break
                if binding is self._primary and review_policy.requires_independent_review(proposal):
                    if self._escalation is None:
                        return self._result(
                            started=started,
                            input_digest=input_digest,
                            context_digest=context_digest,
                            capability_digest=capability_digest,
                            disposition=SemanticJudgmentDisposition.UNAVAILABLE,
                            reason_code="semantic_judgment_review_unavailable",
                            observations=tuple(observations),
                        )
                    review_primary_binding = binding
                    review_primary_proposal = proposal
                    break
                return self._result(
                    started=started,
                    input_digest=input_digest,
                    context_digest=context_digest,
                    capability_digest=capability_digest,
                    disposition=SemanticJudgmentDisposition.ACCEPTED,
                    reason_code="accepted",
                    binding=binding,
                    proposal=proposal,
                    observations=tuple(observations),
                )
        if review_primary_proposal is not None:
            return self._result(
                started=started,
                input_digest=input_digest,
                context_digest=context_digest,
                capability_digest=capability_digest,
                disposition=SemanticJudgmentDisposition.UNAVAILABLE,
                reason_code="semantic_judgment_review_unavailable",
                observations=tuple(observations),
            )
        if schema_fallback_binding is not None and schema_fallback_proposal is not None:
            return self._result(
                started=started,
                input_digest=input_digest,
                context_digest=context_digest,
                capability_digest=capability_digest,
                disposition=SemanticJudgmentDisposition.ACCEPTED,
                reason_code="accepted_schema_repair_fallback",
                binding=schema_fallback_binding,
                proposal=schema_fallback_proposal,
                observations=tuple(observations),
            )
        return self._result(
            started=started,
            input_digest=input_digest,
            context_digest=context_digest,
            capability_digest=capability_digest,
            disposition=final_disposition,
            reason_code=final_reason,
            binding=(
                final_binding
                if final_disposition is SemanticJudgmentDisposition.LOW_CONFIDENCE
                else None
            ),
            proposal=(
                final_proposal
                if final_disposition is SemanticJudgmentDisposition.LOW_CONFIDENCE
                else None
            ),
            observations=tuple(observations),
        )

    def _result(
        self,
        *,
        started: float,
        input_digest: str,
        context_digest: str,
        capability_digest: str,
        disposition: SemanticJudgmentDisposition,
        reason_code: str,
        binding: SemanticJudgmentBinding | None = None,
        proposal: SemanticJudgmentProposal | None = None,
        observations: tuple[SemanticJudgmentObservation, ...] = (),
    ) -> SemanticJudgmentResult:
        body = {
            "schema_version": "1.0.0",
            "input_digest": input_digest,
            "context_digest": context_digest,
            "capability_digest": capability_digest,
            "proposal_digest": proposal.proposal_digest if proposal is not None else None,
            "profile_id": self.profile_id,
            "profile_version": self.profile_version,
            "tier": binding.tier.value if binding is not None else None,
            "model_config_digest": (
                binding.model_config_digest
                if proposal is not None and binding is not None
                else None
            ),
            "prompt_digest": (
                binding.prompt_digest if proposal is not None and binding is not None else None
            ),
            "disposition": disposition.value,
            "confidence": proposal.confidence if proposal is not None else None,
            "ambiguous": proposal.ambiguous if proposal is not None else False,
            "latency_ms": min(120_000, max(0, int((time.monotonic() - started) * 1_000))),
            "reason_code": reason_code,
            "execution_authority": False,
        }
        receipt = SemanticJudgmentReceipt.model_validate(
            {**body, "receipt_digest": content_digest(body)}
        )
        return SemanticJudgmentResult(proposal, receipt, observations)


def _bounded_context(context: Sequence[str]) -> tuple[str, ...]:
    selected: list[str] = []
    total = 0
    for item in tuple(context)[-_MAX_CONTEXT_ITEMS:]:
        if not isinstance(item, str):
            raise TypeError("semantic judgment context MUST contain strings")
        total += len(item)
        if total > _MAX_CONTEXT_CHARS:
            raise ValueError("semantic judgment context exceeds its bound")
        selected.append(item)
    return tuple(selected)


def _bounded_capabilities(
    capabilities: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, Any], ...]:
    if len(capabilities) > _MAX_CAPABILITIES:
        raise ValueError("semantic judgment capabilities exceed their count bound")
    selected = tuple(dict(item) for item in capabilities)
    if len(canonical_json(list(selected)).encode()) > _MAX_CAPABILITY_BYTES:
        raise ValueError("semantic judgment capabilities exceed their byte bound")
    return selected


def _bounded_direct_response_profile(
    profile: Mapping[str, Any] | None,
) -> dict[str, Any]:
    selected = dict(profile or {})
    encoded = canonical_json(selected).encode()
    if len(encoded) > 16_384:
        raise ValueError("semantic direct response profile exceeds its byte bound")
    return selected


def _validate_direct_response(
    proposal: SemanticJudgmentProposal,
    *,
    locale: str,
    profile_digest: str,
) -> None:
    draft = proposal.direct_response
    if draft is None:
        return
    if draft.locale != locale:
        raise ValueError("semantic direct response locale does not match the request")
    if draft.profile_digest != profile_digest:
        raise ValueError("semantic direct response profile digest does not match")


def _bounded_subject_types(
    subjects: Sequence[str],
    *,
    capabilities: tuple[dict[str, Any], ...],
) -> tuple[str, ...]:
    selected = tuple(subjects)
    if len(selected) != len(set(selected)) or len(selected) > 4:
        raise ValueError("semantic bound subject types are invalid")
    object_types = {
        name
        for capability in capabilities
        if capability.get("kind") == "object_type"
        if isinstance((name := capability.get("name")), str)
    }
    if any(subject not in object_types for subject in selected):
        raise ValueError("semantic bound subject type is absent from the manifest")
    return selected


def _recover_bound_subject_proposal(
    raw: Mapping[str, Any],
    *,
    utterance: str,
    capabilities: tuple[dict[str, Any], ...],
    bound_subject_types: tuple[str, ...],
) -> SemanticJudgmentProposal | None:
    if (
        not bound_subject_types
        or not raw.get("targets")
        or raw.get("action_posture", "advise_only") != "advise_only"
    ):
        return None
    candidate = _canonicalize_machine_tokens({**raw, "targets": []})
    try:
        proposal = SemanticJudgmentProposal.model_validate(candidate)
        proposal = capability_normalization.normalize_primary_intent(
            proposal,
            capabilities=capabilities,
        )
        grounding.validate_source_spans(proposal, utterance=utterance)
    except (TypeError, ValueError, ValidationError):
        return None
    return proposal


def _recover_safe_ontology_trace_proposal(
    raw: Mapping[str, Any],
    *,
    utterance: str,
    capabilities: tuple[dict[str, Any], ...],
) -> SemanticJudgmentProposal | None:
    candidate = _canonicalize_machine_tokens(raw)
    facets = set(candidate.get("requested_facets", ()))
    required_facets = {"resource_type", "signal_type"}
    action_type = any("action_type" in facet for facet in facets)
    relationship = (
        bool({"explore", "relationships", "trace", "trace_relationships"}.intersection(facets))
        or "controlled_action_type" in facets
    )
    if (
        candidate.get("primary_intent") != "query.ontology_relationships"
        or candidate.get("action_posture", "advise_only") != "advise_only"
        or candidate.get("execution_authority") is not False
        or not required_facets <= facets
        or not action_type
        or not relationship
    ):
        return None
    candidate.update(
        {
            "ambiguous": False,
            "alternatives": [],
            "unresolved_terms": [],
            "clarification": None,
        }
    )
    try:
        proposal = SemanticJudgmentProposal.model_validate(candidate)
        proposal = grounding.ground_unique_source_spans(
            proposal,
            utterance=utterance,
            capabilities=capabilities,
        )
        proposal = capability_normalization.normalize_primary_intent(
            proposal,
            capabilities=capabilities,
        )
        grounding.validate_source_spans(proposal, utterance=utterance)
    except (TypeError, ValueError, ValidationError):
        return None
    expected_targets = {"ActionType", "ResourceType", "Rule", "SignalType"}
    observed_targets = {target.canonical_value for target in proposal.targets}
    allowed_targets: tuple[set[str], ...] = (
        set(),
        expected_targets,
        expected_targets | {"Resource", "Signal"},
    )
    return proposal if observed_targets in allowed_targets else None


def _canonicalize_machine_tokens(raw: Mapping[str, Any]) -> dict[str, Any]:
    normalized = dict(raw)

    def canonicalize(value: object) -> object:
        if not isinstance(value, str):
            return value
        return _MACHINE_TOKEN_SEPARATOR.sub("_", value.strip().lower()).strip("_")

    normalized["primary_intent"] = canonicalize(normalized.get("primary_intent"))
    if normalized.get("discourse_mode") in {"hypothetical", "quoted"}:
        normalized["forbidden_actions"] = []
    if normalized.get("action_posture") == "advise_only":
        normalized["action_subject"] = "none"
    for field in ("secondary_intents", "requested_facets", "alternatives"):
        values = normalized.get(field)
        if isinstance(values, (list, tuple)):
            normalized[field] = [canonicalize(value) for value in values]
    alternatives = normalized.get("alternatives")
    unresolved_terms = normalized.get("unresolved_terms")
    if isinstance(alternatives, (list, tuple)) and isinstance(unresolved_terms, (list, tuple)):
        normalized["ambiguous"] = bool(alternatives or unresolved_terms)
    for field in ("targets", "forbidden_actions"):
        targets = normalized.get(field)
        if isinstance(targets, (list, tuple)):
            normalized[field] = [
                {**target, "kind": canonicalize(target.get("kind"))}
                if isinstance(target, Mapping)
                else target
                for target in targets
            ]
    return normalized


def _validate_intent_target_compatibility(proposal: SemanticJudgmentProposal) -> None:
    """Reject typed intent and target-kind combinations that cannot share one query contract."""

    if proposal.primary_intent == "query.resource_current_state" and any(
        target.kind == "resource_group" for target in proposal.targets
    ):
        raise ValueError("semantic current-state intent requires a Resource target")


__all__ = [
    "SemanticJudgmentBinding",
    "SemanticJudgmentBoundary",
    "SemanticJudgmentModel",
    "SemanticJudgmentResult",
]
