"""ResourceTypeRegistry loader - canonical CSP-neutral resource_type vocabulary.

Mirrors the JSON Schema at ``resource_types.schema.json`` and adds
duplicate-id detection (the schema has no ``uniqueItemProperties``
keyword in Draft 2020-12). Follows the same aggregate-issue pattern as
:mod:`fdai.rule_catalog.schema.exemption` so a reviewer sees every
problem in one shot.
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from enum import StrEnum
from importlib import resources
from typing import Annotated, Any

from jsonschema import Draft202012Validator
from pydantic import BaseModel, ConfigDict, Field

_SCHEMA_PACKAGE = "fdai.rule_catalog.schema"
_SCHEMA_FILE = "resource_types.schema.json"


class ResourceTypeCategory(StrEnum):
    COMPUTE = "compute"
    NETWORK = "network"
    STORAGE = "storage"
    DATABASE = "database"
    SECURITY = "security"
    OBSERVABILITY = "observability"
    GOVERNANCE = "governance"


class ResourceTypeEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    id: Annotated[str, Field(pattern=r"^[a-z][a-z0-9\-]*(\.[a-z][a-z0-9\-]*)*$")]
    category: ResourceTypeCategory
    description: Annotated[str, Field(min_length=1, max_length=512)]
    azure_arm_type: str | None = None
    azure_kind_tokens: tuple[str, ...] = ()
    query_terms: tuple[str, ...] = ()
    typical_parents: list[str] = Field(default_factory=list)


class ResourceTypeRegistry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Annotated[str, Field(pattern=r"^\d+\.\d+\.\d+$")]
    version: Annotated[str, Field(pattern=r"^\d+\.\d+\.\d+$")]
    category_query_terms: dict[ResourceTypeCategory, tuple[str, ...]] = Field(default_factory=dict)
    types: tuple[ResourceTypeEntry, ...]

    def ids(self) -> set[str]:
        return {t.id for t in self.types}

    def get(self, type_id: str) -> ResourceTypeEntry:
        for entry in self.types:
            if entry.id == type_id:
                return entry
        raise KeyError(type_id)

    def __iter__(self) -> Iterator[ResourceTypeEntry]:  # type: ignore[override]
        return iter(self.types)


@dataclass(frozen=True, slots=True)
class ResourceTypeIssue:
    key: str
    message: str


class ResourceTypeRegistryError(ValueError):
    def __init__(self, issues: list[ResourceTypeIssue]) -> None:
        self.issues = issues
        preview = "; ".join(f"{i.key}: {i.message}" for i in issues[:5])
        suffix = f" (+{len(issues) - 5} more)" if len(issues) > 5 else ""
        super().__init__(f"resource-type registry validation failed: {preview}{suffix}")


def _load_json_schema() -> dict[str, Any]:
    raw = resources.files(_SCHEMA_PACKAGE).joinpath(_SCHEMA_FILE).read_text(encoding="utf-8")
    return json.loads(raw)  # type: ignore[no-any-return]


def _duplicate_ids(entries: Iterable[Mapping[str, Any]]) -> list[str]:
    seen: dict[str, int] = {}
    dupes: list[str] = []
    for entry in entries:
        entry_id = entry.get("id")
        if not isinstance(entry_id, str):
            continue
        seen[entry_id] = seen.get(entry_id, 0) + 1
        if seen[entry_id] == 2:
            dupes.append(entry_id)
    return dupes


def _normalize_term(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _query_term_collisions(entries: Iterable[Mapping[str, Any]]) -> dict[str, set[str]]:
    owners: dict[str, set[str]] = {}
    for entry in entries:
        entry_id = entry.get("id")
        terms = entry.get("query_terms", ())
        if not isinstance(entry_id, str) or not isinstance(terms, list):
            continue
        for term in terms:
            if isinstance(term, str):
                owners.setdefault(_normalize_term(term), set()).add(entry_id)
    return {term: ids for term, ids in owners.items() if len(ids) > 1}


def _category_query_term_collisions(
    raw_categories: object,
    entries: Iterable[Mapping[str, Any]],
) -> list[tuple[str, str, str]]:
    if not isinstance(raw_categories, Mapping):
        return []
    category_terms = {
        str(category): {_normalize_term(term) for term in terms if isinstance(term, str)}
        for category, terms in raw_categories.items()
        if isinstance(terms, list)
    }
    collisions: list[tuple[str, str, str]] = []
    for entry in entries:
        entry_id = entry.get("id")
        category = entry.get("category")
        terms = entry.get("query_terms", ())
        if (
            not isinstance(entry_id, str)
            or not isinstance(category, str)
            or not isinstance(terms, list)
        ):
            continue
        for term in terms:
            if isinstance(term, str) and _normalize_term(term) in category_terms.get(
                category, set()
            ):
                collisions.append((category, entry_id, _normalize_term(term)))
    return sorted(collisions)


def _shared_arm_types_without_kind(entries: Iterable[Mapping[str, Any]]) -> list[str]:
    candidates: dict[str, list[tuple[str, bool]]] = {}
    for entry in entries:
        entry_id = entry.get("id")
        arm_type = entry.get("azure_arm_type")
        kind_tokens = entry.get("azure_kind_tokens", ())
        if (
            isinstance(entry_id, str)
            and isinstance(arm_type, str)
            and isinstance(kind_tokens, list)
        ):
            candidates.setdefault(arm_type.casefold(), []).append((entry_id, bool(kind_tokens)))
    return sorted(
        arm_type
        for arm_type, variants in candidates.items()
        if len(variants) > 1 and any(not has_kind for _entry_id, has_kind in variants)
    )


def _shared_arm_kind_collisions(
    entries: Iterable[Mapping[str, Any]],
) -> list[tuple[str, str, tuple[str, ...]]]:
    owners: dict[tuple[str, str], set[str]] = {}
    for entry in entries:
        entry_id = entry.get("id")
        arm_type = entry.get("azure_arm_type")
        kind_tokens = entry.get("azure_kind_tokens", ())
        if (
            not isinstance(entry_id, str)
            or not isinstance(arm_type, str)
            or not isinstance(kind_tokens, list)
        ):
            continue
        for token in kind_tokens:
            if isinstance(token, str):
                owners.setdefault((arm_type.casefold(), token.casefold()), set()).add(entry_id)
    return sorted(
        (arm_type, token, tuple(sorted(entry_ids)))
        for (arm_type, token), entry_ids in owners.items()
        if len(entry_ids) > 1
    )


def load_resource_type_registry_from_mapping(
    raw: Mapping[str, Any],
) -> ResourceTypeRegistry:
    """Validate ``raw`` against the JSON Schema + duplicate-id rule and return the model."""
    issues: list[ResourceTypeIssue] = []

    schema = _load_json_schema()
    validator = Draft202012Validator(schema)
    for err in sorted(validator.iter_errors(dict(raw)), key=lambda e: list(e.path)):
        path = ".".join(str(p) for p in err.absolute_path) or "<root>"
        issues.append(ResourceTypeIssue(key=path, message=err.message))

    types_field = raw.get("types") if isinstance(raw, Mapping) else None
    if isinstance(types_field, list):
        entries = [t for t in types_field if isinstance(t, Mapping)]
        for dup in _duplicate_ids(entries):
            issues.append(
                ResourceTypeIssue(
                    key=f"types[id={dup}]",
                    message="duplicate resource_type id",
                )
            )
        for term, owners in sorted(_query_term_collisions(entries).items()):
            issues.append(
                ResourceTypeIssue(
                    key=f"query_terms[{term}]",
                    message=f"query term is shared by resource types {sorted(owners)}",
                )
            )
        for category, entry_id, term in _category_query_term_collisions(
            raw.get("category_query_terms"), entries
        ):
            issues.append(
                ResourceTypeIssue(
                    key=f"types[id={entry_id}].query_terms[{term}]",
                    message=f"category query term {term!r} is already owned by {category}",
                )
            )
        for arm_type in _shared_arm_types_without_kind(entries):
            issues.append(
                ResourceTypeIssue(
                    key=f"azure_arm_type[{arm_type}]",
                    message="every semantic type sharing an ARM type requires azure_kind_tokens",
                )
            )
        for arm_type, token, owners in _shared_arm_kind_collisions(entries):
            issues.append(
                ResourceTypeIssue(
                    key=f"azure_arm_type[{arm_type}].azure_kind_tokens[{token}]",
                    message=f"kind token is shared by resource types {list(owners)}",
                )
            )

    if issues:
        raise ResourceTypeRegistryError(issues)

    try:
        return ResourceTypeRegistry.model_validate(raw)
    except ValueError as exc:
        errors = getattr(exc, "errors", None)
        if callable(errors):
            for e in errors():
                loc = ".".join(str(p) for p in e.get("loc", ()))
                issues.append(ResourceTypeIssue(key=loc or "<root>", message=e["msg"]))
        else:
            issues.append(ResourceTypeIssue(key="<root>", message=str(exc)))
        raise ResourceTypeRegistryError(issues) from exc


def resolve_azure_resource_type(
    registry: ResourceTypeRegistry,
    *,
    arm_type: str,
    kind: object = None,
) -> str | None:
    """Resolve one Azure row without conflating entries that share an ARM type."""

    candidates = tuple(
        entry
        for entry in registry
        if entry.azure_arm_type is not None
        and entry.azure_arm_type.casefold() == arm_type.casefold()
    )
    if len(candidates) == 1:
        return candidates[0].id
    if not candidates:
        return None
    kind_tokens = {token for token in re.split(r"[,;/\s]+", str(kind).casefold()) if token}
    matches = tuple(
        entry
        for entry in candidates
        if entry.azure_kind_tokens
        and any(token.casefold() in kind_tokens for token in entry.azure_kind_tokens)
    )
    return matches[0].id if len(matches) == 1 else None


__all__ = [
    "ResourceTypeCategory",
    "ResourceTypeEntry",
    "ResourceTypeIssue",
    "ResourceTypeRegistry",
    "ResourceTypeRegistryError",
    "load_resource_type_registry_from_mapping",
    "resolve_azure_resource_type",
]
