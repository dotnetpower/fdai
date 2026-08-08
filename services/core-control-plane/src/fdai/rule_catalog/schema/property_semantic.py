"""Reviewed shared Property semantics and deterministic value normalization."""

from __future__ import annotations

import json
import math
import unicodedata
from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from importlib import resources
from pathlib import Path
from typing import Annotated, Any

import yaml
from jsonschema import Draft202012Validator
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, ValidationError, model_validator

from fdai.shared.contracts.models import PropertyType

_SCHEMA_PACKAGE = "fdai.rule_catalog.schema"
_SCHEMA_FILE = "property_semantics.schema.json"
_SEMANTIC_ID_PATTERN = r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$"
_PROVIDER_PATTERN = r"^[a-z][a-z0-9-]{0,63}$"
_RESOURCE_TYPE_PATTERN = r"^[a-z][a-z0-9-]*(?:\.[a-z][a-z0-9-]*)*$"

ScalarValue = str | int | float | bool
CanonicalValue = str | int | bool


class PropertyNormalizationRule(StrEnum):
    STRING_TRIM = "string.trim"
    STRING_TRIM_CASEFOLD = "string.trim_casefold"
    INTEGER_STRICT = "integer.strict"
    NUMBER_DECIMAL = "number.decimal"
    BOOLEAN_STRICT = "boolean.strict"
    DATETIME_RFC3339_UTC = "datetime.rfc3339_utc"
    IDENTITY = "identity"


class PropertyAuthorityClass(StrEnum):
    CATALOG_OWNED = "catalog_owned"
    FDAI_OWNED = "fdai_owned"
    PROVIDER_OBSERVED = "provider_observed"
    LEDGER_OWNED = "ledger_owned"
    DERIVED = "derived"


class PropertyStaleBehavior(StrEnum):
    UNKNOWN = "unknown"
    LOWER_AUTONOMY = "lower_autonomy"


class PropertyRange(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    minimum: int | float | None = None
    maximum: int | float | None = None

    @model_validator(mode="after")
    def validate_bounds(self) -> PropertyRange:
        if self.minimum is None and self.maximum is None:
            raise ValueError("range MUST declare minimum or maximum")
        for value in (self.minimum, self.maximum):
            if isinstance(value, bool) or (isinstance(value, float) and not math.isfinite(value)):
                raise ValueError("range bounds MUST be finite numeric values")
        if (
            self.minimum is not None
            and self.maximum is not None
            and Decimal(str(self.minimum)) > Decimal(str(self.maximum))
        ):
            raise ValueError("range minimum MUST be at most maximum")
        return self


class PropertyAuthorityPolicy(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        populate_by_name=True,
    )

    authority_class: PropertyAuthorityClass = Field(
        validation_alias=AliasChoices("class", "authority_class"),
        serialization_alias="class",
    )
    source_identity_required: bool


class PropertyFreshnessPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    max_age_seconds: Annotated[int, Field(gt=0)]
    stale_behavior: PropertyStaleBehavior


class EquivalentProviderPath(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: Annotated[str, Field(pattern=_PROVIDER_PATTERN)]
    resource_type: Annotated[str, Field(pattern=_RESOURCE_TYPE_PATTERN)]
    path: Annotated[str, Field(min_length=1, max_length=256, pattern=r"^\S+$")]

    @property
    def property_ref(self) -> str:
        return f"property.{self.resource_type}.{self.path}"


class PropertySemantic(BaseModel):
    """One reviewed meaning shared by equivalent provider property paths."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    semantic_id: Annotated[str, Field(pattern=_SEMANTIC_ID_PATTERN)]
    value_type: PropertyType
    canonical_unit: Annotated[str, Field(min_length=1, max_length=64)] | None = None
    enum_values: tuple[ScalarValue, ...] = ()
    range: PropertyRange | None = None
    normalization_rule: PropertyNormalizationRule
    authority: PropertyAuthorityPolicy
    freshness: PropertyFreshnessPolicy
    equivalent_provider_paths: tuple[EquivalentProviderPath, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_semantic_contract(self) -> PropertySemantic:
        expected_rules = {
            PropertyType.STRING: {
                PropertyNormalizationRule.STRING_TRIM,
                PropertyNormalizationRule.STRING_TRIM_CASEFOLD,
            },
            PropertyType.INTEGER: {PropertyNormalizationRule.INTEGER_STRICT},
            PropertyType.NUMBER: {PropertyNormalizationRule.NUMBER_DECIMAL},
            PropertyType.BOOLEAN: {PropertyNormalizationRule.BOOLEAN_STRICT},
            PropertyType.DATETIME: {PropertyNormalizationRule.DATETIME_RFC3339_UTC},
            PropertyType.OBJECT: {PropertyNormalizationRule.IDENTITY},
            PropertyType.ARRAY: {PropertyNormalizationRule.IDENTITY},
        }
        if self.normalization_rule not in expected_rules[self.value_type]:
            raise ValueError("normalization rule is incompatible with value_type")
        if self.canonical_unit is not None and self.value_type not in {
            PropertyType.INTEGER,
            PropertyType.NUMBER,
        }:
            raise ValueError("canonical_unit requires an integer or number value_type")
        if self.range is not None and self.value_type not in {
            PropertyType.INTEGER,
            PropertyType.NUMBER,
        }:
            raise ValueError("range requires an integer or number value_type")
        if self.range is not None and self.enum_values:
            raise ValueError("range and enum_values are mutually exclusive")
        for enum_value in self.enum_values:
            _normalize_unchecked(enum_value, self.value_type, self.normalization_rule)
        return self

    def normalize(self, value: object) -> CanonicalValue:
        """Normalize one value and enforce this semantic's enum or range."""

        normalized = _normalize_unchecked(value, self.value_type, self.normalization_rule)
        if self.enum_values:
            canonical_enum = tuple(
                _normalize_unchecked(item, self.value_type, self.normalization_rule)
                for item in self.enum_values
            )
            if normalized not in canonical_enum:
                raise ValueError(f"value is outside enum for {self.semantic_id!r}")
        if self.range is not None:
            numeric = Decimal(str(normalized))
            if self.range.minimum is not None and numeric < Decimal(str(self.range.minimum)):
                raise ValueError(f"value is below range for {self.semantic_id!r}")
            if self.range.maximum is not None and numeric > Decimal(str(self.range.maximum)):
                raise ValueError(f"value is above range for {self.semantic_id!r}")
        return normalized


class PropertySemanticRegistry(BaseModel):
    """Validated registry that never infers equivalence for undeclared properties."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Annotated[str, Field(pattern=r"^\d+\.\d+\.\d+$")]
    version: Annotated[str, Field(pattern=r"^\d+\.\d+\.\d+$")]
    semantics: tuple[PropertySemantic, ...]

    @model_validator(mode="after")
    def validate_registry_conflicts(self) -> PropertySemanticRegistry:
        semantic_ids: set[str] = set()
        provider_paths: dict[tuple[str, str, str], str] = {}
        property_semantics: dict[str, str] = {}
        for semantic in self.semantics:
            if semantic.semantic_id in semantic_ids:
                raise ValueError(f"duplicate semantic_id {semantic.semantic_id!r}")
            semantic_ids.add(semantic.semantic_id)
            for provider_path in semantic.equivalent_provider_paths:
                path_key = (
                    provider_path.provider,
                    provider_path.resource_type,
                    provider_path.path,
                )
                prior_path_owner = provider_paths.get(path_key)
                if prior_path_owner is not None:
                    raise ValueError(
                        "duplicate provider path "
                        f"{path_key!r} in {prior_path_owner!r} and {semantic.semantic_id!r}"
                    )
                provider_paths[path_key] = semantic.semantic_id
                prior_semantic = property_semantics.get(provider_path.property_ref)
                if prior_semantic is not None and prior_semantic != semantic.semantic_id:
                    raise ValueError(
                        "equivalent property semantic conflict for "
                        f"{provider_path.property_ref!r}: "
                        f"{prior_semantic!r} != {semantic.semantic_id!r}"
                    )
                property_semantics[provider_path.property_ref] = semantic.semantic_id
        return self

    def for_property(self, property_ref: str) -> PropertySemantic | None:
        """Return reviewed semantics, or ``None`` for a legacy undeclared property."""

        for semantic in self.semantics:
            if any(
                provider_path.property_ref == property_ref
                for provider_path in semantic.equivalent_provider_paths
            ):
                return semantic
        return None

    def normalize(self, property_ref: str, value: object) -> CanonicalValue:
        """Normalize only a property with reviewed semantics."""

        semantic = self.for_property(property_ref)
        if semantic is None:
            raise KeyError(f"property has no reviewed normalized equivalence: {property_ref!r}")
        return semantic.normalize(value)


class PropertySemanticRegistryError(ValueError):
    """Raised when shared Property semantics are malformed or conflicting."""


def _normalize_unchecked(
    value: object,
    value_type: PropertyType,
    rule: PropertyNormalizationRule,
) -> CanonicalValue:
    if value_type is PropertyType.STRING:
        if not isinstance(value, str):
            raise ValueError("string property value MUST be a string")
        normalized = unicodedata.normalize("NFC", value.strip())
        if rule is PropertyNormalizationRule.STRING_TRIM_CASEFOLD:
            normalized = normalized.casefold()
        return normalized
    if value_type is PropertyType.INTEGER:
        if isinstance(value, bool):
            raise ValueError("boolean property value MUST NOT be treated as integer")
        if not isinstance(value, int):
            raise ValueError("integer property value MUST be an integer")
        return value
    if value_type is PropertyType.NUMBER:
        if isinstance(value, bool):
            raise ValueError("boolean property value MUST NOT be treated as number")
        if not isinstance(value, (str, int, float)):
            raise ValueError("number property value MUST be numeric or a numeric string")
        try:
            numeric = Decimal(str(value))
        except InvalidOperation as exc:
            raise ValueError("number property value MUST be decimal") from exc
        if not numeric.is_finite():
            raise ValueError("number property value MUST be finite")
        if numeric == 0:
            return "0"
        return format(numeric.normalize(), "f")
    if value_type is PropertyType.BOOLEAN:
        if not isinstance(value, bool):
            raise ValueError("boolean property value MUST be a boolean")
        return value
    if value_type is PropertyType.DATETIME:
        if not isinstance(value, str):
            raise ValueError("datetime property value MUST be an RFC3339 string")
        candidate = value.strip()
        if candidate.endswith("Z"):
            candidate = f"{candidate[:-1]}+00:00"
        try:
            parsed = datetime.fromisoformat(candidate)
        except ValueError as exc:
            raise ValueError("datetime property value MUST be RFC3339") from exc
        if parsed.tzinfo is None:
            raise ValueError("datetime property value MUST carry a timezone")
        result = parsed.astimezone(UTC).isoformat()
        return result.replace("+00:00", "Z")
    if rule is PropertyNormalizationRule.IDENTITY and isinstance(value, (str, int, bool)):
        return value
    raise ValueError("object and array properties cannot claim scalar normalization")


def _load_schema() -> dict[str, Any]:
    raw = resources.files(_SCHEMA_PACKAGE).joinpath(_SCHEMA_FILE).read_text(encoding="utf-8")
    return json.loads(raw)  # type: ignore[no-any-return]


def load_property_semantic_registry_from_mapping(
    raw: Mapping[str, Any],
) -> PropertySemanticRegistry:
    """Validate one registry mapping against JSON Schema and semantic invariants."""

    schema = _load_schema()
    errors = sorted(Draft202012Validator(schema).iter_errors(dict(raw)), key=lambda e: list(e.path))
    if errors:
        preview = "; ".join(
            f"{'.'.join(str(item) for item in error.absolute_path) or '<root>'}: {error.message}"
            for error in errors[:5]
        )
        raise PropertySemanticRegistryError(
            f"property-semantic registry validation failed: {preview}"
        )
    try:
        return PropertySemanticRegistry.model_validate(raw)
    except ValidationError as exc:
        raise PropertySemanticRegistryError(
            f"property-semantic registry validation failed: {exc}"
        ) from exc


def load_property_semantic_registry(path: Path) -> PropertySemanticRegistry:
    """Load one reviewed PropertySemantic registry YAML file."""

    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise PropertySemanticRegistryError(
            "property-semantic registry is unavailable or invalid YAML"
        ) from exc
    if not isinstance(raw, Mapping):
        raise PropertySemanticRegistryError("property-semantic registry root MUST be a mapping")
    return load_property_semantic_registry_from_mapping(raw)


__all__ = [
    "EquivalentProviderPath",
    "PropertyAuthorityClass",
    "PropertyAuthorityPolicy",
    "PropertyFreshnessPolicy",
    "PropertyNormalizationRule",
    "PropertyRange",
    "PropertySemantic",
    "PropertySemanticRegistry",
    "PropertySemanticRegistryError",
    "PropertyStaleBehavior",
    "load_property_semantic_registry",
    "load_property_semantic_registry_from_mapping",
]
