"""Bound and sanitize semantic-judgment schema-repair diagnostics."""

from __future__ import annotations

import json
import logging

from pydantic import ValidationError

_MAX_SCHEMA_ERRORS = 16
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
        "semantic current-state intent requires a Resource target",
        "semantic direct response answer MUST be one paragraph",
        "semantic direct response answer MUST be trimmed",
        "semantic direct response answer MUST remain unambiguous and advisory",
        "semantic direct response intent MUST carry exactly one model-authored answer",
        "semantic direct response locale does not match the request",
        "semantic direct response profile digest does not match",
        "semantic judgment requested_facets MUST be unique",
        "semantic judgment secondary_intents MUST be unique",
        "semantic target source span exceeds the utterance",
        "semantic target source span does not match the utterance",
        "semantic target source span MUST be ordered",
    }
)


def schema_repair_feedback(
    exc: TypeError | ValueError | ValidationError,
) -> tuple[dict[str, str], ...]:
    """Return bounded machine diagnostics without model-authored values."""

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


def merge_schema_repair(
    existing: tuple[dict[str, str], ...],
    latest: tuple[dict[str, str], ...],
) -> tuple[dict[str, str], ...]:
    """Merge distinct repair entries while preserving first-seen order."""

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


def log_proposal_rejection(
    exc: TypeError | ValueError | ValidationError,
    *,
    validation_reason: tuple[dict[str, str], ...],
) -> None:
    """Log only bounded, allowlisted rejection diagnostics."""

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
