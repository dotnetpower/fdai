"""ExemptionRegistry - human-override lookup at the risk-gate.

Realizes `architecture.instructions.md § Human Override`: an operator MAY
override an accepted rule via a scoped, policy-as-code override that sits
**above** the automated quality gate. Overrides are stored as data
(`rule-catalog/exemptions/*.json`, validated by
:mod:`fdai.rule_catalog.schema.exemption`) and consumed here at
runtime - the risk-gate MUST consult this Protocol before it can return
``AUTO``.

Scope shape
-----------

The design constrains override scope to a resource-group-equivalent
grouping or narrower (per architecture.instructions § Human Override).
The lookup here matches on:

- the ``rule_id`` the finding cites, and
- either the ``resource_group`` or the ``resource_ref`` on the
  candidate action.

Wider scopes are not modeled: an org-wide "disable this rule" is a rule
retirement, not an override. See ``docs/roadmap/rules-and-detection/rule-governance.md``.

Modes
-----

The initial implementation only supports the ``disabled`` mode
(overrides that suppress *execution* on the covered scope). Downgrade
and parameter-relaxation modes are future work and MUST land as an
additive schema change with their own consumer path.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class ExemptionMatch:
    """Frozen record returned when an override applies to a candidate.

    ``exemption_id`` names the artifact (``rule-catalog/exemptions/<id>.json``)
    so the audit entry ties the risk-gate decision back to the reviewed
    policy-as-code override.
    """

    exemption_id: str
    rule_id: str
    reason: str
    """Human justification recorded on the exemption artifact."""

    scope_summary: str = ""
    """Short "rg=<name>" / "resource=<ref>" text for the audit trail."""


@runtime_checkable
class ExemptionRegistry(Protocol):
    """Runtime lookup of active exemptions on an action's target.

    Implementations MUST honor state + expiry: an ``expired`` or
    ``revoked`` exemption never matches. The registry is queried per
    risk-gate evaluation, so implementations SHOULD cache and refresh
    on a short cadence (the load side is validated at ingestion by
    :func:`~fdai.rule_catalog.schema.exemption.load_exemption_from_mapping`).
    """

    def find_match(
        self,
        *,
        rule_id: str,
        resource_ref: str,
        resource_group: str | None = None,
        at: datetime | None = None,
    ) -> ExemptionMatch | None: ...


# ---------------------------------------------------------------------------
# In-memory default (upstream) - a fork replaces this with a state-store
# adapter that reads exemption artifacts.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class InMemoryExemptionRecord:
    """Minimal in-memory representation used by the default registry.

    Mirrors the fields the risk-gate cares about; the full
    :class:`~fdai.rule_catalog.schema.exemption.Exemption` model
    is authoritative but too heavy for a testing fake.
    """

    exemption_id: str
    rule_id: str
    resource_group: str | None
    resource_ref: str | None
    expires_at: datetime
    revoked_at: datetime | None = None
    justification: str = ""


class InMemoryExemptionRegistry:
    """Upstream default :class:`ExemptionRegistry` implementation.

    Not production-grade: forks replace this with a state-store adapter
    that reads the exemption artifacts. Kept in ``shared/providers/`` (not
    ``testing/``) because ``core/`` needs a working default so the
    control loop can be exercised end-to-end in dev without a fork.
    """

    def __init__(self, records: tuple[InMemoryExemptionRecord, ...] = ()) -> None:
        # Keep an internal index by rule_id for O(1) filtering; MUST NOT
        # be mutated by the risk-gate.
        self._records: dict[str, list[InMemoryExemptionRecord]] = {}
        for record in records:
            self._records.setdefault(record.rule_id, []).append(record)

    def find_match(
        self,
        *,
        rule_id: str,
        resource_ref: str,
        resource_group: str | None = None,
        at: datetime | None = None,
    ) -> ExemptionMatch | None:
        moment = at or datetime.now(tz=UTC)
        for record in self._records.get(rule_id, ()):
            if record.revoked_at is not None and record.revoked_at <= moment:
                continue
            if record.expires_at <= moment:
                continue
            # Scope match: resource_ref wins over resource_group (narrower).
            if record.resource_ref is not None:
                if record.resource_ref != resource_ref:
                    continue
                scope = f"resource={record.resource_ref}"
            elif record.resource_group is not None:
                if resource_group is None or record.resource_group != resource_group:
                    continue
                scope = f"rg={record.resource_group}"
            else:
                # An exemption without any scope narrower than the
                # subscription MUST be rejected - architectural
                # invariant. Skip such records.
                continue
            return ExemptionMatch(
                exemption_id=record.exemption_id,
                rule_id=rule_id,
                reason=record.justification or "exemption_active",
                scope_summary=scope,
            )
        return None


@dataclass(frozen=True, slots=True)
class _EmptyExemptionRegistryProbe:
    """Default no-op registry used when no exemptions are configured."""

    identifier: str = field(default="no-op")

    def find_match(
        self,
        *,
        rule_id: str,
        resource_ref: str,
        resource_group: str | None = None,
        at: datetime | None = None,
    ) -> ExemptionMatch | None:
        del rule_id, resource_ref, resource_group, at
        return None


def empty_exemption_registry() -> ExemptionRegistry:
    """Return a registry that never matches - safe default for tests."""
    return _EmptyExemptionRegistryProbe()


__all__ = [
    "ExemptionMatch",
    "ExemptionRegistry",
    "InMemoryExemptionRecord",
    "InMemoryExemptionRegistry",
    "empty_exemption_registry",
]
