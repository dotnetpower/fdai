"""Governance override - the human control surface above the automated gate.

Realizes "Human Override" (architecture.instructions.md): an operator MAY
narrow, downgrade, or disable an accepted rule at a resource-group-equivalent
scope or narrower, without editing the rule
(rule-governance.md "Overrides"). Complements, never replaces, an exemption:
an exemption is time-boxed and finding-scoped; an override is a scoped policy
stance that MAY be permanent.

Pure and I/O-free: :meth:`Override.covers` is a deterministic predicate over a
:class:`~fdai.rule_catalog.schema.scope.ResourceContext` (mirrors
:meth:`fdai.rule_catalog.schema.assignment.Assignment.applies_to`), so the
loader, the CI gate, and T0 runtime consumption share one source of truth.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from fdai.rule_catalog.schema.provenance import Provenance
from fdai.rule_catalog.schema.scope import ResourceContext, ScopeLevel, ScopeRef
from fdai.shared.contracts.models import Severity


class OverrideMode(StrEnum):
    """Permitted override modes (rule-governance.md "Overrides § Rules (MUST)").

    Any other broadening is rejected - these three are exhaustive.
    """

    DISABLED = "disabled"
    SEVERITY_DOWNGRADE = "severity-downgrade"
    PARAMETER_RELAXATION = "parameter-relaxation"


@dataclass(frozen=True, slots=True)
class Override:
    """A scoped, audited policy stance narrowing/downgrading/disabling a rule.

    ``scope`` MUST resolve to :attr:`~fdai.rule_catalog.schema.scope.ScopeLevel.RESOURCE_GROUP`
    or narrower - an organization/account-wide override is rejected here (that
    is a rule *retirement*, which goes through the catalog pipeline instead).
    ``expires_at`` is optional (unlike an exemption, an override MAY be
    permanent); when set, :meth:`covers` treats a past ``expires_at`` as no
    longer applying so a forgotten cleanup PR cannot let a stale override
    silently outlive its own stated boundary.
    """

    id: str
    target_rule: str
    scope: ScopeRef
    mode: OverrideMode
    justification: str
    requested_by: str
    approver: str
    severity_downgrade_to: Severity | None = None
    parameter_overrides: Mapping[str, str] = field(default_factory=dict)
    expires_at: datetime | None = None
    provenance: Provenance | None = None
    version: str | None = None

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise ValueError("Override.id MUST be non-empty")
        if not self.target_rule.strip():
            raise ValueError("Override.target_rule MUST be non-empty")
        if self.scope.level < ScopeLevel.RESOURCE_GROUP:
            raise ValueError(
                "Override.scope MUST be resource-group-equivalent or narrower "
                "(architecture.instructions.md 'Human Override') - got "
                f"{self.scope.level.name.lower()}-level scope {self.scope.render()!r}; "
                "disabling a rule org/account-wide is a rule retirement, not an override"
            )
        if len(self.justification.strip()) < 20:
            raise ValueError("Override.justification MUST be at least 20 characters")
        if not self.requested_by.strip() or not self.approver.strip():
            raise ValueError("Override.requested_by and approver MUST be non-empty")
        if self.requested_by == self.approver:
            raise ValueError(
                "Override.requested_by MUST differ from approver (no self-override, "
                "mirrors the exemption requester/approver rule)"
            )
        if self.mode is OverrideMode.SEVERITY_DOWNGRADE:
            if self.severity_downgrade_to is None:
                raise ValueError("mode=severity-downgrade MUST set severity_downgrade_to")
        elif self.severity_downgrade_to is not None:
            raise ValueError("severity_downgrade_to is only valid with mode=severity-downgrade")
        if self.mode is OverrideMode.PARAMETER_RELAXATION:
            if not self.parameter_overrides:
                raise ValueError(
                    "mode=parameter-relaxation MUST set at least one parameter_overrides entry"
                )
        elif self.parameter_overrides:
            raise ValueError("parameter_overrides is only valid with mode=parameter-relaxation")
        if self.expires_at is not None and self.expires_at.tzinfo is None:
            raise ValueError("Override.expires_at MUST be timezone-aware when set")

    def covers(self, ctx: ResourceContext, *, at: datetime) -> bool:
        """True when this override applies to ``ctx`` at ``at``.

        ``at`` MUST be timezone-aware; a naive clock can never be compared
        against ``expires_at`` unambiguously, so this raises rather than
        silently treating the override as always (or never) active.
        """
        if at.tzinfo is None:
            raise ValueError("Override.covers clock MUST be timezone-aware")
        if self.expires_at is not None and self.expires_at <= at:
            return False
        return self.scope.covers(ctx)


__all__ = ["Override", "OverrideMode", "resolve_override"]


def resolve_override(
    *,
    overrides: Sequence[Override],
    ctx: ResourceContext,
    rule_id: str,
    at: datetime,
) -> Override | None:
    """Return the override that governs ``rule_id`` on ``ctx`` at ``at``, if any.

    rule-governance.md "Overrides § Precedence": an override wins over an
    assignment's effect *on the scope it covers*; outside its scope, the
    standard assignment scope-precedence applies unchanged. The catalog load
    boundary already rejects two overrides on the exact same (rule, scope)
    pair, but a resource-level override and a resource-group-level override
    for the same rule MAY legitimately coexist over a shared resource (the
    resource-level one narrower); the **narrowest covering** override wins,
    mirroring :func:`fdai.rule_catalog.schema.scope.most_specific`. Returns
    ``None`` when no override covers the resource for that rule - the caller
    then falls through to the ordinary assignment resolution.
    """
    matching = [
        override
        for override in overrides
        if override.target_rule == rule_id and override.covers(ctx, at=at)
    ]
    if not matching:
        return None
    return max(matching, key=lambda override: override.scope.level)
