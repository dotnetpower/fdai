"""Rank bounded resource-name suggestions from authorized query evidence."""

from __future__ import annotations

import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass

from fdai.core.ontology_platform import QueryPlanExecution
from fdai.core.ontology_platform.query_values import QueryTable

_CANDIDATE_NODE_PREFIX = "gateway-name-candidates-"
_MIN_SIMILARITY = 0.6
_MAX_SUGGESTIONS = 5


@dataclass(frozen=True, slots=True)
class ResourceNameSuggestion:
    """One observed resource name that resembles an unresolved exact target."""

    name: str
    resource_type: str | None
    similarity: float

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("ResourceNameSuggestion name MUST be non-empty")
        if (
            isinstance(self.similarity, bool)
            or not isinstance(self.similarity, (int, float))
            or not (0.0 <= float(self.similarity) <= 1.0)
        ):
            raise ValueError("ResourceNameSuggestion similarity MUST be in [0.0, 1.0]")


def resource_name_suggestions(
    requested_name: str,
    execution: QueryPlanExecution,
) -> tuple[ResourceNameSuggestion, ...]:
    """Return bounded evidence-backed candidates without rebinding the target."""

    if not _normalized_name(requested_name):
        return ()
    ranked = [
        item
        for item in observed_resource_name_candidates(
            execution,
            requested_name=requested_name,
        )
        if item.similarity >= _MIN_SIMILARITY and item.similarity < 1.0
    ]
    return tuple(
        sorted(
            ranked,
            key=lambda item: (-item.similarity, item.name.casefold(), item.resource_type or ""),
        )[:_MAX_SUGGESTIONS]
    )


def observed_resource_name_candidates(
    execution: QueryPlanExecution,
    *,
    requested_name: str = "",
) -> tuple[ResourceNameSuggestion, ...]:
    """Return bounded same-type names even when none is lexically similar."""

    requested = _normalized_name(requested_name)
    candidates: list[ResourceNameSuggestion] = []
    seen: set[tuple[str, str | None]] = set()
    for node_id, result in execution.results.items():
        if not node_id.startswith(_CANDIDATE_NODE_PREFIX) or not isinstance(
            result.value, QueryTable
        ):
            continue
        for row in result.value.rows:
            props = row.values.get("properties")
            name = (
                row.values.get("name")
                if isinstance(row.values.get("name"), str)
                else props.get("name")
                if isinstance(props, Mapping)
                else None
            )
            resource_type = (
                row.values.get("type")
                if isinstance(row.values.get("type"), str)
                else props.get("type")
                if isinstance(props, Mapping)
                else None
            )
            if not isinstance(name, str) or not name.strip():
                continue
            resolved_type = (
                resource_type.strip()
                if isinstance(resource_type, str) and resource_type.strip()
                else None
            )
            key = (name.strip().casefold(), resolved_type)
            if key in seen:
                continue
            seen.add(key)
            similarity = (
                _normalized_similarity(requested, _normalized_name(name)) if requested else 0.0
            )
            candidates.append(
                ResourceNameSuggestion(
                    name=name.strip(),
                    resource_type=resolved_type,
                    similarity=similarity,
                )
            )
    return tuple(
        sorted(
            candidates,
            key=lambda item: (-item.similarity, item.name.casefold(), item.resource_type or ""),
        )[:_MAX_SUGGESTIONS]
    )


def _normalized_name(value: str) -> str:
    return " ".join(unicodedata.normalize("NFC", value).casefold().split())


def _normalized_similarity(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    distance = _levenshtein_distance(left, right)
    return 1.0 - (distance / max(len(left), len(right)))


def _levenshtein_distance(left: str, right: str) -> int:
    if len(left) < len(right):
        left, right = right, left
    previous = list(range(len(right) + 1))
    for left_index, left_character in enumerate(left, start=1):
        current = [left_index]
        for right_index, right_character in enumerate(right, start=1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[right_index] + 1,
                    previous[right_index - 1] + (left_character != right_character),
                )
            )
        previous = current
    return previous[-1]


__all__ = [
    "ResourceNameSuggestion",
    "observed_resource_name_candidates",
    "resource_name_suggestions",
]
