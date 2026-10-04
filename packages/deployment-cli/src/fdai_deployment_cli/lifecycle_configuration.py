"""Pure lifecycle configuration range and override resolution helpers."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, cast

from fdai_deployment_cli.runtime_release import (
    ReleaseDecision,
    _compare_release_versions,
    _release_version_parts,
)

_RANGE_TOKEN = re.compile(r"(<=|>=|<|>|=)?([^\s]+)\Z", re.ASCII)
_OPS = frozenset({"<", "<=", ">", ">=", "="})
_Operator = Literal["<", "<=", ">", ">=", "="]
_VersionParts = tuple[int, int, int, tuple[str, ...] | None]


@dataclass(frozen=True, slots=True)
class ConfigurationResolution:
    """Resolved configuration result with a stable blocking reason when denied."""

    allowed: bool
    reason_code: str
    values: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class _Constraint:
    operator: _Operator
    version: _VersionParts


def release_version_satisfies_range(*, release_version: str, version_range: str) -> ReleaseDecision:
    """Return whether a canonical Release version satisfies a simple Apollo-style range."""

    candidate = _release_version_parts(release_version)
    if candidate is None:
        return ReleaseDecision(False, "release_version_invalid", (release_version,))
    constraints = _parse_range(version_range)
    if constraints is None:
        return ReleaseDecision(False, "version_range_invalid", (version_range,))
    for constraint in constraints:
        comparison = _compare_release_versions(candidate, constraint.version)
        if constraint.operator == "=" and comparison != 0:
            return ReleaseDecision(False, "release_version_outside_range", (version_range,))
        if constraint.operator == ">" and comparison <= 0:
            return ReleaseDecision(False, "release_version_outside_range", (version_range,))
        if constraint.operator == ">=" and comparison < 0:
            return ReleaseDecision(False, "release_version_outside_range", (version_range,))
        if constraint.operator == "<" and comparison >= 0:
            return ReleaseDecision(False, "release_version_outside_range", (version_range,))
        if constraint.operator == "<=" and comparison > 0:
            return ReleaseDecision(False, "release_version_outside_range", (version_range,))
    return ReleaseDecision(True, "allowed")


def resolve_configuration_layers(
    *,
    release_version: str,
    release_defaults: Mapping[str, object],
    environment_config: Mapping[str, object],
    entity_overrides: tuple[Mapping[str, object], ...],
) -> ConfigurationResolution:
    """Resolve defaults, environment config, and the most specific matching override block."""

    if _release_version_parts(release_version) is None:
        return ConfigurationResolution(False, "release_version_invalid", {})
    matching: list[tuple[tuple[int, int], Mapping[str, object]]] = []
    for index, block in enumerate(entity_overrides):
        raw_range = block.get("version_range")
        raw_values = block.get("values")
        if not isinstance(raw_range, str) or not isinstance(raw_values, Mapping):
            return ConfigurationResolution(False, "override_block_invalid", {})
        decision = release_version_satisfies_range(
            release_version=release_version,
            version_range=raw_range,
        )
        if decision.reason_code == "version_range_invalid":
            return ConfigurationResolution(False, "version_range_invalid", {})
        if decision.allowed:
            override_values = cast(Mapping[str, object], raw_values)
            matching.append((_range_specificity(raw_range, index), override_values))
    if not matching:
        return ConfigurationResolution(False, "override_coverage_missing", {})
    _, selected_values = max(matching, key=lambda item: item[0])
    resolved_values: dict[str, object] = dict(release_defaults)
    resolved_values.update(environment_config)
    resolved_values.update(selected_values)
    return ConfigurationResolution(True, "allowed", resolved_values)


def _parse_range(value: str) -> tuple[_Constraint, ...] | None:
    stripped = value.strip()
    if not stripped or stripped == "*":
        return ()
    constraints: list[_Constraint] = []
    for token in stripped.split():
        match = _RANGE_TOKEN.fullmatch(token)
        if match is None:
            return None
        operator = match.group(1) or "="
        if operator not in _OPS:
            return None
        parts = _release_version_parts(match.group(2))
        if parts is None:
            return None
        constraints.append(_Constraint(operator=cast(_Operator, operator), version=parts))
    return tuple(constraints)


def _range_specificity(value: str, index: int) -> tuple[int, int]:
    constraints = _parse_range(value)
    assert constraints is not None
    exact = any(constraint.operator == "=" for constraint in constraints)
    bounded = sum(1 for constraint in constraints if constraint.operator != "=")
    # Later blocks break ties so a customer can replace an earlier equally specific block.
    return (100 if exact else bounded, index)
