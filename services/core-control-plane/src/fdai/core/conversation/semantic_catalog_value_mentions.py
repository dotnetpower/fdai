"""Report catalog value terms stated in one utterance as candidate grounding evidence.

A mention reuses the planner's stated-value grounding for ``Resource.type`` and adds
the exact source span of the declared term. Semantic judgment receives it only as
candidate evidence, and the manifest contradiction hold compares it with a proposed
meaning. A mention never selects an intent, route, or capability, and grants no
authority.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .semantic_planning_value_filters import stated_value_filters
from .semantic_target_identity import runtime_target_spans

_OBJECT_TYPE = "Resource"
_PROPERTY = "type"
# Characters that join an ASCII term into a larger identifier, such as a Resource name.
_IDENTIFIER_JOINERS = frozenset("-_./:")


@dataclass(frozen=True, slots=True)
class StatedCatalogValue:
    """One unambiguous catalog value binding and the exact utterance span that states it."""

    object_type: str
    property_name: str
    text: str
    source_start: int
    source_end: int
    values: tuple[str, ...]

    def capability_hint(self) -> dict[str, object]:
        """Project the binding into the candidate-only judgment capability shape."""

        return {
            "property": f"{self.object_type}.{self.property_name}",
            "text": self.text,
            "source_start": self.source_start,
            "source_end": self.source_end,
            "values": list(self.values),
        }


def stated_catalog_values(
    utterance: str,
    descriptors: Sequence[Mapping[str, Any]],
) -> tuple[StatedCatalogValue, ...]:
    """Return the unambiguous ``Resource.type`` binding stated in the utterance, if any.

    The binding uses the same group selection as ``stated_value_filters``. A term that
    is part of a larger identifier, such as an exact Resource name, states no subtype.
    """

    lowered = utterance.casefold()
    if len(lowered) != len(utterance):
        return ()
    values = stated_value_filters(
        utterance,
        descriptors,
        allowed_properties=frozenset({_PROPERTY}),
    ).get((_OBJECT_TYPE, _PROPERTY), ())
    if not values:
        return ()
    span = _earliest_term_span(
        _group_terms(descriptors, values),
        lowered,
        runtime_target_spans(utterance),
    )
    if span is None:
        return ()
    start, end = span
    return (
        StatedCatalogValue(
            object_type=_OBJECT_TYPE,
            property_name=_PROPERTY,
            text=utterance[start:end],
            source_start=start,
            source_end=end,
            values=values,
        ),
    )


def _group_terms(
    descriptors: Sequence[Mapping[str, Any]],
    values: tuple[str, ...],
) -> tuple[str, ...]:
    expected = frozenset(values)
    terms: list[str] = []
    for descriptor in descriptors:
        if descriptor.get("kind") != "object" or descriptor.get("name") != _OBJECT_TYPE:
            continue
        properties = descriptor.get("properties")
        declaration = properties.get(_PROPERTY) if isinstance(properties, Mapping) else None
        groups = declaration.get("value_groups") if isinstance(declaration, Mapping) else None
        for group in groups if isinstance(groups, list) else ():
            if not isinstance(group, Mapping):
                continue
            group_values = group.get("values")
            group_terms = group.get("terms")
            if (
                isinstance(group_values, list)
                and isinstance(group_terms, list)
                and frozenset(str(value) for value in group_values) == expected
            ):
                terms.extend(term for term in group_terms if isinstance(term, str))
    return tuple(dict.fromkeys(terms))


def _earliest_term_span(
    terms: Sequence[str],
    lowered_utterance: str,
    runtime_spans: Sequence[tuple[int, int]],
) -> tuple[int, int] | None:
    best: tuple[int, int] | None = None
    for term in terms:
        needle = term.casefold().strip()
        if not needle:
            continue
        start = lowered_utterance.find(needle)
        while start != -1:
            end = start + len(needle)
            if _bounded(needle, lowered_utterance, start, end) and not any(
                start < span_end and span_start < end for span_start, span_end in runtime_spans
            ):
                if best is None or (start, -end) < (best[0], -best[1]):
                    best = (start, end)
                break
            start = lowered_utterance.find(needle, start + 1)
    return best


def _bounded(needle: str, lowered_utterance: str, start: int, end: int) -> bool:
    """Require identifier boundaries around ASCII term edges.

    Korean attaches particles without spaces, so a Hangul edge needs no boundary.
    """

    before = lowered_utterance[start - 1] if start else " "
    after = lowered_utterance[end] if end < len(lowered_utterance) else " "
    return (not _ascii_word(needle[0]) or not _joins_identifier(before)) and (
        not _ascii_word(needle[-1]) or not _joins_identifier(after)
    )


def _ascii_word(value: str) -> bool:
    return value.isascii() and value.isalnum()


def _joins_identifier(value: str) -> bool:
    return _ascii_word(value) or value in _IDENTIFIER_JOINERS


__all__ = ["StatedCatalogValue", "stated_catalog_values"]
