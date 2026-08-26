"""Shared model-backed boundary for natural-language semantic judgment.

The boundary validates one T1 proposal, retries a configured T2 binding after
unavailable, malformed, ambiguous, or low-confidence output, and returns one
content-free terminal receipt. It never grants execution authority.
"""

from __future__ import annotations

import json
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
from pydantic import ValidationError

_MAX_UTTERANCE_CHARS = 32_000
_MAX_CONTEXT_ITEMS = 8
_MAX_CONTEXT_CHARS = 12_000
_MAX_CAPABILITIES = 512
_MAX_CAPABILITY_BYTES = 524_288
_MAX_SCHEMA_ATTEMPTS_PER_BINDING = 3
_MAX_SCHEMA_ERRORS = 16
_MACHINE_TOKEN_SEPARATOR = re.compile(r"[^a-z0-9_.-]+")
_LOGGER = logging.getLogger(__name__)
_SAFE_REJECTION_REASONS = frozenset(
    {
        "ambiguous semantic judgment MUST carry one clarification",
        "primary semantic intent MUST NOT be duplicated",
        "semantic link intent MUST use query namespace",
        "semantic judgment action subject MUST match draft posture",
        "semantic judgment alternatives MUST be unique",
        "semantic judgment ambiguity MUST match its unresolved meaning",
        "semantic judgment clarification MUST be one question",
        "semantic judgment confidence MUST be finite",
        "semantic judgment requested_facets MUST be unique",
        "semantic judgment secondary_intents MUST be unique",
        "semantic target source span exceeds the utterance",
        "semantic target source span does not match the utterance",
        "semantic target source span MUST be ordered",
    }
)


class SemanticJudgmentModel(Protocol):
    """Propose candidate-only structured meaning without authority."""

    def judge(
        self,
        *,
        utterance: str,
        context: tuple[str, ...],
        capabilities: tuple[dict[str, Any], ...],
        profile_id: str,
        profile_version: str,
        schema_repair: tuple[dict[str, str], ...],
    ) -> Mapping[str, Any] | SemanticJudgmentModelResponse | None: ...


@dataclass(frozen=True, slots=True)
class SemanticJudgmentObservation:
    """Measured provider metadata for one authority-free judgment attempt."""

    model: str
    usage: Mapping[str, int] | None
    trace_call: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class SemanticJudgmentModelResponse:
    """One raw proposal paired with its already-issued provider observation."""

    proposal: Mapping[str, Any]
    observation: SemanticJudgmentObservation


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
        return self.receipt.disposition is SemanticJudgmentDisposition.ACCEPTED


class SemanticJudgmentBoundary:
    """Run bounded T1/T2 semantic judgment and validate every proposal."""

    def __init__(
        self,
        *,
        profile_id: str,
        profile_version: str,
        primary: SemanticJudgmentBinding | None,
        escalation: SemanticJudgmentBinding | None = None,
        confidence_threshold: float = 0.75,
    ) -> None:
        if primary is not None and primary.tier is not SemanticJudgmentTier.T1:
            raise ValueError("primary semantic judgment binding MUST use T1")
        if escalation is not None and escalation.tier is not SemanticJudgmentTier.T2:
            raise ValueError("escalation semantic judgment binding MUST use T2")
        if not 0.0 < confidence_threshold <= 1.0:
            raise ValueError("semantic judgment confidence threshold MUST be in (0, 1]")
        self.profile_id = profile_id
        self.profile_version = profile_version
        self._bindings = tuple(item for item in (primary, escalation) if item is not None)
        self._confidence_threshold = confidence_threshold

    def judge(
        self,
        *,
        utterance: str,
        context: Sequence[str],
        capabilities: Sequence[Mapping[str, Any]],
        allow_escalation: bool = True,
        bound_subject_types: Sequence[str] = (),
    ) -> SemanticJudgmentResult:
        """Return one bounded judgment, optionally restricting evaluation to T1."""

        started = time.monotonic()
        bounded_context = _bounded_context(context)
        bounded_capabilities = _bounded_capabilities(capabilities)
        bounded_subject_types = _bounded_subject_types(
            bound_subject_types,
            capabilities=bounded_capabilities,
        )
        input_digest = content_digest({"utterance": utterance})
        context_digest = content_digest({"context": list(bounded_context)})
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
        observations: list[SemanticJudgmentObservation] = []
        bindings = self._bindings if allow_escalation else self._bindings[:1]
        for binding in bindings:
            schema_repair: tuple[dict[str, str], ...] = ()
            for attempt in range(_MAX_SCHEMA_ATTEMPTS_PER_BINDING):
                model_response = binding.model.judge(
                    utterance=utterance,
                    context=bounded_context,
                    capabilities=bounded_capabilities,
                    profile_id=self.profile_id,
                    profile_version=self.profile_version,
                    schema_repair=schema_repair,
                )
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
                    proposal = _ground_unique_source_spans(
                        proposal,
                        utterance=utterance,
                        capabilities=bounded_capabilities,
                    )
                    proposal = _normalize_primary_intent_capability(
                        proposal,
                        capabilities=bounded_capabilities,
                    )
                    _validate_source_spans(proposal, utterance=utterance)
                except (TypeError, ValueError, ValidationError) as exc:
                    recovered_trace = _recover_safe_ontology_trace_proposal(
                        raw,
                        utterance=utterance,
                        capabilities=bounded_capabilities,
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
                    recovered_proposal = _recover_bound_subject_proposal(
                        raw,
                        utterance=utterance,
                        capabilities=bounded_capabilities,
                        bound_subject_types=bounded_subject_types,
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
                    latest_repair = _schema_repair_feedback(exc)
                    schema_repair = _merge_schema_repair(schema_repair, latest_repair)
                    _log_proposal_rejection(exc, validation_reason=schema_repair)
                    final_disposition = SemanticJudgmentDisposition.MALFORMED
                    final_reason = "proposal_invalid"
                    if attempt + 1 < _MAX_SCHEMA_ATTEMPTS_PER_BINDING:
                        _LOGGER.info(
                            "semantic_judgment_proposal_retry",
                            extra={"tier": binding.tier.value, "attempt": attempt + 1},
                        )
                        continue
                    break
                if proposal.ambiguous:
                    final_disposition = SemanticJudgmentDisposition.CLARIFICATION
                    final_reason = "clarification_required"
                    if binding is not bindings[-1]:
                        break
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
        return SemanticJudgmentResult(
            proposal=proposal,
            receipt=receipt,
            observations=observations,
        )


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
        proposal = _normalize_primary_intent_capability(
            proposal,
            capabilities=capabilities,
        )
        _validate_source_spans(proposal, utterance=utterance)
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
        proposal = _ground_unique_source_spans(
            proposal,
            utterance=utterance,
            capabilities=capabilities,
        )
        proposal = _normalize_primary_intent_capability(
            proposal,
            capabilities=capabilities,
        )
        _validate_source_spans(proposal, utterance=utterance)
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
    targets = normalized.get("targets")
    if isinstance(targets, (list, tuple)):
        normalized["targets"] = [
            {**target, "kind": canonicalize(target.get("kind"))}
            if isinstance(target, Mapping)
            else target
            for target in targets
        ]
    return normalized


def _validate_source_spans(proposal: SemanticJudgmentProposal, *, utterance: str) -> None:
    for target in proposal.targets:
        if target.source_end > len(utterance):
            raise ValueError("semantic target source span exceeds the utterance")
        if utterance[target.source_start : target.source_end] != target.value:
            raise ValueError("semantic target source span does not match the utterance")


def _normalize_primary_intent_capability(
    proposal: SemanticJudgmentProposal,
    *,
    capabilities: tuple[dict[str, Any], ...],
) -> SemanticJudgmentProposal:
    link_names = {
        name
        for capability in capabilities
        if capability.get("kind") == "link_type"
        if isinstance((name := capability.get("name")), str)
    }
    if proposal.primary_intent not in link_names:
        return proposal
    namespaced_intent = f"query.{proposal.primary_intent}"
    if len(namespaced_intent) > 80:
        raise ValueError("semantic link intent MUST use query namespace")
    return proposal.model_copy(update={"primary_intent": namespaced_intent})


def _ground_unique_source_spans(
    proposal: SemanticJudgmentProposal,
    *,
    utterance: str,
    capabilities: tuple[dict[str, Any], ...],
) -> SemanticJudgmentProposal:
    canonical_targets = {
        (kind, name)
        for capability in capabilities
        if isinstance((kind := capability.get("kind")), str)
        if isinstance((name := capability.get("name")), str)
    }
    targets = []
    changed = False
    for target_index, target in enumerate(proposal.targets):
        if utterance[target.source_start : target.source_end] == target.value:
            targets.append(target)
            continue
        source_start = utterance.find(target.value)
        second_start = utterance.find(target.value, source_start + 1) if source_start >= 0 else -1
        if source_start < 0 or second_start >= 0:
            _LOGGER.warning(
                "semantic_judgment_target_span_unresolved",
                extra={
                    "target_index": target_index,
                    "target_kind": target.kind,
                    "exact_occurrences": 0 if source_start < 0 else 2,
                },
            )
            if (
                target.canonical_value is not None
                and (target.kind, target.canonical_value) in canonical_targets
            ):
                changed = True
                continue
            targets.append(target)
            continue
        targets.append(
            target.model_copy(
                update={
                    "source_start": source_start,
                    "source_end": source_start + len(target.value),
                }
            )
        )
        changed = True
    return proposal.model_copy(update={"targets": tuple(targets)}) if changed else proposal


def _schema_repair_feedback(
    exc: TypeError | ValueError | ValidationError,
) -> tuple[dict[str, str], ...]:
    if isinstance(exc, ValidationError):
        return tuple(
            {
                "location": ".".join(str(part) for part in error["loc"]),
                "type": error["type"],
                **(
                    {"reason": reason}
                    if (reason := str(error.get("ctx", {}).get("error", "")))
                    in _SAFE_REJECTION_REASONS
                    else {}
                ),
            }
            for error in exc.errors(include_input=False, include_url=False)[:_MAX_SCHEMA_ERRORS]
        )
    reason = str(exc)
    return (
        {
            "location": "",
            "type": "value_error" if isinstance(exc, ValueError) else "type_error",
            **({"reason": reason} if reason in _SAFE_REJECTION_REASONS else {}),
        },
    )


def _merge_schema_repair(
    existing: tuple[dict[str, str], ...],
    latest: tuple[dict[str, str], ...],
) -> tuple[dict[str, str], ...]:
    merged: list[dict[str, str]] = []
    identities: set[tuple[tuple[str, str], ...]] = set()
    for item in (*existing, *latest):
        identity = tuple(sorted(item.items()))
        if identity in identities:
            continue
        identities.add(identity)
        merged.append(item)
        if len(merged) == _MAX_SCHEMA_ERRORS:
            break
    return tuple(merged)


def _log_proposal_rejection(
    exc: TypeError | ValueError | ValidationError,
    *,
    validation_reason: tuple[dict[str, str], ...],
) -> None:
    rejection: dict[str, str] = {"failure_type": type(exc).__name__}
    if isinstance(exc, ValidationError):
        rejection["validation_reason"] = json.dumps(
            validation_reason,
            separators=(",", ":"),
            sort_keys=True,
        )
    elif str(exc) in _SAFE_REJECTION_REASONS:
        rejection["reason"] = str(exc)
    _LOGGER.warning("semantic_judgment_proposal_rejected", extra=rejection)


__all__ = [
    "SemanticJudgmentBinding",
    "SemanticJudgmentBoundary",
    "SemanticJudgmentModel",
    "SemanticJudgmentResult",
]
