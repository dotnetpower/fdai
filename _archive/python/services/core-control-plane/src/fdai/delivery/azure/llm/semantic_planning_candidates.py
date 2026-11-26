"""Bounded ontology manifest projections for semantic planning."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def frame_descriptor_candidates(
    descriptors: tuple[dict[str, Any], ...],
) -> tuple[dict[str, Any], ...]:
    """Project exact manifest declarations into bounded frame-selection candidates."""

    candidates: list[dict[str, Any]] = []
    for descriptor in descriptors:
        kind = descriptor.get("kind")
        if kind == "action":
            continue
        candidate = {key: descriptor[key] for key in ("kind", "name") if key in descriptor}
        if kind == "link":
            for key in ("from_type", "to_type"):
                if key in descriptor:
                    candidate[key] = descriptor[key]
        elif kind == "function":
            if "read_sets" in descriptor:
                candidate["read_sets"] = descriptor["read_sets"]
            output_schema = descriptor.get("output_schema")
            if isinstance(output_schema, Mapping):
                measure_concepts = output_schema.get("x-fdai-measure-concepts")
                if measure_concepts is not None:
                    candidate["measure_concepts"] = measure_concepts
        candidates.append(candidate)
    return tuple(candidates)


__all__ = ["frame_descriptor_candidates"]
