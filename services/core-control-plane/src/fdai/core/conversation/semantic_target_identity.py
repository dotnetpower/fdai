"""Resolve one exact runtime target from verified utterance and frame facts."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

_RUNTIME_TARGET = re.compile(
    r"(?<![A-Za-z0-9_.-])[A-Za-z][A-Za-z0-9]*(?:-[A-Za-z0-9]+){2,}"
    r"(?![A-Za-z0-9_.-])"
)
_FRAME_TARGET = re.compile(r"[A-Za-z][A-Za-z0-9]*(?:-[A-Za-z0-9]+)+")
_TYPED_RESOURCE_TARGET = re.compile(r"Resource\.(id|name|display_name)=(.+)")
_ARM_RESOURCE_TARGET = re.compile(r"(?i)(?<!\S)/subscriptions/[0-9a-f-]{36}(?:/[^\s\"'<>]+)+")


@dataclass(frozen=True, slots=True)
class ExactResourceTarget:
    """One source-grounded Resource identity property and value."""

    property_name: str
    value: str


def exact_target_from_constraints(
    subject_constraints: tuple[str, ...],
    *,
    utterance: str,
    descriptors: tuple[dict[str, Any], ...],
) -> str | None:
    """Return one source-grounded runtime identifier or preserve ambiguity."""

    target = exact_resource_target_from_constraints(
        subject_constraints,
        utterance=utterance,
        descriptors=descriptors,
    )
    return target.value if target is not None else None


def exact_resource_target_from_constraints(
    subject_constraints: tuple[str, ...],
    *,
    utterance: str,
    descriptors: tuple[dict[str, Any], ...],
) -> ExactResourceTarget | None:
    """Return one typed Resource identity without changing its property."""

    identity_properties = _resource_identity_properties(descriptors)
    arm_targets = tuple(
        dict.fromkeys(
            match.group(0).rstrip(".,!?;:)]}") for match in _ARM_RESOURCE_TARGET.finditer(utterance)
        )
    )
    if len(arm_targets) == 1 and "id" in identity_properties:
        return ExactResourceTarget(property_name="id", value=arm_targets[0])
    if arm_targets:
        return None
    typed_targets: list[ExactResourceTarget] = []
    folded = utterance.casefold()
    for constraint in subject_constraints:
        match = _TYPED_RESOURCE_TARGET.fullmatch(constraint.strip())
        if match is None:
            continue
        property_name, value = match.group(1), match.group(2).strip()
        candidate = ExactResourceTarget(property_name=property_name, value=value)
        if (
            property_name in identity_properties
            and value
            and folded.count(value.casefold()) == 1
            and candidate not in typed_targets
        ):
            typed_targets.append(candidate)
    if len(typed_targets) == 1:
        return typed_targets[0]
    if typed_targets:
        return None

    runtime_spans = runtime_target_spans(utterance)
    runtime_targets = tuple(utterance[start:end] for start, end in runtime_spans)
    if len(runtime_targets) == 1 and any(
        descriptor.get("kind") == "object" and descriptor.get("name") == "Resource"
        for descriptor in descriptors
    ):
        property_name = next(
            (name for name in ("name", "display_name", "id") if name in identity_properties),
            "name",
        )
        return ExactResourceTarget(property_name=property_name, value=runtime_targets[0])
    if runtime_targets:
        return None
    declared = {
        name.casefold()
        for descriptor in descriptors
        if descriptor.get("kind") in {"object", "interface"}
        if isinstance((name := descriptor.get("name")), str)
    }
    candidates = tuple(
        subject
        for subject in subject_constraints
        if subject.casefold() not in declared
        if _FRAME_TARGET.fullmatch(subject)
        if folded.count(subject.casefold()) == 1
    )
    if len(candidates) != 1:
        return None
    property_name = next(
        (name for name in ("name", "display_name", "id") if name in identity_properties),
        "name",
    )
    return ExactResourceTarget(property_name=property_name, value=candidates[0])


def _resource_identity_properties(
    descriptors: tuple[dict[str, Any], ...],
) -> frozenset[str]:
    selected = tuple(
        descriptor
        for descriptor in descriptors
        if descriptor.get("kind") == "object" and descriptor.get("name") == "Resource"
    )
    if len(selected) != 1 or not isinstance(selected[0].get("properties"), Mapping):
        return frozenset()
    properties = selected[0]["properties"]
    return frozenset(name for name in ("id", "name", "display_name") if name in properties)


def runtime_target_spans(utterance: str) -> tuple[tuple[int, int], ...]:
    """Return source spans for exact runtime identifiers in one utterance."""

    scanned_utterance = utterance.rstrip(".!?")
    return tuple(
        (match.start(), match.end()) for match in _RUNTIME_TARGET.finditer(scanned_utterance)
    )


__all__ = [
    "ExactResourceTarget",
    "exact_resource_target_from_constraints",
    "exact_target_from_constraints",
    "runtime_target_spans",
]
