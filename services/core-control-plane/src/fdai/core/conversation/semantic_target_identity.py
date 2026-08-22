"""Resolve one exact runtime target from verified utterance and frame facts."""

from __future__ import annotations

import re
from typing import Any

_RUNTIME_TARGET = re.compile(
    r"(?<![A-Za-z0-9_.-])[A-Za-z][A-Za-z0-9]*(?:-[A-Za-z0-9]+){2,}"
    r"(?![A-Za-z0-9_.-])"
)
_FRAME_TARGET = re.compile(r"[A-Za-z][A-Za-z0-9]*(?:-[A-Za-z0-9]+)+")


def exact_target_from_constraints(
    subject_constraints: tuple[str, ...],
    *,
    utterance: str,
    descriptors: tuple[dict[str, Any], ...],
) -> str | None:
    """Return one source-grounded runtime identifier or preserve ambiguity."""

    scanned_utterance = utterance.rstrip(".!?")
    runtime_targets = tuple(match.group(0) for match in _RUNTIME_TARGET.finditer(scanned_utterance))
    if len(runtime_targets) == 1 and any(
        descriptor.get("kind") == "object" and descriptor.get("name") == "Resource"
        for descriptor in descriptors
    ):
        return runtime_targets[0]
    if runtime_targets:
        return None
    declared = {
        name.casefold()
        for descriptor in descriptors
        if descriptor.get("kind") in {"object", "interface"}
        if isinstance((name := descriptor.get("name")), str)
    }
    folded = utterance.casefold()
    candidates = tuple(
        subject
        for subject in subject_constraints
        if subject.casefold() not in declared
        if _FRAME_TARGET.fullmatch(subject)
        if folded.count(subject.casefold()) == 1
    )
    return candidates[0] if len(candidates) == 1 else None


__all__ = ["exact_target_from_constraints"]
