"""Deterministic helpers for consuming typed semantic judgments."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from fdai_service_contracts.ontology_query import SemanticOperation, SemanticProblemFrame
from fdai_service_contracts.semantic_judgment import (
    SemanticDiscourseMode,
    SemanticJudgmentDisposition,
    SemanticJudgmentProposal,
    SemanticJudgmentTier,
)
from pydantic import ValidationError

from .conversation_preflight_targets import named_subscription_requested
from .semantic_judgment import SemanticJudgmentObservation
from .semantic_planning_models import (
    SemanticDirectResponseIntent,
    SemanticOutputShape,
)


@dataclass(frozen=True)
class _JudgmentDecision:
    """Record one bounded semantic-judgment decision for planning."""

    proposal: SemanticJudgmentProposal | None
    disposition: SemanticJudgmentDisposition
    tier: SemanticJudgmentTier | None
    observations: tuple[SemanticJudgmentObservation, ...] = ()
    accepted: bool = False


_OPERATIONAL_DESCRIPTOR_NAMES = {
    "create.document": frozenset({"Resource"}),
    "query.contextual_resources": frozenset({"Resource"}),
    "query.resource_health_inventory": frozenset({"Resource", "query.resource_health_inventory"}),
    "query.resource_current_state": frozenset({"Resource", "query.resource_current_state"}),
    "query.resource_change_activity": frozenset(
        {
            "Resource",
            "query.resource_change_activity",
            "query.recent_resource_changes",
            "query.resource_state_transitions",
        }
    ),
    "query.resource_event_history": frozenset({"Resource", "query.resource_event_history"}),
    "query.resource_state_inventory": frozenset({"Resource", "query.resource_state_inventory"}),
    "query.subscription_scope_identity": frozenset({"query.subscription_scope_identity"}),
    "query.subscription_service_health": frozenset({"query.subscription_service_health"}),
    "query.resource_configuration_changes": frozenset(
        {
            "Resource",
            "query.resource_configuration_changes",
            "query.resource_configuration_snapshot",
        }
    ),
    "query.gateway_diagnostic_evidence": frozenset(
        {
            "Resource",
            "routes_to",
            "query.gateway_diagnostic_evidence",
            "query.resource_configuration_changes",
            "query.resource_current_state",
            "query.resource_state_inventory",
            "query.resource_configuration_snapshot",
        }
    ),
}
_MAX_JUDGMENT_CAPABILITY_BYTES = 32 * 1024
_PRIMARY_OPERATIONAL_OUTPUT_INTENTS: dict[str, str] = {
    "resource_configuration_changes": "query.resource_configuration_changes",
    "gateway_diagnostic_evidence": "query.gateway_diagnostic_evidence",
}
_SUMMARY_OPERATIONAL_OUTPUT_INTENTS: dict[str, str] = {
    "resource_health_list": "query.resource_health_inventory",
    "resource_state_list": "query.resource_state_inventory",
    "subscription_scope_identity": "query.subscription_scope_identity",
    "subscription_service_health": "query.subscription_service_health",
}
_DERIVED_RESOURCE_OUTPUT_INTENTS: dict[str, frozenset[str]] = {
    "resource_condition_sections": frozenset(
        {
            "query.resource_health_inventory",
            "query.resource_state_inventory",
        }
    ),
}
_PRIMARY_ONLY_SUMMARY_OUTPUTS = frozenset(
    {
        "resource_health_list",
        "resource_state_list",
        "subscription_scope_identity",
        "subscription_service_health",
    }
)
_RESOURCE_COLLECTION_SUMMARY_OUTPUTS = frozenset(
    {"resource_condition_sections", "resource_health_list", "resource_state_list"}
)
_SERVICE_HEALTH_SOURCE_PATTERN = re.compile(r"(?i)(?:\bservice\s+health\b|서비스\s*(?:상태|헬스))")
_COMBINED_SUBSCRIPTION_REQUEST_PATTERN = re.compile(
    r"(?is)(?:\bservice\s+health\b|서비스\s*(?:상태|헬스)).*"
    r"(?:\btogether\s+with\b|\bas\s+well\s+as\b|\balong\s+with\b|\bplus\b|\band\b|"
    r"뿐만\s+아니라|(?<!\S)(?:그리고|및|같이)(?!\S)|하고\s+|(?:와|과)\s+).*"
    r"(?:\bsubscription\b|구독)"
)
_COMBINED_SUBSCRIPTION_REQUEST_REVERSE_PATTERN = re.compile(
    r"(?is)(?:\bsubscription\b|구독).*"
    r"(?:\btogether\s+with\b|\bas\s+well\s+as\b|\balong\s+with\b|\bplus\b|\band\b|"
    r"뿐만\s+아니라|(?<!\S)(?:그리고|및|같이)(?!\S)|하고\s+|(?:와|과)\s+).*"
    r"(?:\bservice\s+health\b|서비스\s*(?:상태|헬스))"
)
_SAFE_VALIDATION_REASONS = frozenset(
    {
        "investigation declaration is absent or ambiguous",
        "investigation target has no readable properties",
        "investigation relationship direction is invalid",
        "investigation relationship path endpoint does not compose",
        "investigation relationship path is empty",
        "investigation query side is absent or ambiguous",
        "query plan output_node_ids MUST reference declared nodes",
        "query extension arguments violate their registered schema",
        "metric concept is absent from the reviewed registry",
        "metric_scope_series MUST read one scoped query.table",
        "metric_scope_series dependency MUST be a scoped query.table",
        "semantic enum predicate operand is not grounded in the utterance",
        "relationship traversal requires one entity dependency",
        "relationship traversal source MUST be an object_set table",
        "relationship traversal target is absent from the manifest",
        "relationship traversal LinkType is absent from the manifest",
        "relationship traversal source endpoint type does not match",
        "relationship traversal target endpoint type is invalid",
        "relationship traversal target endpoint type does not match",
        "function dependencies MUST all have argument bindings",
        "function node omits required arguments",
        "function node supplies unknown arguments",
        "ontology relationship endpoints must exist in the principal manifest",
        "query node arguments do not match the closed schema",
    }
)
_DIRECT_RESPONSE_FACETS = {
    SemanticDirectResponseIntent.GREETING: frozenset(),
    SemanticDirectResponseIntent.SELF_INTRODUCTION: frozenset(
        {"identity", "role", "capabilities", "authority", "authority_boundary"}
    ),
}


def _direct_response(
    proposal: SemanticJudgmentProposal | None,
) -> tuple[SemanticDirectResponseIntent, str] | None:
    """Validate one canonical direct-answer intent selected by semantic judgment."""

    if (
        proposal is None
        or proposal.discourse_mode is not SemanticDiscourseMode.DIRECT
        or proposal.secondary_intents
        or proposal.targets
        or proposal.direct_response is None
    ):
        return None
    try:
        intent = SemanticDirectResponseIntent(proposal.primary_intent)
    except ValueError:
        return None
    if not set(proposal.requested_facets).issubset(_DIRECT_RESPONSE_FACETS[intent]):
        return None
    return intent, proposal.direct_response.answer


def _safe_validation_reason(exc: ValidationError | TypeError | ValueError) -> str:
    """Reduce validation failures to the bounded diagnostic vocabulary."""

    reason = str(exc)
    if reason in _SAFE_VALIDATION_REASONS:
        return reason
    if reason.startswith("query node kind "):
        return "query node kind is unavailable or has no verifier schema"
    return "validation_reason_not_allowlisted"


def _is_temporal_comparison(frame: SemanticProblemFrame | None) -> bool:
    """Return whether a frame is the supported temporal-comparison shape."""

    return (
        frame is not None
        and frame.operation is SemanticOperation.COMPARE
        and frame.output_shape == SemanticOutputShape.TEMPORAL_COMPARISON
    )


def _semantic_judgment_capabilities(
    descriptors: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, Any], ...]:
    """Project principal-scoped identity and reviewed intent semantics without authority."""

    kind_map = {
        "action": "action_type",
        "function": "function_type",
        "interface": "interface_type",
        "link": "link_type",
        "object": "object_type",
    }
    capabilities: list[dict[str, Any]] = []
    encoded_bytes = 2
    for descriptor in descriptors:
        kind = descriptor.get("kind")
        name = descriptor.get("name")
        if kind not in kind_map or not isinstance(name, str):
            continue
        capability: dict[str, Any] = {"kind": kind_map[kind], "name": name}
        operation = descriptor.get("operation")
        if kind == "action" and isinstance(operation, str):
            capability["operation"] = operation
        if kind == "function":
            output_schema = descriptor.get("output_schema")
            measure_concepts = (
                output_schema.get("x-fdai-measure-concepts")
                if isinstance(output_schema, Mapping)
                else None
            )
            if (
                isinstance(measure_concepts, list)
                and measure_concepts
                and len(measure_concepts) <= 32
                and all(isinstance(item, str) and 0 < len(item) <= 128 for item in measure_concepts)
            ):
                capability["measure_concepts"] = sorted(set(measure_concepts))
        if kind == "object":
            properties = descriptor.get("properties")
            if isinstance(properties, Mapping) and len(properties) <= 32:
                capability["canonical_values"] = [
                    name,
                    *(f"{name}.{property_name}" for property_name in sorted(properties)),
                ]
        capability_bytes = len(
            json.dumps(
                capability,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        )
        candidate_bytes = encoded_bytes + int(bool(capabilities)) + capability_bytes
        if candidate_bytes > _MAX_JUDGMENT_CAPABILITY_BYTES:
            break
        capabilities.append(capability)
        encoded_bytes = candidate_bytes
    return tuple(capabilities)


def _operational_frame_matches_accepted_judgment(
    *,
    output_shape: str,
    judgment: SemanticJudgmentProposal | None,
    judgment_accepted: bool,
    judgment_evaluated: bool = False,
    utterance: str = "",
    exact_resource_targeted: bool = False,
    derived_resource_intents_grounded: bool = False,
) -> bool:
    """Require accepted typed intent for operational frame families."""

    required_primary_intent = _PRIMARY_OPERATIONAL_OUTPUT_INTENTS.get(output_shape)
    required_summary_intent = _SUMMARY_OPERATIONAL_OUTPUT_INTENTS.get(output_shape)
    required_derived_intents = _DERIVED_RESOURCE_OUTPUT_INTENTS.get(output_shape)
    if (
        required_primary_intent is None
        and required_summary_intent is None
        and required_derived_intents is None
    ):
        return True
    if (
        required_summary_intent is not None or required_derived_intents is not None
    ) and not judgment_evaluated:
        if (
            output_shape in _PRIMARY_ONLY_SUMMARY_OUTPUTS
            or output_shape in _RESOURCE_COLLECTION_SUMMARY_OUTPUTS
        ) and named_subscription_requested(utterance):
            return False
        if output_shape in _RESOURCE_COLLECTION_SUMMARY_OUTPUTS and exact_resource_targeted:
            return False
        if output_shape == "resource_condition_sections":
            return derived_resource_intents_grounded
        if output_shape == "subscription_service_health" and (
            _COMBINED_SUBSCRIPTION_REQUEST_PATTERN.search(utterance) is not None
            or _COMBINED_SUBSCRIPTION_REQUEST_REVERSE_PATTERN.search(utterance) is not None
        ):
            return False
        return not (
            output_shape == "subscription_scope_identity"
            and _SERVICE_HEALTH_SOURCE_PATTERN.search(utterance) is not None
        )
    if not judgment_accepted or judgment is None:
        return False
    if required_primary_intent is not None:
        return bool(judgment.primary_intent == required_primary_intent)
    if required_derived_intents is not None:
        return not _has_unsupported_collection_target(judgment) and required_derived_intents == {
            judgment.primary_intent,
            *judgment.secondary_intents,
        }
    if output_shape in _PRIMARY_ONLY_SUMMARY_OUTPUTS:
        targets_match = (
            not _has_unsupported_collection_target(judgment)
            if output_shape in _RESOURCE_COLLECTION_SUMMARY_OUTPUTS
            else not judgment.targets
        )
        return (
            targets_match
            and not judgment.secondary_intents
            and judgment.primary_intent == required_summary_intent
        )
    return required_summary_intent in {
        judgment.primary_intent,
        *judgment.secondary_intents,
    }


def _has_unsupported_collection_target(judgment: SemanticJudgmentProposal) -> bool:
    """Return whether collection output would discard an exact or foreign-scope target."""

    return any(
        target.kind not in {"resource_state_filter", "resource_type_filter"}
        for target in judgment.targets
    )


def _descriptors_for_judgment(
    descriptors: tuple[dict[str, Any], ...],
    judgment: SemanticJudgmentProposal,
) -> tuple[dict[str, Any], ...]:
    """Narrow known operational families after model-backed intent classification."""

    return _descriptors_for_operational_intent(descriptors, judgment.primary_intent)


def _descriptors_for_operational_intent(
    descriptors: tuple[dict[str, Any], ...],
    primary_intent: str,
) -> tuple[dict[str, Any], ...]:
    """Narrow descriptors for one high-confidence operational intent."""

    required = _OPERATIONAL_DESCRIPTOR_NAMES.get(primary_intent)
    if required is None:
        return descriptors
    selected = tuple(descriptor for descriptor in descriptors if descriptor.get("name") in required)
    selected_names = {descriptor.get("name") for descriptor in selected}
    if not required <= selected_names:
        return descriptors
    return selected
