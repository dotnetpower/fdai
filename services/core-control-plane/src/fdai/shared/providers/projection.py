"""``ScratchProjection`` provider Protocol - shared by Twin + Preflight.

Both Assurance Twin (whole subscription) and Deployment Preflight
(single deploy) build a read-only projection over the inventory graph,
apply a diff, and evaluate T0 rules against the result. R4 in
[implementation-plan.md](../../../../docs/roadmap/fork-and-sequencing/implementation-plan.md)
factors that primitive out so the two consumers share one kernel.

Kept as a Provider Protocol under ``shared/providers/`` so ``core/``
imports Protocols only, per the coding-conventions safety rules (see
.github/instructions/coding-conventions.instructions.md).

Read-only invariants:

- ``apply_diff`` returns a NEW :class:`ScratchProjection` instance;
  never mutates ``self``.
- ``evaluate`` executes deterministically against the projected
  state; it MUST NOT touch the underlying live inventory.
- Consumers MUST NOT hold on to a projection across event boundaries;
  a fresh projection is built per dispatch attempt.

Wave scope: skeleton (this file) + a fake in-memory implementation
under :mod:`fdai.shared.providers.local.projection` land in Wave
F/A groundwork; the real Azure-backed projection is a Wave A/P
delivery module.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable

Severity = Literal["low", "medium", "high", "critical"]


@dataclass(frozen=True)
class ResourceRef:
    """Handle onto one resource in the projection.

    CSP-neutral: ``resource_type`` is the vocabulary defined under
    ``rule-catalog/vocabulary/resource-types.yaml``; ``ref`` is an
    opaque string (ARM id, k8s object ref, ...). Neither the Twin nor
    the Preflight kernel cares which CSP produced the ref.
    """

    resource_type: str
    ref: str

    def __post_init__(self) -> None:
        if not self.resource_type or not self.ref:
            raise ValueError("ResourceRef fields MUST be non-empty")


@dataclass(frozen=True)
class InventoryDiff:
    """One or more proposed changes.

    A create carries the full ``properties`` block; an update carries
    only the delta the caller wants to apply; a delete carries an
    empty properties block. The Twin batches many diffs per PR; the
    Preflight kernel receives one diff at a time.
    """

    kind: Literal["create", "update", "delete"]
    target: ResourceRef
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Finding:
    """One rule verdict against the projection."""

    rule_id: str
    resource: ResourceRef
    severity: Severity
    reason: str
    evidence_refs: tuple[str, ...] = ()


@dataclass(frozen=True)
class RuleSet:
    """Bounded rule set the consumer wants evaluated.

    Kept opaque here - the kernel only needs a rule-id list; how the
    consumer selects them (all shipped rules / a vertical's rules /
    only the ones referenced by an ActionType) is orthogonal. The
    projection implementation resolves the id to loaded Rule objects
    via a registry it holds internally.
    """

    rule_ids: tuple[str, ...]


@runtime_checkable
class ScratchProjection(Protocol):
    """Read-only projection over the inventory graph.

    All methods MUST be pure with respect to the projection: two
    projections built from the same baseline snapshot + same diff
    sequence produce identical ``evaluate`` output.
    """

    def apply_diff(self, diff: InventoryDiff) -> ScratchProjection:
        """Return a new projection with ``diff`` applied."""
        ...

    def evaluate(self, rules: RuleSet) -> Sequence[Finding]:
        """Evaluate ``rules`` against the projected state."""
        ...


__all__ = [
    "Finding",
    "InventoryDiff",
    "ResourceRef",
    "RuleSet",
    "ScratchProjection",
    "Severity",
]
