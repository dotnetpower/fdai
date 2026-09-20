"""Validate and report bounded schema-family repairs for semantic judgment."""

from __future__ import annotations

import json
import logging
from typing import Any

from fdai_service_contracts.semantic_judgment import SemanticJudgmentProposal
from pydantic import ValidationError

from .semantic_judgment_rejections import (
    SAFE_SEMANTIC_JUDGMENT_REJECTION_REASONS as _SAFE_REJECTION_REASONS,
)

_MAX_SCHEMA_ERRORS = 16
_SCHEMA_INTENTS = frozenset(
    {"query.manifest", "query.ontology_declaration", "query.ontology_relationships"}
)
_SCHEMA_METATYPES = frozenset(
    {"ActionType", "FunctionType", "InterfaceType", "LinkType", "ObjectType"}
)


def normalize_identity_ambiguity(
    proposal: SemanticJudgmentProposal,
    *,
    capabilities: tuple[dict[str, Any], ...],
) -> SemanticJudgmentProposal:
    """Remove only ambiguity contradicted by one supplied schema subject."""

    if (
        not proposal.ambiguous
        or proposal.action_posture != "advise_only"
        or proposal.secondary_intents
        or proposal.primary_intent
        not in {"query.ontology_declaration", "query.ontology_relationships"}
    ):
        return proposal
    object_names = {
        name
        for capability in capabilities
        if capability.get("kind") == "object_type"
        if isinstance((name := capability.get("name")), str)
    }
    target_subjects = {
        target.canonical_value
        for target in proposal.targets
        if target.kind == "object_type" and target.canonical_value in object_names
    }
    normalized_facets = {
        facet.replace("_", "").replace("-", "").casefold() for facet in proposal.requested_facets
    }
    facet_subjects = {
        name
        for name in object_names
        if any(facet.startswith(name.casefold()) for facet in normalized_facets)
    }
    subjects = target_subjects or facet_subjects
    declaration_complete = proposal.primary_intent == "query.ontology_declaration"
    relationship_complete = proposal.primary_intent == "query.ontology_relationships"
    if len(subjects) != 1 or not (declaration_complete or relationship_complete):
        return proposal
    return proposal.model_copy(
        update={
            "ambiguous": False,
            "alternatives": (),
            "unresolved_terms": (),
            "clarification": None,
        }
    )


def repair_required(proposal: SemanticJudgmentProposal) -> bool:
    """Return whether a no-authority schema-family proposal needs one repair pass."""

    if (
        proposal.primary_intent not in _SCHEMA_INTENTS
        or proposal.action_posture != "advise_only"
        or proposal.secondary_intents
        or proposal.execution_authority
    ):
        return False
    if (
        proposal.primary_intent == "query.manifest"
        and not proposal.targets
        and not proposal.ambiguous
        and any(
            set(proposal.requested_facets)
            == {f"{kind.removesuffix('Type').lower()}_types", "readable"}
            for kind in _SCHEMA_METATYPES
        )
    ):
        return False
    object_targets = {
        target.canonical_value
        for target in proposal.targets
        if target.kind == "object_type" and target.canonical_value is not None
    }
    if proposal.primary_intent != "query.manifest":
        required_facets = (
            {"declaration_detail", "readable_properties"}
            if proposal.primary_intent == "query.ontology_declaration"
            else {"incoming_relationships", "outgoing_relationships"}
        )
        return len(object_targets) != 1 or not required_facets <= set(proposal.requested_facets)
    if object_targets - _SCHEMA_METATYPES:
        return True
    has_count = "count" in proposal.requested_facets
    has_kind = len(object_targets.intersection(_SCHEMA_METATYPES)) == 1
    return not has_count or not has_kind


def repair_preserves_family(
    original: SemanticJudgmentProposal,
    repaired: SemanticJudgmentProposal,
) -> bool:
    """Require a repair to remain inside the read-only schema-query family."""

    return bool(
        original.primary_intent in _SCHEMA_INTENTS
        and repaired.primary_intent in _SCHEMA_INTENTS
        and repaired.action_posture == "advise_only"
        and repaired.action_subject == "none"
        and not repaired.secondary_intents
        and repaired.execution_authority is False
    )


def repair_feedback(
    exc: TypeError | ValueError | ValidationError,
) -> tuple[dict[str, str], ...]:
    """Project an exception into bounded, allowlisted schema-repair feedback."""

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


def merge_feedback(
    existing: tuple[dict[str, str], ...],
    latest: tuple[dict[str, str], ...],
) -> tuple[dict[str, str], ...]:
    """Deduplicate feedback while retaining first-seen order and the error bound."""

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


def log_rejection(
    exc: TypeError | ValueError | ValidationError,
    *,
    validation_reason: tuple[dict[str, str], ...],
    logger: logging.Logger,
) -> None:
    """Log only bounded schema metadata and allowlisted fixed contract reasons."""

    rejection: dict[str, str] = {"failure_type": type(exc).__name__}
    if isinstance(exc, ValidationError):
        rejection["validation_reason"] = json.dumps(
            validation_reason,
            separators=(",", ":"),
            sort_keys=True,
        )
    elif str(exc) in _SAFE_REJECTION_REASONS:
        rejection["reason"] = str(exc)
    logger.warning("semantic_judgment_proposal_rejected", extra=rejection)


__all__ = [
    "log_rejection",
    "merge_feedback",
    "normalize_identity_ambiguity",
    "repair_feedback",
    "repair_preserves_family",
    "repair_required",
]
