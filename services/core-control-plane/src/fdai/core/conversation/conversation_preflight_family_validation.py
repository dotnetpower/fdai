"""Operational promotion and family-shape validation for conversation preflight."""

from __future__ import annotations

import logging

from fdai_service_contracts.ontology_query import content_digest
from fdai_service_contracts.semantic_judgment import SemanticJudgmentProposal, SemanticTarget

from .conversation_preflight_contracts import (
    ContextDependency,
    ConversationPreflightResult,
    OperationalPreflightFamily,
    OperationalSignal,
)
from .conversation_preflight_operational_shapes import validate_operational_family
from .conversation_preflight_targets import (
    GENERIC_SUBSCRIPTION_SCOPE_FILTERS,
    operational_target_is_exact,
    operational_target_is_generic,
    operational_time_is_past_hour,
)
from .conversation_preflight_validation import preflight_input_digest as _preflight_input_digest
from .semantic_target_identity import runtime_target_spans

_LOGGER = logging.getLogger("fdai.core.conversation.conversation_preflight")

_OPERATIONAL_ROUTE_PROMOTION_CONFIDENCE = 0.75


def preflight_operational_judgment(
    result: ConversationPreflightResult,
    *,
    utterance: str,
    allow_resource_collection: bool = False,
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
            proposal.operational_family is not OperationalPreflightFamily.RESOURCE_COLLECTION
            or allow_resource_collection,
            "capability_aware_judgment_required",
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
            proposal.confidence >= _OPERATIONAL_ROUTE_PROMOTION_CONFIDENCE,
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
    exact_runtime_spans = runtime_target_spans(utterance)
    normalized_targets: list[SemanticTarget] = []
    for target in proposal.operational_targets:
        gateway_family = (
            proposal.operational_family is OperationalPreflightFamily.GATEWAY_DIAGNOSTIC_EVIDENCE
        )
        if gateway_family and target.kind == "gateway":
            target = target.model_copy(update={"kind": "resource"})
        if gateway_family and target.kind in {"resource_name_filter", "resource_type_filter"}:
            continue
        if (
            proposal.operational_family is OperationalPreflightFamily.RESOURCE_CONFIGURATION_CHANGES
            and target.kind == "resource_type_filter"
            and target.value.strip().casefold() in GENERIC_SUBSCRIPTION_SCOPE_FILTERS
        ):
            continue
        if (
            gateway_family
            and target.kind in {"resource", "backend", "model"}
            and operational_target_is_generic(target.value)
        ):
            continue
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
            if target.canonical_value != "duration.PT1H" or not operational_time_is_past_hour(
                target.value
            ):
                return _reject_operational_promotion("unsupported_time_canonicalization")
        collection_filter = proposal.operational_family in {
            OperationalPreflightFamily.RESOURCE_COLLECTION,
            OperationalPreflightFamily.RESOURCE_CONFIGURATION_CHANGES,
        } and target.kind in {
            "resource_type_filter",
            "resource_state_exclusion_filter",
            "resource_state_filter",
            "resource_name_filter",
        }
        if target.kind not in {
            "resource",
            "time_range",
            "backend",
            "model",
            "resource_type_filter",
            "resource_state_exclusion_filter",
            "resource_state_filter",
            "resource_name_filter",
        }:
            return _reject_operational_promotion("unsupported_target_kind")
        if collection_filter and target.canonical_value is not None:
            return _reject_operational_promotion("collection_filter_canonicalization_not_allowed")
        if collection_filter and any(
            start <= target.source_start and target.source_end <= end
            for start, end in exact_runtime_spans
        ):
            return _reject_operational_promotion("collection_filter_overlaps_exact_resource")
        if (
            collection_filter
            and target.kind not in {"resource_state_exclusion_filter", "resource_state_filter"}
            and (
                target.value.casefold().startswith("/subscriptions/")
                or (
                    not any(character.isspace() for character in target.value)
                    and (
                        "-" in target.value
                        or any(character.isdigit() for character in target.value)
                    )
                )
            )
        ):
            return _reject_operational_promotion("collection_filter_looks_like_exact_resource")
        if (
            target.kind != "time_range"
            and not collection_filter
            and not operational_target_is_exact(target.value)
        ):
            return _reject_operational_promotion("generic_target_identity")
        if (
            proposal.operational_family is OperationalPreflightFamily.RESOURCE_CURRENT_STATE
            and target.kind == "resource"
        ):
            target = target.model_copy(
                update={
                    "canonical_value": (
                        "Resource.id"
                        if target.value.casefold().startswith("/subscriptions/")
                        else "Resource.name"
                    )
                }
            )
        normalized_targets.append(target)
    if (
        proposal.operational_family is OperationalPreflightFamily.GATEWAY_DIAGNOSTIC_EVIDENCE
        and not any(target.kind == "resource" for target in normalized_targets)
        and len(exact_runtime_spans) == 1
    ):
        source_start, source_end = exact_runtime_spans[0]
        normalized_targets.append(
            SemanticTarget(
                kind="resource",
                value=utterance[source_start:source_end],
                canonical_value="Resource.name",
                source_start=source_start,
                source_end=source_end,
            )
        )
    selection = validate_operational_family(
        proposal,
        normalized_targets=normalized_targets,
        utterance=utterance,
    )
    if selection is None:
        return _reject_operational_promotion("invalid_family_shape")
    return SemanticJudgmentProposal(
        primary_intent=selection.primary_intent,
        targets=tuple(normalized_targets),
        requested_facets=selection.normalized_facets,
        confidence=proposal.confidence,
        ambiguous=False,
        action_posture="advise_only",
        action_subject="none",
        authority="candidate_only",
        execution_authority=False,
    )


def _reject_operational_promotion(reason: str) -> SemanticJudgmentProposal | None:
    _LOGGER.info(
        "conversation_preflight_operational_promotion_rejected",
        extra={"reason": reason},
    )
    return None
