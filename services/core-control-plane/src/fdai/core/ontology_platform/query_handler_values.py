"""Shared validation and evidence helpers for ontology query handlers."""

from __future__ import annotations

from collections.abc import Mapping

from .query_execution import QueryNodeResult


def argument_name(value: object) -> str:
    """Validate one bounded dot-separated function argument name."""

    if (
        not isinstance(value, str)
        or not value.strip()
        or value != value.strip()
        or len(value) > 256
        or not value.isascii()
    ):
        raise ValueError("function argument name MUST contain between 1 and 256 characters")
    parts = value.split(".")
    if any(
        not part
        or not (part[0].isalpha() or part[0] == "_")
        or not part.replace("_", "").replace("-", "").isalnum()
        for part in parts
    ):
        raise ValueError("function argument name MUST be a dot-separated identifier")
    return value


def evidence_refs(dependencies: Mapping[str, QueryNodeResult]) -> tuple[str, ...]:
    """Return stable non-root evidence references from dependency results."""

    return tuple(
        dict.fromkeys(
            evidence_ref.strip()
            for result in dependencies.values()
            for evidence_ref in result.evidence_refs
            if isinstance(evidence_ref, str)
            and evidence_ref.strip()
            and not evidence_ref.startswith("ontology-object-set-output:")
        )
    )


__all__ = ["argument_name", "evidence_refs"]
