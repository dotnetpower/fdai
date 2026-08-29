"""Governance-level parameter-relaxation bounds policy.

Closes the "close design decisions safely" requirement from
rule-governance.md "Overrides § Rules (MUST)" and "Open Decisions": an
override's ``mode: parameter-relaxation`` MUST widen a threshold only within a
range a rule's own schema does not yet declare (rule-governance.md Open
Decisions still leaves the rule-schema-declared bound as future work), so the
safe interim design is a **separately reviewed governance-level allowlist**:
one reviewed YAML file naming, per rule, exactly which parameter keys an
override may touch and the numeric/enumerated bound each key accepts. A key
absent from the policy - or a value outside its declared bound - fails the
governance catalog load closed (see
:func:`fdai.rule_catalog.schema.governance_catalog.load_governance_catalog`).
There is no runtime HIL fallback for this: an override that violates the
policy never reaches a resource, because the catalog that would carry it
never loads.

Pure and I/O-free at the mapping boundary (the caller reads the YAML file and
passes the parsed mapping).
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class ParameterBound:
    """The allowed shape for one relaxable parameter key.

    Either a numeric ``[minimum, maximum]`` range (either bound optional) or a
    fixed ``allowed_values`` set - never both, and never neither (an
    unconstrained key would defeat the point of a reviewed bound).
    """

    key: str
    minimum: float | None = None
    maximum: float | None = None
    allowed_values: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        if not self.key.strip():
            raise ValueError("ParameterBound.key MUST be non-empty")
        has_range = self.minimum is not None or self.maximum is not None
        if has_range and self.allowed_values:
            raise ValueError(
                f"ParameterBound {self.key!r} MUST NOT combine a numeric range with allowed_values"
            )
        if not has_range and not self.allowed_values:
            raise ValueError(
                f"ParameterBound {self.key!r} MUST declare a numeric range or allowed_values"
            )
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise ValueError(f"ParameterBound {self.key!r}: minimum MUST NOT exceed maximum")

    def allows(self, value: str) -> bool:
        """True when ``value`` (the override's raw string parameter value) is in bound."""
        if self.allowed_values:
            return value in self.allowed_values
        try:
            numeric = float(value)
        except ValueError:
            return False
        if not math.isfinite(numeric):
            return False
        if self.minimum is not None and numeric < self.minimum:
            return False
        if self.maximum is not None and numeric > self.maximum:
            return False
        return True


@dataclass(frozen=True, slots=True)
class ParameterRelaxationPolicy:
    """Every parameter key one rule permits an override to relax."""

    rule_id: str
    bounds: Mapping[str, ParameterBound] = field(default_factory=dict)

    def allows(self, key: str, value: str) -> bool:
        """True when ``key`` is allow-listed for this rule and ``value`` is in bound."""
        bound = self.bounds.get(key)
        return bound is not None and bound.allows(value)


def parameter_relaxation_policies_from_mapping(
    raw: Mapping[str, Any],
) -> dict[str, ParameterRelaxationPolicy]:
    """Build ``{rule_id: ParameterRelaxationPolicy}`` from the parsed YAML mapping.

    Expected shape::

        rules:
          postgresql-server.point-in-time-restore:
            min_retention_days: {minimum: 1, maximum: 30}
            mode: {allowed_values: [full, incremental]}

    Raises :class:`ValueError` (aggregated by the caller into the governance
    load boundary) on a malformed shape.
    """
    rules_raw = raw.get("rules", {})
    if not isinstance(rules_raw, Mapping):
        raise ValueError("override-parameter-bounds.yaml 'rules' MUST be a mapping")
    policies: dict[str, ParameterRelaxationPolicy] = {}
    for rule_id, bounds_raw in rules_raw.items():
        if not isinstance(bounds_raw, Mapping):
            raise ValueError(f"override-parameter-bounds.yaml rule {rule_id!r} MUST be a mapping")
        bounds: dict[str, ParameterBound] = {}
        for key, bound_raw in bounds_raw.items():
            if not isinstance(bound_raw, Mapping):
                raise ValueError(
                    f"override-parameter-bounds.yaml rule {rule_id!r} key {key!r} MUST be a mapping"
                )
            allowed = bound_raw.get("allowed_values")
            bounds[key] = ParameterBound(
                key=key,
                minimum=bound_raw.get("minimum"),
                maximum=bound_raw.get("maximum"),
                allowed_values=frozenset(str(v) for v in allowed) if allowed else frozenset(),
            )
        policies[rule_id] = ParameterRelaxationPolicy(rule_id=rule_id, bounds=bounds)
    return policies


__all__ = [
    "ParameterBound",
    "ParameterRelaxationPolicy",
    "parameter_relaxation_policies_from_mapping",
]
