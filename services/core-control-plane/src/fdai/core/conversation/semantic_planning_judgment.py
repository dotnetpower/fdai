"""Deterministic helpers for consuming typed semantic judgments."""

from __future__ import annotations

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
            "query.resource_configuration_snapshot",
        }
    ),
}
_OPERATIONAL_OUTPUT_INTENTS = {
    "resource_configuration_changes": "query.resource_configuration_changes",
    "gateway_diagnostic_evidence": "query.gateway_diagnostic_evidence",
}
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
    """Project principal-scoped ontology descriptors without authority or schemas."""

    kind_map = {
        "action": "action_type",
        "function": "function_type",
        "interface": "interface_type",
        "link": "link_type",
        "object": "object_type",
    }
    capabilities: list[dict[str, Any]] = []
    for descriptor in descriptors:
        kind = descriptor.get("kind")
        name = descriptor.get("name")
        if kind not in kind_map or not isinstance(name, str):
            continue
        capability = {"kind": kind_map[kind], "name": name}
        operation = descriptor.get("operation")
        if kind == "action" and isinstance(operation, str):
            capability["operation"] = operation
        capabilities.append(capability)
    return tuple(capabilities)


def _operational_frame_matches_accepted_judgment(
    *,
    output_shape: str,
    judgment: SemanticJudgmentProposal | None,
    judgment_accepted: bool,
) -> bool:
    """Require accepted typed intent for operational frame families."""

    required_intent = _OPERATIONAL_OUTPUT_INTENTS.get(output_shape)
    if required_intent is None:
        return True
    return judgment_accepted and judgment is not None and judgment.primary_intent == required_intent


def _descriptors_for_judgment(
    descriptors: tuple[dict[str, Any], ...],
    judgment: SemanticJudgmentProposal,
) -> tuple[dict[str, Any], ...]:
    """Narrow known operational families after model-backed intent classification."""

    required = _OPERATIONAL_DESCRIPTOR_NAMES.get(judgment.primary_intent)
    if required is None:
        return descriptors
    selected = tuple(descriptor for descriptor in descriptors if descriptor.get("name") in required)
    selected_names = {descriptor.get("name") for descriptor in selected}
    if not required <= selected_names:
        return descriptors
    return selected
