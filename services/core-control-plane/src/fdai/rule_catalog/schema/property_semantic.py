"""Reviewed shared Property semantics and deterministic value normalization."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from importlib import resources
from pathlib import Path
from typing import Annotated, Any

import yaml
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_serializer,
    field_validator,
    model_validator,
)
from yaml.constructor import ConstructorError
from yaml.nodes import ScalarNode

from fdai.shared.contracts.models import OntologyProvenance, PropertyType

_SCHEMA_PACKAGE = "fdai.rule_catalog.schema"
_SCHEMA_FILE = "property_semantics.schema.json"
_SEMANTIC_ID_PATTERN = r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$"
_PROVIDER_PATTERN = r"^[a-z][a-z0-9-]{0,63}$"
_RESOURCE_TYPE_PATTERN = r"^[a-z][a-z0-9-]*(?:\.[a-z][a-z0-9-]*)*$"
_MAX_DECIMAL_INPUT_CHARS = 1024
_MAX_DECIMAL_COEFFICIENT_DIGITS = 256
_MAX_DECIMAL_EXPONENT = 1000
_MAX_CANONICAL_DECIMAL_CHARS = 1024
_MAX_FRESHNESS_SECONDS = 31_536_000
_UNIT_PATTERN = r"^[a-z][a-z0-9._/%-]{0,63}$"
_RFC3339_PATTERN = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}"
    r"(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$"
)

ScalarValue = str | int | float | Decimal | bool
CanonicalValue = str | int | bool


class _ExactDecimalSafeLoader(yaml.SafeLoader):
    """Safe YAML loader that preserves floating-point scalar precision."""


def _construct_yaml_decimal(
    loader: _ExactDecimalSafeLoader,
    node: ScalarNode,
) -> Decimal:
    lexeme = loader.construct_scalar(node).replace("_", "")
    special_values = {
        ".inf": "Infinity",
        "+.inf": "Infinity",
        "-.inf": "-Infinity",
        ".nan": "NaN",
    }
    try:
        return Decimal(special_values.get(lexeme.casefold(), lexeme))
    except InvalidOperation as exc:
        raise ConstructorError(
            None,
            None,
            "invalid decimal numeric scalar",
            node.start_mark,
        ) from exc


_ExactDecimalSafeLoader.add_constructor(
    "tag:yaml.org,2002:float",
    _construct_yaml_decimal,
)


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

    minimum: Decimal | None = None
    maximum: Decimal | None = None

    @field_validator("minimum", "maximum", mode="before")
    @classmethod
    def require_numeric_primitive(cls, value: object) -> object:
        if value is not None and (
            isinstance(value, bool) or not isinstance(value, (int, float, Decimal))
        ):
            raise ValueError("range bounds MUST be JSON numeric values")
        return None if value is None else _parse_decimal(value)

    @field_serializer("minimum", "maximum", when_used="json")
    def serialize_bound(self, value: Decimal | None) -> str | None:
        return None if value is None else _canonical_decimal(value)

    @model_validator(mode="after")
    def validate_bounds(self) -> PropertyRange:
        if self.minimum is None and self.maximum is None:
            raise ValueError("range MUST declare minimum or maximum")
        for value in (self.minimum, self.maximum):
            if value is not None and not value.is_finite():
                raise ValueError("range bounds MUST be finite numeric values")
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
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
    source_identity_required: Annotated[bool, Field(strict=True)]

    @model_validator(mode="after")
    def require_source_identity(self) -> PropertyAuthorityPolicy:
        if not self.source_identity_required:
            raise ValueError("property authority MUST require authenticated source identity")
        return self


class PropertyFreshnessPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    max_age_seconds: Annotated[
        int,
        Field(strict=True, gt=0, le=_MAX_FRESHNESS_SECONDS),
    ]
    stale_behavior: PropertyStaleBehavior


class EquivalentProviderPath(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: Annotated[str, Field(pattern=_PROVIDER_PATTERN)]
    resource_type: Annotated[str, Field(pattern=_RESOURCE_TYPE_PATTERN)]
    path: Annotated[str, Field(min_length=1, max_length=256, pattern=r"^\S+$")]

    @field_validator("provider", "resource_type", "path", mode="before")
    @classmethod
    def normalize_identity_parts(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        return _normalize_text(value, casefold=True)

    @property
    def property_ref(self) -> str:
        return f"property.{self.resource_type}.{self.path}"


class PropertySemantic(BaseModel):
    """One reviewed meaning shared by equivalent provider property paths."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    semantic_id: Annotated[str, Field(max_length=128, pattern=_SEMANTIC_ID_PATTERN)]
    value_type: PropertyType
    canonical_unit: (
        Annotated[
            str,
            Field(min_length=1, max_length=64, pattern=_UNIT_PATTERN),
        ]
        | None
    ) = None
    enum_values: tuple[ScalarValue, ...] = Field(default=(), max_length=256)
    range: PropertyRange | None = None
    normalization_rule: PropertyNormalizationRule
    authority: PropertyAuthorityPolicy
    freshness: PropertyFreshnessPolicy
    equivalent_provider_paths: tuple[EquivalentProviderPath, ...] = Field(
        min_length=1,
        max_length=64,
    )

    @field_validator("canonical_unit", mode="before")
    @classmethod
    def normalize_unit(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        return _normalize_text(value, casefold=True)

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
        }
        if self.value_type in {PropertyType.OBJECT, PropertyType.ARRAY}:
            raise ValueError("object and array Property semantics are not supported")
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
        if self.value_type is PropertyType.INTEGER and self.range is not None:
            if any(
                value is not None and value != value.to_integral_value()
                for value in (self.range.minimum, self.range.maximum)
            ):
                raise ValueError("integer range bounds MUST be integers")
        canonical_enum = {
            _normalize_unchecked(enum_value, self.value_type, self.normalization_rule)
            for enum_value in self.enum_values
        }
        object.__setattr__(
            self,
            "enum_values",
            tuple(sorted(canonical_enum, key=_canonical_value_sort_key)),
        )
        object.__setattr__(
            self,
            "equivalent_provider_paths",
            tuple(
                sorted(
                    self.equivalent_provider_paths,
                    key=lambda item: (item.provider, item.resource_type, item.path),
                )
            ),
        )
        return self

    def normalize(self, value: object) -> CanonicalValue:
        """Normalize one value and enforce this semantic's enum or range."""

        exact_numeric = _parse_decimal(value) if self.value_type is PropertyType.NUMBER else None
        normalized = _normalize_unchecked(value, self.value_type, self.normalization_rule)
        if self.enum_values:
            canonical_enum = tuple(
                _normalize_unchecked(item, self.value_type, self.normalization_rule)
                for item in self.enum_values
            )
            if normalized not in canonical_enum:
                raise ValueError(f"value is outside enum for {self.semantic_id!r}")
        if self.range is not None:
            numeric = exact_numeric if exact_numeric is not None else Decimal(str(normalized))
            if self.range.minimum is not None and numeric < self.range.minimum:
                raise ValueError(f"value is below range for {self.semantic_id!r}")
            if self.range.maximum is not None and numeric > self.range.maximum:
                raise ValueError(f"value is above range for {self.semantic_id!r}")
        return normalized


class PropertySemanticRegistry(BaseModel):
    """Validated registry that never infers equivalence for undeclared properties."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Annotated[str, Field(pattern=r"^\d+\.\d+\.\d+$")]
    version: Annotated[str, Field(pattern=r"^\d+\.\d+\.\d+$")]
    semantics: tuple[PropertySemantic, ...] = Field(max_length=1000)
    provenance: OntologyProvenance

    @property
    def content_digest(self) -> str:
        """Return the verified canonical registry digest."""

        return self.provenance.content_hash

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
        normalized = value.strip()
        if rule is PropertyNormalizationRule.STRING_TRIM_CASEFOLD:
            normalized = normalized.casefold()
        return unicodedata.normalize("NFC", normalized)
    if value_type is PropertyType.INTEGER:
        if isinstance(value, bool):
            raise ValueError("boolean property value MUST NOT be treated as integer")
        if not isinstance(value, int):
            raise ValueError("integer property value MUST be an integer")
        return value
    if value_type is PropertyType.NUMBER:
        return _canonical_decimal(_parse_decimal(value))
    if value_type is PropertyType.BOOLEAN:
        if not isinstance(value, bool):
            raise ValueError("boolean property value MUST be a boolean")
        return value
    if value_type is PropertyType.DATETIME:
        if not isinstance(value, str):
            raise ValueError("datetime property value MUST be an RFC3339 string")
        candidate = value
        if candidate != candidate.strip():
            raise ValueError("datetime property value MUST NOT contain surrounding whitespace")
        if _RFC3339_PATTERN.fullmatch(candidate) is None:
            raise ValueError(
                "datetime property value MUST use RFC3339 T separation, timezone, and at most "
                "six fractional digits"
            )
        if candidate.endswith("Z"):
            candidate = f"{candidate[:-1]}+00:00"
        try:
            parsed = datetime.fromisoformat(candidate)
        except ValueError as exc:
            raise ValueError("datetime property value MUST be RFC3339") from exc
        if parsed.tzinfo is None:
            raise ValueError("datetime property value MUST carry a timezone")
        try:
            utc_value = parsed.astimezone(UTC)
        except (OverflowError, ValueError) as exc:
            raise ValueError(
                "datetime property value MUST convert to UTC within the supported datetime range"
            ) from exc
        result = utc_value.strftime("%Y-%m-%dT%H:%M:%S")
        if utc_value.microsecond:
            result = f"{result}.{utc_value.microsecond:06d}".rstrip("0")
        return f"{result}Z"
    raise ValueError("object and array properties cannot claim scalar normalization")


def _normalize_text(value: str, *, casefold: bool) -> str:
    normalized = value.strip()
    if casefold:
        normalized = normalized.casefold()
    return unicodedata.normalize("NFC", normalized)


def _canonical_value_sort_key(value: CanonicalValue) -> tuple[str, str]:
    return type(value).__name__, json.dumps(value, ensure_ascii=True, separators=(",", ":"))


def _parse_decimal(value: object) -> Decimal:
    if isinstance(value, bool):
        raise ValueError("boolean property value MUST NOT be treated as number")
    if not isinstance(value, (str, int, float, Decimal)):
        raise ValueError("number property value MUST be numeric or a numeric string")
    text = str(value)
    if len(text) > _MAX_DECIMAL_INPUT_CHARS:
        raise ValueError("number property value exceeds its input limit")
    try:
        numeric = Decimal(text)
    except InvalidOperation as exc:
        raise ValueError("number property value MUST be decimal") from exc
    if not numeric.is_finite():
        raise ValueError("number property value MUST be finite")
    parts = numeric.as_tuple()
    if len(parts.digits) > _MAX_DECIMAL_COEFFICIENT_DIGITS:
        raise ValueError("number property value exceeds its coefficient limit")
    exponent = int(parts.exponent)
    if abs(exponent) > _MAX_DECIMAL_EXPONENT:
        raise ValueError("number property value exceeds its exponent limit")
    return numeric


def _canonical_decimal(numeric: Decimal) -> str:
    if numeric.is_zero():
        return "0"
    parts = numeric.as_tuple()
    digits = "".join(str(digit) for digit in parts.digits)
    exponent = int(parts.exponent)
    decimal_position = len(digits) + exponent
    if exponent >= 0:
        rendered = digits + ("0" * exponent)
    elif decimal_position > 0:
        rendered = f"{digits[:decimal_position]}.{digits[decimal_position:]}"
    else:
        rendered = f"0.{('0' * -decimal_position)}{digits}"
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    if parts.sign:
        rendered = f"-{rendered}"
    if len(rendered) > _MAX_CANONICAL_DECIMAL_CHARS:
        raise ValueError("canonical number property value exceeds its output limit")
    return rendered


def _load_schema() -> dict[str, Any]:
    raw = resources.files(_SCHEMA_PACKAGE).joinpath(_SCHEMA_FILE).read_text(encoding="utf-8")
    return json.loads(raw)  # type: ignore[no-any-return]


def _load_exact_yaml(raw: str) -> object:
    loader = _ExactDecimalSafeLoader(raw)
    try:
        return loader.get_single_data()
    finally:
        loader.dispose()  # type: ignore[no-untyped-call]


def _schema_validation_payload(registry: PropertySemanticRegistry) -> dict[str, Any]:
    payload = registry.model_dump(
        mode="json",
        by_alias=True,
        exclude_defaults=True,
        exclude_none=True,
    )
    semantics_payload = payload["semantics"]
    for semantic_payload, semantic in zip(semantics_payload, registry.semantics, strict=True):
        if semantic.range is None:
            continue
        range_payload = semantic_payload["range"]
        for field_name in ("minimum", "maximum"):
            value = getattr(semantic.range, field_name)
            if value is None:
                continue
            range_payload[field_name] = (
                int(value) if semantic.value_type is PropertyType.INTEGER else value
            )
    return payload


def property_semantic_registry_content_hash(registry: PropertySemanticRegistry) -> str:
    """Hash canonical registry content while excluding its provenance envelope."""

    payload = registry.model_dump(
        mode="json",
        by_alias=True,
        exclude={"provenance"},
        exclude_defaults=True,
        exclude_none=True,
    )
    canonical = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(canonical).hexdigest()}"


def empty_property_semantic_registry() -> PropertySemanticRegistry:
    """Return the explicit legacy registry used when the catalog file is absent."""

    registry = PropertySemanticRegistry(
        schema_version="1.0.0",
        version="0.0.0",
        semantics=(),
        provenance=OntologyProvenance(
            source_url="urn:fdai:property-semantics:legacy-empty",
            resolved_ref="property-semantics:legacy-empty@0.0.0",
            content_hash=f"sha256:{'0' * 64}",
            license="Apache-2.0",
            retrieved_at=datetime(1970, 1, 1, tzinfo=UTC),
        ),
    )
    provenance = registry.provenance.model_copy(
        update={"content_hash": property_semantic_registry_content_hash(registry)}
    )
    return registry.model_copy(update={"provenance": provenance})


def load_property_semantic_registry_from_mapping(
    raw: Mapping[str, Any],
) -> PropertySemanticRegistry:
    """Validate one registry mapping against JSON Schema and semantic invariants."""

    try:
        registry = PropertySemanticRegistry.model_validate(raw)
    except ValidationError as exc:
        raise PropertySemanticRegistryError(
            f"property-semantic registry validation failed: {exc}"
        ) from exc
    schema = _load_schema()
    normalized = _schema_validation_payload(registry)
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(normalized),
        key=lambda error: list(error.path),
    )
    if errors:
        preview = "; ".join(
            f"{'.'.join(str(item) for item in error.absolute_path) or '<root>'}: {error.message}"
            for error in errors[:5]
        )
        raise PropertySemanticRegistryError(
            f"property-semantic registry validation failed: {preview}"
        )
    expected_digest = property_semantic_registry_content_hash(registry)
    if registry.provenance.content_hash != expected_digest:
        raise PropertySemanticRegistryError(
            "property-semantic registry validation failed: provenance.content_hash mismatch: "
            f"expected {expected_digest}, got {registry.provenance.content_hash}"
        )
    return registry


def load_property_semantic_registry(path: Path) -> PropertySemanticRegistry:
    """Load one reviewed PropertySemantic registry YAML file."""

    try:
        raw = _load_exact_yaml(path.read_text(encoding="utf-8"))
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
    "empty_property_semantic_registry",
    "load_property_semantic_registry",
    "load_property_semantic_registry_from_mapping",
    "property_semantic_registry_content_hash",
]
