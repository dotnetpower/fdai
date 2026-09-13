"""Bound inputs and normalize validation feedback for conversation preflight."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, cast

from fdai_service_contracts.ontology_query import canonical_json, content_digest
from pydantic import ValidationError

from .conversation_preflight_targets import operational_target_is_generic

_MAX_CONTEXT_ITEMS = 4
_MAX_CONTEXT_CHARS = 4_000
_MAX_PROFILE_BYTES = 16_384
_COLLECTION_FILTER_TARGET_KINDS = frozenset(
    {
        "resource_name_filter",
        "resource_state_exclusion_filter",
        "resource_state_filter",
    }
)


def discard_generic_collection_filter_targets(value: object) -> object:
    """Drop model-proposed collection filters that contain only generic labels."""

    if not isinstance(value, Mapping) or value.get("operational_family") != "resource_collection":
        return value
    targets = value.get("operational_targets")
    if not isinstance(targets, Sequence) or isinstance(targets, (str, bytes)):
        return value
    filtered = tuple(
        target
        for target in targets
        if not (
            isinstance(target, Mapping)
            and target.get("kind") in _COLLECTION_FILTER_TARGET_KINDS
            and isinstance(target.get("value"), str)
            and operational_target_is_generic(cast(str, target["value"]))
        )
    )
    return value if len(filtered) == len(targets) else {**value, "operational_targets": filtered}


def bounded_context(context: Sequence[str]) -> tuple[str, ...]:
    """Return recent context when every item and the total size are valid."""

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


def bounded_profile(profile: Mapping[str, Any]) -> dict[str, Any]:
    """Copy one trusted response profile within the preflight byte bound."""

    selected = dict(profile)
    if len(canonical_json(selected).encode()) > _MAX_PROFILE_BYTES:
        raise ValueError("conversation preflight profile exceeds its byte bound")
    return selected


def preflight_input_digest(utterance: str) -> str:
    """Return the stable digest used to bind a proposal to its utterance."""

    return content_digest({"utterance": utterance})


def repair_instruction(exc: TypeError | ValueError | ValidationError) -> dict[str, str]:
    """Map validation failures to one bounded schema-repair instruction."""

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
