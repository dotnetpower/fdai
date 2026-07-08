"""Schema compatibility - the evolution guard for versioned contracts.

Every event / object-type schema carries a ``schema_version`` and is
served immutably by the :class:`~fdai.shared.contracts.registry.SchemaRegistry`
(``event/1.0.0``, ``event/1.1.0``, ...). Immutability alone is not enough:
nothing today verifies that a *new* version can be safely rolled out while
old producers and consumers still run. During a rolling deploy or across
replicas at mixed versions, an incompatible schema change (a removed
field, a type flip, a newly-required field) silently breaks decoding.

This module is the missing guard: a pure, I/O-free checker that compares
two JSON Schemas and reports whether the change is additive-only
(``COMPATIBLE``) or ``BREAKING``, using the standard additive-evolution
rules (a superset of Avro/Confluent BACKWARD compatibility):

- **Breaking**: a field removed; a field's ``type`` changed; a field made
  newly ``required``; an ``enum`` narrowed (allowed values removed).
- **Compatible**: a new optional field added; ``enum`` values added; a
  required field relaxed to optional.

A catalog-validation CI gate calls :func:`check_schema_compatibility` for
each ``name/N`` -> ``name/N+1`` pair to block an incompatible bump before
it ships.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class CompatibilityLevel(StrEnum):
    COMPATIBLE = "compatible"
    BREAKING = "breaking"


@dataclass(frozen=True, slots=True)
class SchemaChange:
    path: str
    kind: str
    breaking: bool
    detail: str


@dataclass(frozen=True, slots=True)
class CompatibilityReport:
    level: CompatibilityLevel
    changes: tuple[SchemaChange, ...] = field(default_factory=tuple)

    @property
    def breaking_changes(self) -> tuple[SchemaChange, ...]:
        return tuple(c for c in self.changes if c.breaking)

    @property
    def is_compatible(self) -> bool:
        return self.level is CompatibilityLevel.COMPATIBLE


def check_schema_compatibility(
    old: Mapping[str, Any], new: Mapping[str, Any]
) -> CompatibilityReport:
    """Compare two JSON Schemas for additive-only compatibility."""
    changes = list(_diff(old, new, prefix=""))
    level = (
        CompatibilityLevel.BREAKING
        if any(c.breaking for c in changes)
        else CompatibilityLevel.COMPATIBLE
    )
    return CompatibilityReport(level=level, changes=tuple(changes))


def _diff(
    old: Mapping[str, Any], new: Mapping[str, Any], *, prefix: str
) -> list[SchemaChange]:
    changes: list[SchemaChange] = []
    old_props = _props(old)
    new_props = _props(new)
    old_required = set(_required(old))
    new_required = set(_required(new))

    # Removed fields break any consumer / stored datum referencing them.
    for name in old_props.keys() - new_props.keys():
        changes.append(
            SchemaChange(
                path=f"{prefix}{name}",
                kind="field_removed",
                breaking=True,
                detail="field removed",
            )
        )

    # A field that becomes required (and is not brand new-optional) breaks
    # old producers that omit it.
    for name in new_required - old_required:
        if name in new_props:
            changes.append(
                SchemaChange(
                    path=f"{prefix}{name}",
                    kind="required_added",
                    breaking=True,
                    detail="field is newly required",
                )
            )

    # Per-field: type change, enum narrowing, and nested recursion.
    for name in old_props.keys() & new_props.keys():
        o = old_props[name]
        n = new_props[name]
        path = f"{prefix}{name}"
        ot, nt = o.get("type"), n.get("type")
        if ot is not None and nt is not None and ot != nt:
            changes.append(
                SchemaChange(
                    path=path,
                    kind="type_changed",
                    breaking=True,
                    detail=f"type {ot!r} -> {nt!r}",
                )
            )
        oe, ne = o.get("enum"), n.get("enum")
        if isinstance(oe, list) and isinstance(ne, list):
            removed = {str(v) for v in oe} - {str(v) for v in ne}
            if removed:
                changes.append(
                    SchemaChange(
                        path=path,
                        kind="enum_narrowed",
                        breaking=True,
                        detail=f"enum values removed: {sorted(removed)}",
                    )
                )
        if _is_object(o) and _is_object(n):
            changes.extend(_diff(o, n, prefix=f"{path}."))

    return changes


def _props(schema: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    props = schema.get("properties")
    if not isinstance(props, Mapping):
        return {}
    return {k: v for k, v in props.items() if isinstance(v, Mapping)}


def _required(schema: Mapping[str, Any]) -> list[str]:
    req = schema.get("required")
    return [str(r) for r in req] if isinstance(req, list) else []


def _is_object(schema: Mapping[str, Any]) -> bool:
    return schema.get("type") == "object" or isinstance(
        schema.get("properties"), Mapping
    )


__all__ = [
    "CompatibilityLevel",
    "CompatibilityReport",
    "SchemaChange",
    "check_schema_compatibility",
]
