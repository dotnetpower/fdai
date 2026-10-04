"""Pure validators for Hub lifecycle configuration packages.

The functions in this module validate and resolve candidate configuration bytes before
signing or import. They do not read files, contact Azure, sign packages, decrypt sealed
values, grant authority, or establish deployability beyond the returned validation result.
"""

from __future__ import annotations

import copy
import re
import unicodedata
from collections.abc import Container, Mapping
from collections.abc import Sequence as AbstractSequence
from dataclasses import dataclass
from typing import cast

_ANNOTATION_AXIS = "x-fdai-axis"
_ANNOTATION_OWNER = "x-fdai-owner"
_CONFIGURATION_AXES = frozenset(
    {
        "execution-venue",
        "deployment-environment",
        "product-surface-profile",
        "evidence-profile",
        "optional-package-preference",
        "kinetic-evidence-availability",
        "evidence-conflict-state",
        "distribution",
        "operational-safety-profile",
        "installation-path",
        "release-channel-subscription",
        "model-diversity-policy",
    }
)
_SEMVER = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
_RANGE_PART = re.compile(r"^(>=|>|<=|<|=)?(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
_ACRONYM_BOUNDARY = re.compile(r"(?<=[A-Z])(?=[A-Z][a-z])")
_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_DIGIT_BOUNDARY = re.compile(r"(?<=[A-Za-z])(?=[0-9])|(?<=[0-9])(?=[A-Za-z])")
_TOKEN_SPLIT = re.compile(r"[^A-Za-z0-9]+")
_KEY_VAULT_REF = re.compile(
    r"^kv://[A-Za-z0-9](?:[A-Za-z0-9-]{1,22}[A-Za-z0-9])/[A-Za-z0-9-]{1,127}$"
)
_KEY_VAULT_SECRET_REF = re.compile(
    r"^[A-Za-z0-9](?:[A-Za-z0-9-]{1,22}[A-Za-z0-9])/[A-Za-z0-9-]{1,127}$"
)
_DIRECT_SECRET_TOKENS = frozenset(
    {
        "credential",
        "credentials",
        "passphrase",
        "passphrases",
        "passwd",
        "password",
        "passwords",
        "pwd",
        "sas",
        "secret",
        "secrets",
        "token",
        "tokens",
    }
)
_DIRECT_SECRET_SUBSTRINGS = (
    "apikey",
    "connectionstring",
    "credential",
    "passphrase",
    "passwd",
    "password",
    "secret",
    "token",
)
_KEY_CONTEXT_TOKENS = frozenset(
    {
        "access",
        "account",
        "api",
        "client",
        "primary",
        "private",
        "secondary",
        "shared",
        "signing",
        "storage",
        "subscription",
    }
)

Version = tuple[int, int, int]


class ConfigurationValidationError(ValueError):
    """Configuration validation failure with a stable machine-readable code."""

    code: str
    path: tuple[str, ...]

    def __init__(self, code: str, path: AbstractSequence[str], message: str) -> None:
        self.code = code
        self.path = tuple(path)
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class LayerResolution:
    """Resolved configuration for one Release and Entity."""

    values: dict[str, object]
    version_range: str


@dataclass(frozen=True, slots=True)
class _Constraint:
    operator: str
    version: Version


@dataclass(frozen=True, slots=True)
class _VersionRange:
    source: str
    constraints: tuple[_Constraint, ...]
    lower: Version | None
    lower_inclusive: bool
    upper: Version | None
    upper_inclusive: bool

    def contains(self, version: Version) -> bool:
        for constraint in self.constraints:
            if constraint.operator == ">=" and version < constraint.version:
                return False
            if constraint.operator == ">" and version <= constraint.version:
                return False
            if constraint.operator == "<=" and version > constraint.version:
                return False
            if constraint.operator == "<" and version >= constraint.version:
                return False
            if constraint.operator == "=" and version != constraint.version:
                return False
        return True

    @property
    def specificity(self) -> tuple[Version, int, Version, int, int]:
        """Order overlapping ranges by the most constrained matching interval."""

        lower = self.lower if self.lower is not None else (-1, -1, -1)
        upper = (
            self.upper if self.upper is not None else (1_000_000_000, 1_000_000_000, 1_000_000_000)
        )
        return (
            lower,
            0 if self.lower_inclusive else 1,
            (-upper[0], -upper[1], -upper[2]),
            1 if not self.upper_inclusive else 0,
            len(self.constraints),
        )


def validate_release_configuration_schema(configuration_schema: Mapping[str, object]) -> None:
    """Validate Release configuration key annotations without granting authority."""

    for key, raw_entry in configuration_schema.items():
        _validate_printable_configuration_key(key, (key,))
        entry = _mapping(raw_entry, ("configuration_schema", key))
        axis = entry.get(_ANNOTATION_AXIS)
        owner = entry.get(_ANNOTATION_OWNER)
        if not isinstance(axis, str) or not axis or not isinstance(owner, str) or not owner:
            raise ConfigurationValidationError(
                "unannotated_configuration_key",
                (key,),
                f"configuration key {key!r} MUST declare x-fdai-axis and x-fdai-owner",
            )
        if _normal_token(axis) not in _CONFIGURATION_AXES:
            raise ConfigurationValidationError(
                "unsupported_configuration_axis",
                (key,),
                f"configuration key {key!r} uses an unsupported or authority axis",
            )


def resolve_configuration_layers(
    *,
    release_version: str,
    configuration_schema: Mapping[str, object],
    environment_config: Mapping[str, object],
    entity_overrides: AbstractSequence[Mapping[str, object]],
    sealed_keys: Container[str] = frozenset(),
) -> LayerResolution:
    """Resolve defaults, Environment Config, and the most-specific matching override block."""

    validate_release_configuration_schema(configuration_schema)
    version = _parse_version(release_version, ("release_version",))
    values = _defaults(configuration_schema)
    _merge_values(
        values,
        environment_config,
        schema=configuration_schema,
        sealed_keys=sealed_keys,
        path=("environment_config",),
    )
    matching: list[tuple[_VersionRange, Mapping[str, object], int]] = []
    ranges_seen: set[str] = set()
    for index, raw_block in enumerate(entity_overrides):
        block_path = ("entity_overrides", str(index))
        block = _mapping(raw_block, block_path)
        source = _text(block.get("versions"), (*block_path, "versions"))
        values_raw = _mapping(block.get("values"), (*block_path, "values"))
        version_range = _parse_range(source, (*block_path, "versions"))
        if version_range.source in ranges_seen:
            raise ConfigurationValidationError(
                "duplicate_override_range",
                (*block_path, "versions"),
                f"Entity override range {source!r} is duplicated",
            )
        ranges_seen.add(version_range.source)
        _validate_values(
            values_raw,
            schema=configuration_schema,
            sealed_keys=sealed_keys,
            path=(*block_path, "values"),
        )
        if version_range.contains(version):
            matching.append((version_range, values_raw, index))
    if not matching:
        raise ConfigurationValidationError(
            "missing_matching_override_block",
            ("entity_overrides",),
            f"Release {release_version!r} has no matching Entity override block",
        )
    selected_range, selected_values, _index = max(
        matching, key=lambda item: (item[0].specificity, -item[2])
    )
    _merge_values(
        values,
        selected_values,
        schema=configuration_schema,
        sealed_keys=sealed_keys,
        path=("entity_overrides", selected_range.source, "values"),
    )
    return LayerResolution(values=values, version_range=selected_range.source)


def validate_configuration_package_for_signing(package: Mapping[str, object]) -> None:
    """Reject literal secret values before any package signing step can run.

    Key Vault references are data-plane references and are allowed. Literal values under
    secret-bearing fields fail closed so they cannot be signed into a package.
    """

    _scan_secret_values(package, ())


def _defaults(configuration_schema: Mapping[str, object]) -> dict[str, object]:
    values: dict[str, object] = {}
    for key, raw_entry in configuration_schema.items():
        entry = _mapping(raw_entry, ("configuration_schema", key))
        if "default" in entry:
            values[key] = copy.deepcopy(entry["default"])
    return values


def _merge_values(
    target: dict[str, object],
    update: Mapping[str, object],
    *,
    schema: Mapping[str, object],
    sealed_keys: Container[str],
    path: tuple[str, ...],
) -> None:
    for key, value in update.items():
        key_path = (*path, key)
        _validate_configuration_key(key, schema=schema, sealed_keys=sealed_keys, path=key_path)
        target[key] = copy.deepcopy(value)


def _validate_values(
    values: Mapping[str, object],
    *,
    schema: Mapping[str, object],
    sealed_keys: Container[str],
    path: tuple[str, ...],
) -> None:
    for key in values:
        _validate_configuration_key(key, schema=schema, sealed_keys=sealed_keys, path=(*path, key))


def _validate_configuration_key(
    key: str,
    *,
    schema: Mapping[str, object],
    sealed_keys: Container[str],
    path: tuple[str, ...],
) -> None:
    _validate_printable_configuration_key(key, path)
    if key not in schema:
        raise ConfigurationValidationError(
            "unknown_configuration_key",
            path,
            f"configuration key {key!r} is not declared by the Release schema",
        )
    if key in sealed_keys:
        raise ConfigurationValidationError(
            "sealed_configuration_key",
            path,
            f"configuration key {key!r} belongs in the sealed section",
        )


def _scan_secret_values(value: object, path: tuple[str, ...]) -> None:
    if isinstance(value, Mapping):
        _scan_name_value_secret(value, path)
        for raw_key, raw_item in value.items():
            key = str(raw_key)
            item_path = (*path, key)
            _validate_printable_configuration_key(key, item_path)
            if _is_sensitive_key(key):
                _validate_secret_reference(raw_item, item_path, key)
                continue
            _scan_secret_values(raw_item, item_path)
        return
    if isinstance(value, AbstractSequence) and not isinstance(value, str | bytes | bytearray):
        for index, item in enumerate(value):
            _scan_secret_values(item, (*path, str(index)))


def _scan_name_value_secret(value: Mapping[object, object], path: tuple[str, ...]) -> None:
    name_key = _find_casefold_key(value, "name") or _find_casefold_key(value, "key")
    value_key = _find_casefold_key(value, "value")
    if name_key is None or value_key is None:
        return
    name = value[name_key]
    if isinstance(name, str) and _is_sensitive_key(name):
        _validate_secret_reference(value[value_key], (*path, str(value_key)), name)


def _validate_secret_reference(value: object, path: tuple[str, ...], key: str) -> None:
    if isinstance(value, str) and _KEY_VAULT_REF.fullmatch(value) is not None:
        return
    if (
        isinstance(value, Mapping)
        and set(value) == {"key_vault_secret"}
        and isinstance(value["key_vault_secret"], str)
        and _KEY_VAULT_SECRET_REF.fullmatch(value["key_vault_secret"]) is not None
    ):
        return
    raise ConfigurationValidationError(
        "literal_secret_value",
        path,
        f"field {key!r} contains a literal secret value or malformed secret reference",
    )


def _find_casefold_key(value: Mapping[object, object], target: str) -> object | None:
    for key in value:
        if isinstance(key, str) and key.casefold() == target:
            return key
    return None


def _mapping(value: object, path: tuple[str, ...]) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ConfigurationValidationError(
            "invalid_mapping",
            path,
            f"{'.'.join(path) or 'configuration'} MUST be a mapping",
        )
    return cast(Mapping[str, object], value)


def _text(value: object, path: tuple[str, ...]) -> str:
    if not isinstance(value, str) or not value:
        raise ConfigurationValidationError(
            "invalid_string",
            path,
            f"{'.'.join(path)} MUST be a non-empty string",
        )
    return value


def _normal_token(value: str) -> str:
    tokens = _tokens(value)
    return "-".join(tokens)


def _is_sensitive_key(value: str) -> bool:
    tokens_tuple = _tokens(value)
    tokens = set(tokens_tuple)
    if tokens & _DIRECT_SECRET_TOKENS:
        return True
    if any(marker in token for token in tokens_tuple for marker in _DIRECT_SECRET_SUBSTRINGS):
        return True
    if "connection" in tokens and "string" in tokens:
        return True
    return bool(tokens & {"key", "keys"} and tokens & _KEY_CONTEXT_TOKENS)


def _tokens(value: str) -> tuple[str, ...]:
    separated = _ACRONYM_BOUNDARY.sub("-", value)
    separated = _CAMEL_BOUNDARY.sub("-", separated)
    separated = _DIGIT_BOUNDARY.sub("-", separated)
    return tuple(token.lower() for token in _TOKEN_SPLIT.split(separated) if token)


def _validate_printable_configuration_key(key: str, path: tuple[str, ...]) -> None:
    normalized = unicodedata.normalize("NFKC", key)
    if normalized != key or any(unicodedata.category(char) == "Cf" for char in key):
        raise ConfigurationValidationError(
            "invalid_configuration_key",
            path,
            "configuration keys MUST be printable ASCII",
        )
    if any(ord(char) < 0x20 or ord(char) > 0x7E for char in normalized):
        raise ConfigurationValidationError(
            "invalid_configuration_key",
            path,
            "configuration keys MUST be printable ASCII",
        )


def _parse_version(value: str, path: tuple[str, ...]) -> Version:
    match = _SEMVER.fullmatch(value)
    if match is None:
        raise ConfigurationValidationError(
            "invalid_release_version",
            path,
            f"{'.'.join(path)} MUST be a semantic version",
        )
    return (int(match.group(1)), int(match.group(2)), int(match.group(3)))


def _parse_range(value: str, path: tuple[str, ...]) -> _VersionRange:
    constraints: list[_Constraint] = []
    lower: Version | None = None
    lower_inclusive = True
    upper: Version | None = None
    upper_inclusive = True
    for part in value.split():
        match = _RANGE_PART.fullmatch(part)
        if match is None:
            raise ConfigurationValidationError(
                "invalid_version_range",
                path,
                f"version range {value!r} is invalid",
            )
        operator = match.group(1) or "="
        version = (int(match.group(2)), int(match.group(3)), int(match.group(4)))
        constraints.append(_Constraint(operator=operator, version=version))
        if operator in {">=", ">"}:
            if lower is None or version > lower or (version == lower and operator == ">"):
                lower = version
                lower_inclusive = operator == ">="
        elif operator in {"<=", "<"}:
            if upper is None or version < upper or (version == upper and operator == "<"):
                upper = version
                upper_inclusive = operator == "<="
        else:
            lower = version
            upper = version
            lower_inclusive = True
            upper_inclusive = True
    if not constraints:
        raise ConfigurationValidationError(
            "invalid_version_range",
            path,
            "version range MUST contain at least one constraint",
        )
    return _VersionRange(
        source=value,
        constraints=tuple(constraints),
        lower=lower,
        lower_inclusive=lower_inclusive,
        upper=upper,
        upper_inclusive=upper_inclusive,
    )
