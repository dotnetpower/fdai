"""Typed assembly keys for dynamic semantic frame and plan prompts.

Frame guidance is selected by the accepted judgment's canonical intents and plan
guidance by the verified frame's output shape. A frame whose output shape is
governed by an excluded pack is re-proposed once with the complete prompt.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from fdai_service_contracts.ontology_query import SemanticProblemFrame

_KEY_VALUE = re.compile(r"^[a-z0-9][a-z0-9_.\-]{0,127}$")


def frame_assembly_keys(semantic_judgment: Mapping[str, Any] | None) -> tuple[str, ...] | None:
    """Return intent keys from one accepted judgment, or ``None`` for the complete prompt."""

    if not isinstance(semantic_judgment, Mapping):
        return None
    secondary = semantic_judgment.get("secondary_intents")
    intents = (
        semantic_judgment.get("primary_intent"),
        *(secondary if isinstance(secondary, (list, tuple)) else ()),
    )
    keys = sorted(
        {
            f"intent:{intent}"
            for intent in intents
            if isinstance(intent, str) and _KEY_VALUE.fullmatch(intent)
        }
    )
    return tuple(keys) or None


def plan_assembly_keys(frame: SemanticProblemFrame) -> tuple[str, ...]:
    """Return the verified frame's exact output-shape key."""

    shape = str(getattr(frame.output_shape, "value", frame.output_shape))
    return (f"shape:{shape}",) if _KEY_VALUE.fullmatch(shape) else ()


def frame_result_keys(proposal: Mapping[str, Any]) -> tuple[str, ...]:
    """Return the output-shape key a frame proposal produced."""

    shape = proposal.get("output_shape")
    return (f"shape:{shape}",) if isinstance(shape, str) and _KEY_VALUE.fullmatch(shape) else ()


__all__ = ["frame_assembly_keys", "frame_result_keys", "plan_assembly_keys"]
