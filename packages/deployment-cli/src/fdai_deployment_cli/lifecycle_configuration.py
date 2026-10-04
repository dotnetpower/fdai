"""Pure validators for Hub lifecycle configuration packages.

The functions in this module validate and resolve candidate configuration bytes before
signing or import. They do not read files, contact Azure, sign packages, decrypt sealed
values, grant authority, or establish deployability beyond the returned validation result.
"""

from __future__ import annotations

import copy
import re
from collections.abc import Container, Mapping, Sequence
from dataclasses import dataclass
from typing import cast

_ANNOTATION_AXIS = "x-fdai-axis"
_ANNOTATION_OWNER = "x-fdai-owner"
_AUTHORITY_AXES = frozenset(
    {
        "action-lifecycle",
        "action_lifecycle",
        "approval-profile",
        "approval_profile",
        "authorization-policy",
        "authorization_policy",
        "standing-authority",
        "standing_authority",
        "authority",
    }
)
_SEMVER = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
_RANGE_PART = re.compile(r"^(>=|>|<=|<|=)?(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
_SENSITIVE_KEY = re.compile(
    r"(^|[_-])(api[_-]?key|credential|password|private[_-]?key|secret|token)($|[_-])",
    re.IGNORECASE,
)

Version = tuple[int, int, int]


class ConfigurationValidationError(ValueError):
    """Configuration validation failure with a stable machine-readable code."""

    code: str
    path: tuple[str, ...]

    def __init__(self, code: str, path: Sequence[str], message: str) -> None:
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
        entry = _mapping(raw_entry, ("configuration_schema", key))
        axis = entry.get(_ANNOTATION_AXIS)
        owner = entry.get(_ANNOTATION_OWNER)
        if not isinstance(axis, str) or not axis or not isinstance(owner, str) or not owner:
            raise ConfigurationValidationError(
                "unannotated_configuration_key",
                (key,),
                f"configuration key {key!r} MUST declare x-fdai-axis and x-fdai-owner",
            )
        if _normal_token(axis) in _AUTHORITY_AXES:
            raise ConfigurationValidationError(
                "authority_axis_configuration_key",
                (key,),
                f"configuration key {key!r} belongs to an authority axis",
            )


def resolve_configuration_layers(
    *,
    release_version: str,
    configuration_schema: Mapping[str, object],
    environment_config: Mapping[str, object],
    entity_overrides: Sequence[Mapping[str, object]],
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
    for index, raw_block in enumerate(entity_overrides):
        block_path = ("entity_overrides", str(index))
        block = _mapping(raw_block, block_path)
        source = _text(block.get("versions"), (*block_path, "versions"))
        values_raw = _mapping(block.get("values"), (*block_path, "values"))
        version_range = _parse_range(source, (*block_path, "versions"))
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
        if key not in schema:
            raise ConfigurationValidationError(
                "unknown_configuration_key",
                key_path,
                f"configuration key {key!r} is not declared by the Release schema",
            )
        if key in sealed_keys:
            raise ConfigurationValidationError(
                "sealed_configuration_key",
                key_path,
                f"configuration key {key!r} belongs in the sealed section",
            )
        target[key] = copy.deepcopy(value)


def _scan_secret_values(value: object, path: tuple[str, ...]) -> None:
    if isinstance(value, Mapping):
        for raw_key, raw_item in value.items():
            key = str(raw_key)
            item_path = (*path, key)
            if _SENSITIVE_KEY.search(key) is not None:
                if _is_allowed_secret_reference(key, raw_item):
                    continue
                if isinstance(raw_item, str):
                    raise ConfigurationValidationError(
                        "literal_secret_value",
                        item_path,
                        f"field {key!r} contains a literal secret value",
                    )
            _scan_secret_values(raw_item, item_path)
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _scan_secret_values(item, (*path, str(index)))


def _is_allowed_secret_reference(key: str, value: object) -> bool:
    if isinstance(value, str):
        return key.endswith("_ref") and value.startswith(("kv://", "keyvault://"))
    if isinstance(value, Mapping):
        return set(value) == {"key_vault_secret"} and isinstance(value["key_vault_secret"], str)
    return False


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
    return value.strip().lower()


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
