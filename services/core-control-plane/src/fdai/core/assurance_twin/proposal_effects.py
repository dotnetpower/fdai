"""Reviewed ActionType effect models and exact scratch-projection change derivation.

The Twin never infers an effect from an ActionType name, a free-form parameter, a
provider payload, or an IaC artifact. A typed proposal becomes a predicted change
set only through one reviewed, declared effect model for its exact ActionType id and
version, a completed what-if bound to the same proposal digest, and targets present
in the retained Inventory revision. Anything else is an explicit unavailable outcome.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from fdai.core.assurance_twin.projection import InMemoryProjection, build_baseline_projection
from fdai.core.assurance_twin.typed_proposal import (
    ACTION_TYPE_PATTERN,
    MAX_WHAT_IF_WINDOW,
    SEMVER_PATTERN,
    WHAT_IF_SOURCE_AUTHORITY,
    ProposalWhatIfResult,
    TypedActionProposal,
    WhatIfStatus,
    canonical_digest,
    is_digest,
    target_material,
)
from fdai.shared.providers.projection import InventoryDiff, ResourceRef

_PROPERTY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
_MISSING = object()
_PARAMETER = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_MAX_EFFECTS = 32


class ProposalReviewUnavailableError(ValueError):
    """The typed proposal cannot support a truthful review; never a clear verdict."""

    def __init__(self, reason_code: str) -> None:
        super().__init__(f"Assurance Twin typed proposal review is unavailable: {reason_code}")
        self.reason_code = reason_code


@dataclass(frozen=True, slots=True)
class DeclaredPropertyEffect:
    """Set one top-level target property from a declared parameter or constant."""

    property_name: str
    parameter: str | None = None
    constant_json: str | None = None

    def __post_init__(self) -> None:
        if _PROPERTY.fullmatch(self.property_name) is None:
            raise ValueError("declared effect property_name MUST be one top-level key")
        if (self.parameter is None) == (self.constant_json is None):
            raise ValueError("declared effect MUST use exactly one parameter or constant")
        if self.parameter is not None and _PARAMETER.fullmatch(self.parameter) is None:
            raise ValueError("declared effect parameter MUST be a canonical parameter name")
        if self.constant_json is not None:
            try:
                decoded = json.loads(self.constant_json)
                canonical = json.dumps(
                    decoded,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=False,
                    allow_nan=False,
                )
            except (TypeError, ValueError) as exc:
                raise ValueError("declared effect constant MUST be canonical JSON") from exc
            if canonical != self.constant_json:
                raise ValueError("declared effect constant MUST be canonical JSON")

    def value(self, parameters: Mapping[str, Any]) -> Any:
        """Return the predicted property value for exact proposal parameters."""

        if self.parameter is not None:
            return parameters[self.parameter]
        return json.loads(str(self.constant_json))


@dataclass(frozen=True, slots=True)
class ReviewedActionTypeEffect:
    """One reviewed, declared property-effect model for an exact ActionType version.

    ``review_ref`` cites the governance review that accepted the model. Parameters
    that the model does not consume MUST be declared inert; an undeclared parameter
    could carry an unmodelled effect and keeps the review unavailable.
    """

    action_type: str
    action_type_version: str
    target_resource_types: tuple[str, ...]
    property_effects: tuple[DeclaredPropertyEffect, ...]
    review_ref: str
    inert_parameters: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if (
            ACTION_TYPE_PATTERN.fullmatch(self.action_type) is None
            or SEMVER_PATTERN.fullmatch(self.action_type_version) is None
        ):
            raise ValueError("reviewed effect MUST name one exact ActionType version")
        if (
            not self.target_resource_types
            or self.target_resource_types != tuple(sorted(set(self.target_resource_types)))
            or any(not item.strip() for item in self.target_resource_types)
        ):
            raise ValueError("reviewed effect target types MUST be non-empty, unique, ordered")
        names = tuple(effect.property_name for effect in self.property_effects)
        if not names or len(names) > _MAX_EFFECTS or names != tuple(sorted(set(names))):
            raise ValueError("reviewed effect properties MUST be bounded, unique, and ordered")
        if (
            self.inert_parameters != tuple(sorted(set(self.inert_parameters)))
            or any(_PARAMETER.fullmatch(name) is None for name in self.inert_parameters)
            or set(self.inert_parameters) & self.parameter_names
        ):
            raise ValueError("reviewed effect inert parameters MUST be canonical and disjoint")
        if not self.review_ref.strip() or len(self.review_ref) > 512:
            raise ValueError("reviewed effect review_ref MUST cite its bounded review")

    @property
    def parameter_names(self) -> frozenset[str]:
        """Parameters that the declared effects consume."""

        return frozenset(
            effect.parameter for effect in self.property_effects if effect.parameter is not None
        )

    @property
    def effect_digest(self) -> str:
        """Content address of the complete reviewed declaration."""

        return canonical_digest(
            {
                "schema": "assurance-twin.reviewed-action-effect/1.0.0",
                "action_type": self.action_type,
                "action_type_version": self.action_type_version,
                "target_resource_types": list(self.target_resource_types),
                "property_effects": [
                    [effect.property_name, effect.parameter, effect.constant_json]
                    for effect in self.property_effects
                ],
                "inert_parameters": list(self.inert_parameters),
                "review_ref": self.review_ref,
            }
        )


class ReviewedEffectCatalog:
    """Immutable exact ``(ActionType id, version)`` lookup of reviewed effect models."""

    def __init__(self, effects: Iterable[ReviewedActionTypeEffect] = ()) -> None:
        catalog: dict[tuple[str, str], ReviewedActionTypeEffect] = {}
        for effect in effects:
            identity = (effect.action_type, effect.action_type_version)
            if identity in catalog:
                raise ValueError("reviewed effect catalog has an ambiguous ActionType version")
            catalog[identity] = effect
        self._effects = catalog

    def effect_for(self, action_type: str, version: str) -> ReviewedActionTypeEffect | None:
        """Return the exact reviewed model, or ``None`` when the version is unsupported."""

        return self._effects.get((action_type, version))

    def __len__(self) -> int:
        return len(self._effects)


@dataclass(frozen=True, slots=True)
class PredictedChangeSet:
    """Exact retained and predicted post-change state of a proposal's targets."""

    proposal: TypedActionProposal
    what_if: ProposalWhatIfResult
    effect: ReviewedActionTypeEffect
    inventory_revision: str
    diffs: tuple[InventoryDiff, ...]
    baseline: InMemoryProjection
    scratch: InMemoryProjection
    change_digest: str


def derive_predicted_change_set(
    *,
    proposal: TypedActionProposal,
    what_if: ProposalWhatIfResult | None,
    effect: ReviewedActionTypeEffect | None,
    projection: InMemoryProjection,
    inventory_revision: str,
    now: datetime,
) -> PredictedChangeSet:
    """Apply only the reviewed declared effect to the proposal's retained targets.

    Raises:
        ProposalReviewUnavailableError: when the effect model is absent or mismatched,
            the what-if is missing, incomplete, stale, failed, synthetic, or
            conflicting, a parameter is missing or undeclared, or a target is outside
            the retained Inventory revision or its reviewed Resource types.
    """

    if not is_digest(inventory_revision):
        raise ValueError("Assurance Twin Inventory revision MUST be a SHA-256 digest")
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Assurance Twin review clock MUST be timezone-aware")
    if effect is None:
        raise ProposalReviewUnavailableError("effect_model_unavailable")
    if (effect.action_type, effect.action_type_version) != (
        proposal.action_type,
        proposal.action_type_version,
    ):
        raise ProposalReviewUnavailableError("effect_model_mismatch")
    completed = require_completed_what_if(proposal, what_if, now)
    parameters = proposal.parameters()
    if not effect.parameter_names <= parameters.keys():
        raise ProposalReviewUnavailableError("parameter_missing")
    if not parameters.keys() <= effect.parameter_names | set(effect.inert_parameters):
        raise ProposalReviewUnavailableError("parameter_undeclared")

    baseline: list[tuple[ResourceRef, Mapping[str, Any]]] = []
    diffs: list[InventoryDiff] = []
    for target in proposal.targets:
        if target.resource_type not in effect.target_resource_types:
            raise ProposalReviewUnavailableError("target_type_unsupported")
        if not projection.contains(target):
            raise ProposalReviewUnavailableError("target_outside_revision")
        baseline.append((target, projection.properties(target)))
        diffs.append(
            InventoryDiff(
                kind="update",
                target=target,
                properties={
                    item.property_name: item.value(parameters) for item in effect.property_effects
                },
            )
        )
    retained = build_baseline_projection(baseline)
    scratch = retained
    for diff in diffs:
        scratch = scratch.apply_diff(diff)
    change_digest = canonical_digest(
        {
            "schema": "assurance-twin.predicted-change/1.0.0",
            "inventory_revision": inventory_revision,
            "proposal_digest": proposal.proposal_digest,
            "what_if_digest": completed.what_if_digest,
            "effect_digest": effect.effect_digest,
            "targets": target_material(proposal.targets),
            "changes": [dict(diff.properties) for diff in diffs],
        }
    )
    return PredictedChangeSet(
        proposal=proposal,
        what_if=completed,
        effect=effect,
        inventory_revision=inventory_revision,
        diffs=tuple(diffs),
        baseline=retained,
        scratch=scratch,
        change_digest=change_digest,
    )


def require_assessed_effect(
    change_set: PredictedChangeSet,
    declared_inputs: Iterable[tuple[ResourceRef, tuple[str, ...]]],
) -> None:
    """Require an applying Rule input for every leaf value the reviewed effect changes.

    A complete evaluation of a target proves nothing about a value that no applying
    Rule reads. The retained and predicted values of each written property are
    compared leaf by leaf; lists and scalars are leaves. A declared input covers its
    own path and every child path, never its parent or siblings, and unchanged leaves
    need no coverage. A wildcard evaluation declares no path and covers nothing.

    Raises:
        ProposalReviewUnavailableError: ``effect_unassessed`` when any changed leaf
            of any target lacks a covering declared Rule input.
    """

    inputs = {target: paths for target, paths in declared_inputs}
    for target in change_set.proposal.targets:
        paths = inputs.get(target, ())
        before = change_set.baseline.properties(target)
        after = change_set.scratch.properties(target)
        for effect in change_set.effect.property_effects:
            written = effect.property_name
            changed = _changed_leaves(
                before.get(written, _MISSING), after.get(written, _MISSING), written
            )
            if any(
                not any(leaf == path or leaf.startswith(f"{path}.") for path in paths)
                for leaf in changed
            ):
                raise ProposalReviewUnavailableError("effect_unassessed")


def _changed_leaves(before: object, after: object, path: str) -> set[str]:
    """Return every leaf path whose value differs between two JSON values."""

    if before is not _MISSING and after is not _MISSING and before == after:
        return set()
    if isinstance(before, Mapping) and isinstance(after, Mapping):
        changed: set[str] = set()
        for key in {*before, *after}:
            changed |= _changed_leaves(
                before.get(key, _MISSING), after.get(key, _MISSING), f"{path}.{key}"
            )
        return changed
    return _leaves(before, path) | _leaves(after, path)


def _leaves(value: object, path: str) -> set[str]:
    if value is _MISSING:
        return set()
    if isinstance(value, Mapping) and value:
        leaves: set[str] = set()
        for key, item in value.items():
            leaves |= _leaves(item, f"{path}.{key}")
        return leaves
    return {path}


def require_completed_what_if(
    proposal: TypedActionProposal,
    what_if: ProposalWhatIfResult | None,
    now: datetime,
) -> ProposalWhatIfResult:
    """Return the what-if only when it is complete, current, and bound to ``proposal``.

    Raises:
        ProposalReviewUnavailableError: with a stable ``what_if_*`` reason code.
    """

    if what_if is None:
        raise ProposalReviewUnavailableError("what_if_missing")
    if what_if.proposal_digest != proposal.proposal_digest:
        raise ProposalReviewUnavailableError("what_if_conflict")
    if what_if.synthetic:
        raise ProposalReviewUnavailableError("what_if_synthetic")
    if what_if.source_authority != WHAT_IF_SOURCE_AUTHORITY:
        raise ProposalReviewUnavailableError("what_if_authority_mismatch")
    if what_if.status is not WhatIfStatus.PASSED:
        raise ProposalReviewUnavailableError(f"what_if_{what_if.status.value}")
    if what_if.complete is not True or not what_if.evidence_refs:
        raise ProposalReviewUnavailableError("what_if_incomplete")
    if what_if.observed_at > now:
        raise ProposalReviewUnavailableError("what_if_from_future")
    if what_if.expires_at <= now or what_if.expires_at - what_if.observed_at > MAX_WHAT_IF_WINDOW:
        raise ProposalReviewUnavailableError("what_if_stale")
    if what_if.affected_targets != proposal.targets:
        raise ProposalReviewUnavailableError("what_if_conflict")
    return what_if


__all__ = [
    "DeclaredPropertyEffect",
    "PredictedChangeSet",
    "ProposalReviewUnavailableError",
    "ReviewedActionTypeEffect",
    "ReviewedEffectCatalog",
    "derive_predicted_change_set",
    "require_assessed_effect",
    "require_completed_what_if",
]
