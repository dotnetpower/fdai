"""Shared validation and evidence helpers for ontology query handlers."""

from __future__ import annotations

from collections.abc import Mapping

from .query_execution import QueryNodeResult


def argument_name(value: object) -> str:
    """Validate one bounded dot-separated function argument name."""

    if not isinstance(value, str) or not value or len(value) > 256:
        raise ValueError("function argument name MUST contain between 1 and 256 characters")
    parts = value.split(".")
    if any(not part or not part.replace("_", "").replace("-", "").isalnum() for part in parts):
        raise ValueError("function argument name MUST be a dot-separated identifier")
    return value


def evidence_refs(dependencies: Mapping[str, QueryNodeResult]) -> tuple[str, ...]:
    """Return stable non-root evidence references from dependency results."""

    return tuple(
        dict.fromkeys(
            evidence_ref
            for result in dependencies.values()
            for evidence_ref in result.evidence_refs
            if not evidence_ref.startswith("ontology-object-set-output:")
        )
    )


__all__ = ["argument_name", "evidence_refs"]
