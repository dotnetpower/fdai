"""Purpose registry - declarative catalog of well-known purpose codes.

A **purpose** names the reason a caller is reading data ("audit-review",
"incident-response", "compliance-report"). It gates
:attr:`~fdai.shared.contracts.models.PropertyDecl.purpose_binding` on
ObjectType properties (see
:mod:`fdai.shared.ontology.acl`) and lands in the projection audit
log so an auditor can reconstruct why a piece of data was surfaced.

The upstream registry is small on purpose. A fork extends it under
``fork/vocabulary/purposes.yaml`` with its own opaque purpose codes;
the loader concatenates the two roots and fails-closed on duplicates.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

_PURPOSE_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")


@dataclass(frozen=True, slots=True)
class PurposeEntry:
    id: str
    description: str
    audit_required: bool = True


@dataclass(frozen=True, slots=True)
class PurposeRegistry:
    """Immutable, order-preserving purpose catalog."""

    entries: tuple[PurposeEntry, ...]

    def ids(self) -> frozenset[str]:
        return frozenset(entry.id for entry in self.entries)

    def get(self, purpose_id: str) -> PurposeEntry:
        for entry in self.entries:
            if entry.id == purpose_id:
                return entry
        raise KeyError(purpose_id)


@dataclass(frozen=True, slots=True)
class PurposeIssue:
    key: str
    message: str


class PurposeRegistryError(ValueError):
    """Aggregate error surfaced when loading the purpose registry fails."""

    def __init__(self, issues: list[PurposeIssue]) -> None:
        self.issues = issues
        preview = "; ".join(f"{i.key}: {i.message}" for i in issues[:5])
        suffix = f" (+{len(issues) - 5} more)" if len(issues) > 5 else ""
        super().__init__(f"purpose registry validation failed: {preview}{suffix}")


class UnknownPurposeError(ValueError):
    """Raised when a caller declares a purpose that the registry does not know.

    Fail-closed: an unknown purpose MUST NOT silently pass. The
    projection layer rejects the request with this error so a typo or
    a stale UI cannot exfiltrate data under a fictional purpose.
    """

    def __init__(self, unknown: frozenset[str], known: frozenset[str]) -> None:
        self.unknown = unknown
        self.known = known
        preview = ", ".join(sorted(unknown))
        super().__init__(
            f"unknown purpose(s) declared: {preview!r} (registered: {sorted(known)!r})"
        )


def load_purpose_registry_from_mapping(raw: Mapping[str, Any]) -> PurposeRegistry:
    """Validate a raw mapping and return an immutable registry."""
    issues: list[PurposeIssue] = []
    if not isinstance(raw, Mapping):
        raise PurposeRegistryError(
            [PurposeIssue(key="<root>", message="top-level must be a mapping")]
        )
    entries_raw = raw.get("purposes")
    if not isinstance(entries_raw, list) or not entries_raw:
        raise PurposeRegistryError(
            [PurposeIssue(key="purposes", message="must be a non-empty list")]
        )

    seen: dict[str, int] = {}
    entries: list[PurposeEntry] = []
    for idx, item in enumerate(entries_raw):
        origin = f"purposes[{idx}]"
        if not isinstance(item, Mapping):
            issues.append(PurposeIssue(key=origin, message="must be a mapping"))
            continue
        entry_id = item.get("id")
        description = item.get("description")
        if not isinstance(entry_id, str) or not entry_id:
            issues.append(PurposeIssue(key=f"{origin}.id", message="required non-empty string"))
            continue
        if not _PURPOSE_PATTERN.match(entry_id):
            issues.append(
                PurposeIssue(
                    key=f"{origin}.id",
                    message=(
                        f"id {entry_id!r} MUST match kebab_snake pattern {_PURPOSE_PATTERN.pattern}"
                    ),
                )
            )
            continue
        if not isinstance(description, str) or not description.strip():
            issues.append(
                PurposeIssue(
                    key=f"{origin}.description",
                    message="required non-empty string",
                )
            )
            continue
        audit_required = item.get("audit_required", True)
        if not isinstance(audit_required, bool):
            issues.append(
                PurposeIssue(
                    key=f"{origin}.audit_required",
                    message="must be a boolean",
                )
            )
            continue
        prior = seen.get(entry_id)
        if prior is not None:
            issues.append(
                PurposeIssue(
                    key=origin,
                    message=(f"duplicate purpose id {entry_id!r} (also at purposes[{prior}])"),
                )
            )
            continue
        seen[entry_id] = idx
        entries.append(
            PurposeEntry(
                id=entry_id,
                description=description.strip(),
                audit_required=audit_required,
            )
        )

    if issues:
        raise PurposeRegistryError(issues)
    return PurposeRegistry(entries=tuple(entries))


def load_purpose_registry(path: Path) -> PurposeRegistry:
    """Load a registry YAML from disk with the same fail-closed contract."""
    with path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    return load_purpose_registry_from_mapping(raw)


def concatenate_registries(*registries: PurposeRegistry) -> PurposeRegistry:
    """Merge multiple registries, failing-closed on duplicate ids."""
    seen: dict[str, PurposeEntry] = {}
    order: list[PurposeEntry] = []
    for reg in registries:
        for entry in reg.entries:
            prior = seen.get(entry.id)
            if prior is not None and prior != entry:
                raise PurposeRegistryError(
                    [
                        PurposeIssue(
                            key=entry.id,
                            message=(
                                f"duplicate purpose id {entry.id!r} across registries "
                                "with conflicting metadata"
                            ),
                        )
                    ]
                )
            if prior is None:
                seen[entry.id] = entry
                order.append(entry)
    return PurposeRegistry(entries=tuple(order))


def validate_declared_purposes(
    declared: Iterable[str], registry: PurposeRegistry
) -> frozenset[str]:
    """Return the normalized set, or raise :class:`UnknownPurposeError`.

    Strips whitespace, drops empty values, and rejects any purpose id
    not in ``registry``. An empty declaration is allowed (the caller
    simply cannot unlock any purpose-bound property).
    """
    normalized = frozenset({p.strip() for p in declared if p and p.strip()})
    known = registry.ids()
    unknown = normalized - known
    if unknown:
        raise UnknownPurposeError(unknown=unknown, known=known)
    return normalized


__all__ = [
    "PurposeEntry",
    "PurposeIssue",
    "PurposeRegistry",
    "PurposeRegistryError",
    "UnknownPurposeError",
    "concatenate_registries",
    "load_purpose_registry",
    "load_purpose_registry_from_mapping",
    "validate_declared_purposes",
]
