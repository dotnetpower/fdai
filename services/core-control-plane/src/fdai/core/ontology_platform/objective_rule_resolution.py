"""Digest-pinned objective relations for non-authoritative Rule retrieval."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

from fdai.rule_catalog.schema.control_objective import (
    ControlObjective,
    ControlObjectiveState,
    control_objective_content_hash,
)
from fdai.rule_catalog.schema.rule_objective_binding import (
    BindingState,
    RuleObjectiveBinding,
    rule_objective_binding_content_hash,
)
from fdai.rule_catalog.schema.rule_semantic_retrieval import RuleCorpus

MAX_OBJECTIVE_REFS = 16
_MAX_OBJECTIVE_RULES = 256
_DIGEST = re.compile(r"^sha256:[a-f0-9]{64}$")
_REFERENCE = re.compile(r"^[A-Za-z][A-Za-z0-9._:@/-]{0,255}$")
_VERSIONED_RULE_REFERENCE = re.compile(r"^[a-z][a-z0-9._-]{0,127}@\d+\.\d+\.\d+$")


class ObjectiveResolutionState(StrEnum):
    """Outcome of resolving requested objectives to exact active Rule pins."""

    NOT_REQUESTED = "not_requested"
    RESOLVED = "resolved"
    DEGRADED = "degraded"


@dataclass(frozen=True, slots=True, order=True)
class ObjectiveResolutionPin:
    """One verified catalog reference and its exact content digest."""

    ref: str
    content_digest: str

    def __post_init__(self) -> None:
        if _REFERENCE.fullmatch(self.ref) is None:
            raise ValueError("objective resolution ref MUST be bounded ASCII")
        if _DIGEST.fullmatch(self.content_digest) is None:
            raise ValueError("objective resolution pin MUST be a sha256 digest")


@dataclass(frozen=True, slots=True)
class ObjectiveRuleResolution:
    """Non-authoritative resolution evidence or an explicit full-search fallback."""

    state: ObjectiveResolutionState
    requested_objective_refs: tuple[str, ...]
    candidate_rule_ids: tuple[str, ...] = ()
    objective_pins: tuple[ObjectiveResolutionPin, ...] = ()
    binding_pins: tuple[ObjectiveResolutionPin, ...] = ()
    rule_pins: tuple[ObjectiveResolutionPin, ...] = ()
    degraded_reason: str | None = None
    fallback_applied: bool = False

    def __post_init__(self) -> None:
        if self.requested_objective_refs != tuple(sorted(set(self.requested_objective_refs))):
            raise ValueError("requested objective refs MUST be unique and ordered")
        if len(self.requested_objective_refs) > MAX_OBJECTIVE_REFS:
            raise ValueError("requested objective refs exceed the resolution bound")
        if self.candidate_rule_ids != tuple(sorted(set(self.candidate_rule_ids))):
            raise ValueError("objective candidate Rule ids MUST be unique and ordered")
        if len(self.candidate_rule_ids) > _MAX_OBJECTIVE_RULES:
            raise ValueError("objective candidate Rule ids exceed the resolution bound")
        for values in (self.objective_pins, self.binding_pins, self.rule_pins):
            if values != tuple(sorted(set(values))):
                raise ValueError("objective resolution pins MUST be unique and ordered")
        if self.state is ObjectiveResolutionState.RESOLVED:
            if not self.candidate_rule_ids or self.degraded_reason is not None:
                raise ValueError("resolved objective context MUST contain exact Rule candidates")
            if self.fallback_applied:
                raise ValueError("resolved objective context MUST NOT apply fallback")
        elif self.candidate_rule_ids or self.objective_pins or self.binding_pins or self.rule_pins:
            raise ValueError("unresolved objective context MUST NOT claim catalog pins")
        if self.state is ObjectiveResolutionState.DEGRADED:
            if self.degraded_reason is None or not self.fallback_applied:
                raise ValueError("degraded objective context MUST name an explicit fallback")
        elif self.degraded_reason is not None or self.fallback_applied:
            raise ValueError("non-degraded objective context MUST NOT claim fallback")

    @property
    def digest(self) -> str:
        """Return the canonical digest of the complete resolution evidence."""

        encoded = json.dumps(
            objective_resolution_payload(self),
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


class ObjectiveRuleResolver:
    """Resolve reviewed, digest-current objective relations to exact active Rule ids."""

    def __init__(
        self,
        *,
        control_objectives: Sequence[ControlObjective],
        objective_bindings: Sequence[RuleObjectiveBinding],
        active_rule_digests: Mapping[str, str],
    ) -> None:
        self._objectives = {item.ref: item for item in control_objectives}
        if len(self._objectives) != len(control_objectives):
            raise ValueError("duplicate ControlObjective ref")
        self._bindings = tuple(sorted(objective_bindings, key=lambda item: item.ref))
        if len({item.ref for item in self._bindings}) != len(self._bindings):
            raise ValueError("duplicate RuleObjectiveBinding ref")
        for rule_ref, digest in active_rule_digests.items():
            if _REFERENCE.fullmatch(rule_ref) is None or _DIGEST.fullmatch(digest) is None:
                raise ValueError("active Rule registry MUST contain exact refs and digests")
        self._active_rule_digests = dict(active_rule_digests)

    def resolve(
        self,
        requested_objective_refs: tuple[str, ...],
        *,
        corpus: RuleCorpus,
    ) -> ObjectiveRuleResolution:
        """Resolve all refs or degrade atomically without narrowing candidates."""

        if not requested_objective_refs:
            return not_requested_resolution()
        if corpus is not RuleCorpus.ACTIVE:
            return degraded_resolution(
                requested_objective_refs,
                "objective_resolution_active_only",
            )

        objective_pins: set[ObjectiveResolutionPin] = set()
        binding_pins: set[ObjectiveResolutionPin] = set()
        rule_pins: set[ObjectiveResolutionPin] = set()
        candidate_rule_ids: set[str] = set()
        for objective_ref in requested_objective_refs:
            objective = self._objectives.get(objective_ref)
            if objective is None:
                return degraded_resolution(requested_objective_refs, "objective_not_found")
            if objective.state not in {
                ControlObjectiveState.REVIEWED,
                ControlObjectiveState.PROMOTED,
            }:
                return degraded_resolution(requested_objective_refs, "objective_not_reviewed")
            if (
                objective.content_digest != control_objective_content_hash(objective)
                or objective.provenance.content_hash != objective.content_digest
            ):
                return degraded_resolution(requested_objective_refs, "objective_digest_stale")

            eligible = tuple(
                binding
                for binding in self._bindings
                if binding.objective.ref == objective_ref
                and binding.state in {BindingState.REVIEWED, BindingState.PROMOTED}
            )
            if not eligible:
                return degraded_resolution(requested_objective_refs, "binding_unavailable")
            for binding in eligible:
                if (
                    binding.content_digest != rule_objective_binding_content_hash(binding)
                    or binding.provenance.content_hash != binding.content_digest
                ):
                    return degraded_resolution(requested_objective_refs, "binding_digest_stale")
                if binding.objective.content_digest != objective.content_digest:
                    return degraded_resolution(requested_objective_refs, "objective_pin_stale")
                active_digest = self._active_rule_digests.get(binding.rule.ref)
                if active_digest is None:
                    return degraded_resolution(requested_objective_refs, "active_rule_unavailable")
                if active_digest != binding.rule.content_digest:
                    return degraded_resolution(requested_objective_refs, "rule_pin_stale")
                if _VERSIONED_RULE_REFERENCE.fullmatch(binding.rule.ref) is None:
                    return degraded_resolution(requested_objective_refs, "rule_ref_invalid")
                rule_id, separator, _ = binding.rule.ref.rpartition("@")
                if not separator:
                    return degraded_resolution(requested_objective_refs, "rule_ref_invalid")
                objective_pins.add(ObjectiveResolutionPin(objective.ref, objective.content_digest))
                binding_pins.add(ObjectiveResolutionPin(binding.ref, binding.content_digest))
                rule_pins.add(ObjectiveResolutionPin(binding.rule.ref, binding.rule.content_digest))
                candidate_rule_ids.add(rule_id)
                if len(candidate_rule_ids) > _MAX_OBJECTIVE_RULES:
                    return degraded_resolution(requested_objective_refs, "rule_fanout_exceeded")

        return ObjectiveRuleResolution(
            state=ObjectiveResolutionState.RESOLVED,
            requested_objective_refs=requested_objective_refs,
            candidate_rule_ids=tuple(sorted(candidate_rule_ids)),
            objective_pins=tuple(sorted(objective_pins)),
            binding_pins=tuple(sorted(binding_pins)),
            rule_pins=tuple(sorted(rule_pins)),
        )


def requested_objective_refs(value: object) -> tuple[str, ...]:
    """Validate and canonicalize bounded objective references from function input."""

    if not isinstance(value, (list, tuple)):
        raise ValueError("objective_refs MUST be an array")
    if len(value) > MAX_OBJECTIVE_REFS:
        raise ValueError("objective_refs exceed the resolution bound")
    if any(not isinstance(item, str) or _REFERENCE.fullmatch(item) is None for item in value):
        raise ValueError("objective_refs MUST contain bounded ASCII references")
    result = tuple(sorted(value))
    if len(result) != len(set(result)):
        raise ValueError("objective_refs MUST be unique")
    return result


def not_requested_resolution() -> ObjectiveRuleResolution:
    """Build the canonical receipt for a query without objective context."""

    return ObjectiveRuleResolution(
        state=ObjectiveResolutionState.NOT_REQUESTED,
        requested_objective_refs=(),
    )


def degraded_resolution(
    requested_objective_refs: tuple[str, ...],
    reason: str,
) -> ObjectiveRuleResolution:
    """Build an explicit full-search fallback without verified catalog pins."""

    return ObjectiveRuleResolution(
        state=ObjectiveResolutionState.DEGRADED,
        requested_objective_refs=requested_objective_refs,
        degraded_reason=reason,
        fallback_applied=True,
    )


def objective_resolution_payload(
    resolution: ObjectiveRuleResolution,
) -> dict[str, object]:
    """Serialize resolution evidence with permanently false execution authority."""

    return {
        "state": resolution.state.value,
        "requested_objective_refs": list(resolution.requested_objective_refs),
        "candidate_rule_ids": list(resolution.candidate_rule_ids),
        "objective_pins": [
            {"ref": item.ref, "content_digest": item.content_digest}
            for item in resolution.objective_pins
        ],
        "binding_pins": [
            {"ref": item.ref, "content_digest": item.content_digest}
            for item in resolution.binding_pins
        ],
        "rule_pins": [
            {"ref": item.ref, "content_digest": item.content_digest}
            for item in resolution.rule_pins
        ],
        "degraded_reason": resolution.degraded_reason,
        "fallback_applied": resolution.fallback_applied,
        "authority": "candidate_only",
        "execution_authority": False,
    }


__all__ = [
    "MAX_OBJECTIVE_REFS",
    "ObjectiveResolutionPin",
    "ObjectiveResolutionState",
    "ObjectiveRuleResolution",
    "ObjectiveRuleResolver",
    "degraded_resolution",
    "not_requested_resolution",
    "objective_resolution_payload",
    "requested_objective_refs",
]
