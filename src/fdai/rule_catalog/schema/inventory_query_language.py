"""Schema-validated natural-language vocabulary for inventory queries."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from enum import Enum, StrEnum
from importlib import resources
from types import MappingProxyType
from typing import Annotated, Any, cast

from jsonschema import Draft202012Validator
from pydantic import BaseModel, ConfigDict, Field

_SCHEMA_PACKAGE = "fdai.rule_catalog.schema"
_SCHEMA_FILE = "inventory_query_language.schema.json"
QueryValueList = Annotated[
    tuple[Annotated[str, Field(min_length=1, max_length=128, pattern=r".*\S.*")], ...],
    Field(min_length=1, max_length=16),
]


class QueryTerms(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    terms: tuple[Annotated[str, Field(min_length=1, max_length=128)], ...]


class QueryEvidenceAuthority(StrEnum):
    CURRENT_INVENTORY = "current_inventory"
    SUBSCRIPTION_HEALTH = "subscription_health"


class QueryValues(QueryTerms):
    values: QueryValueList
    description: Annotated[str, Field(max_length=512)] = ""
    examples: tuple[Annotated[str, Field(min_length=1, max_length=256)], ...] = ()
    evidence_authority: QueryEvidenceAuthority = QueryEvidenceAuthority.CURRENT_INVENTORY
    labels: Mapping[str, Annotated[str, Field(min_length=1, max_length=128)]] = Field(
        default_factory=dict
    )
    preserve_values: bool = False
    suppresses: tuple[str, ...] = ()
    category_values: Mapping[str, QueryValueList] = Field(default_factory=dict)
    preserve_categories: tuple[str, ...] = ()

    def model_post_init(self, __context: Any) -> None:
        object.__setattr__(self, "labels", MappingProxyType(dict(self.labels)))
        object.__setattr__(self, "category_values", MappingProxyType(dict(self.category_values)))


class TimeUnit(QueryTerms):
    multiplier_seconds: Annotated[int, Field(ge=1, le=604800)]


class InventoryQueryLanguageRegistry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Annotated[str, Field(pattern=r"^\d+\.\d+\.\d+$")]
    version: Annotated[str, Field(pattern=r"^\d+\.\d+\.\d+$")]
    default_scope: str
    default_activity_lookback_seconds: Annotated[int, Field(ge=3600, le=2592000)]
    current_requires_fresh: bool
    suffixes: tuple[str, ...]
    signals: Mapping[str, QueryTerms]
    query_kinds: Mapping[str, QueryTerms]
    groupings: Mapping[str, QueryTerms]
    projections: Mapping[str, QueryTerms]
    scopes: Mapping[str, QueryTerms]
    states: Mapping[str, QueryValues]
    operations: Mapping[str, QueryValues]
    time_units: Mapping[str, TimeUnit]

    def model_post_init(self, __context: Any) -> None:
        state_ids = set(self.states)
        for state_id, state in self.states.items():
            if state_id in state.suppresses or any(
                suppressed not in state_ids for suppressed in state.suppresses
            ):
                raise ValueError(f"state {state_id} has invalid suppression targets")
        for field in (
            "signals",
            "query_kinds",
            "groupings",
            "projections",
            "scopes",
            "states",
            "operations",
            "time_units",
        ):
            object.__setattr__(self, field, MappingProxyType(dict(getattr(self, field))))


class InventoryQueryLanguageRegistryError(ValueError):
    """Raised when the inventory query language catalog is invalid."""


def _schema() -> dict[str, Any]:
    return cast(
        dict[str, Any],
        json.loads(
            resources.files(_SCHEMA_PACKAGE).joinpath(_SCHEMA_FILE).read_text(encoding="utf-8")
        ),
    )


def load_inventory_query_language_from_mapping(
    raw: Mapping[str, Any],
) -> InventoryQueryLanguageRegistry:
    """Validate and freeze one inventory query language catalog."""

    schema = _schema()
    errors = sorted(
        Draft202012Validator(schema).iter_errors(dict(raw)), key=lambda error: list(error.path)
    )
    if errors:
        preview = "; ".join(
            f"{'.'.join(str(item) for item in error.absolute_path) or '<root>'}: {error.message}"
            for error in errors[:5]
        )
        raise InventoryQueryLanguageRegistryError(preview)
    try:
        return InventoryQueryLanguageRegistry.model_validate(raw)
    except ValueError as exc:
        raise InventoryQueryLanguageRegistryError(str(exc)) from exc


def inventory_query_language_digest(registry: InventoryQueryLanguageRegistry) -> str:
    """Return one replay-stable digest over the complete frozen registry."""

    encoded = json.dumps(
        _canonical_json_value(registry),
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _canonical_json_value(value: object) -> object:
    if isinstance(value, BaseModel):
        return {
            field: _canonical_json_value(getattr(value, field))
            for field in type(value).model_fields
        }
    if isinstance(value, Mapping):
        return {str(key): _canonical_json_value(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [_canonical_json_value(item) for item in value]
    if isinstance(value, Enum):
        return value.value
    return value


__all__ = [
    "InventoryQueryLanguageRegistry",
    "InventoryQueryLanguageRegistryError",
    "QueryEvidenceAuthority",
    "QueryTerms",
    "QueryValues",
    "TimeUnit",
    "inventory_query_language_digest",
    "load_inventory_query_language_from_mapping",
]
