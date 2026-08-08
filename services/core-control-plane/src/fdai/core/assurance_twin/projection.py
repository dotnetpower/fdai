"""In-memory :class:`ScratchProjection` implementation.

The upstream projection primitive shared by Twin and Preflight. Real
projections (Azure Resource Graph-backed for Twin, Terraform-plan-
backed for Preflight) implement the same Protocol; this in-memory
version is what the composition root binds on Day 1 and what tests
use to prove diff semantics without a cloud dependency.

Invariants (property-tested):

- ``apply_diff`` returns a NEW instance; ``self`` is unchanged.
- Sequential diffs compose: ``p.apply_diff(a).apply_diff(b)`` yields
  the same state as one merged diff with equivalent effects for
  create + update; a delete short-circuits later updates on the same
  ref (they raise).
- ``evaluate`` is pure over the projected state: no I/O, no random
  order.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from fdai.shared.providers.projection import (
    Finding,
    InventoryDiff,
    ResourceRef,
    RuleSet,
    ScratchProjection,
)


@dataclass(frozen=True)
class _ProjectedResource:
    ref: ResourceRef
    properties: Mapping[str, Any]


# Signature of a rule evaluator that maps (projected state) -> findings.
# The Twin binds one that dispatches to the shipped T0 engine; tests bind
# their own simple predicates.
Evaluator = Callable[
    ["InMemoryProjection", RuleSet],
    Sequence[Finding],
]


@dataclass(frozen=True)
class InMemoryProjection(ScratchProjection):
    """Frozen snapshot of resources + optional evaluator binding.

    Kept as a ``frozen=True`` dataclass so :meth:`apply_diff` MUST
    produce a new instance; the type system prevents in-place mutation
    and the property test in :mod:`tests.assurance_twin.test_projection`
    proves the invariant.
    """

    resources: Mapping[ResourceRef, _ProjectedResource] = field(default_factory=dict)
    evaluator: Evaluator | None = None

    def apply_diff(self, diff: InventoryDiff) -> InMemoryProjection:
        current = dict(self.resources)
        target = diff.target
        if diff.kind == "create":
            if target in current:
                raise ValueError(f"create on already-present resource {target!r}")
            current[target] = _ProjectedResource(ref=target, properties=dict(diff.properties))
        elif diff.kind == "update":
            existing = current.get(target)
            if existing is None:
                raise KeyError(f"update on missing resource {target!r}")
            merged = dict(existing.properties)
            merged.update(diff.properties)
            current[target] = _ProjectedResource(ref=target, properties=merged)
        elif diff.kind == "delete":
            if target not in current:
                raise KeyError(f"delete on missing resource {target!r}")
            current.pop(target)
        else:  # pragma: no cover - dataclass restricts kind values
            raise ValueError(f"unknown diff kind {diff.kind!r}")
        return InMemoryProjection(resources=current, evaluator=self.evaluator)

    def evaluate(self, rules: RuleSet) -> Sequence[Finding]:
        if self.evaluator is None:
            # A projection with no bound evaluator is legal but yields
            # no findings (the caller is exercising diff semantics
            # only). The Twin binds a real evaluator at composition.
            return ()
        result = self.evaluator(self, rules)
        return tuple(result)

    def properties(self, ref: ResourceRef) -> Mapping[str, Any]:
        """Convenience accessor for the evaluator + tests."""

        projected = self.resources.get(ref)
        if projected is None:
            raise KeyError(f"no resource with ref {ref!r} in projection")
        return dict(projected.properties)

    def contains(self, ref: ResourceRef) -> bool:
        return ref in self.resources


def build_baseline_projection(
    baseline: Iterable[tuple[ResourceRef, Mapping[str, Any]]],
    *,
    evaluator: Evaluator | None = None,
) -> InMemoryProjection:
    """Build a fresh projection from an iterable of (ref, properties).

    Used by tests and by the fake Twin composition. Real Twin instances
    stream from the Inventory provider and materialise via this same
    entry point.
    """

    resources: dict[ResourceRef, _ProjectedResource] = {}
    for ref, props in baseline:
        if ref in resources:
            raise ValueError(f"duplicate baseline ref {ref!r}")
        resources[ref] = _ProjectedResource(ref=ref, properties=dict(props))
    return InMemoryProjection(resources=resources, evaluator=evaluator)


__all__ = [
    "Evaluator",
    "InMemoryProjection",
    "build_baseline_projection",
]
