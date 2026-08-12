"""Fail-closed loading for normalized discovery-only Rule records."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

from fdai.rule_catalog.schema.rule import RuleCatalogError, RuleIssue
from fdai.shared.contracts.models import Rule
from fdai.shared.contracts.registry import SchemaRegistry

_DISCOVERY_SCHEMA_VERSION = "1.0.0"


def _yaml_load(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as stream:
        return yaml.safe_load(stream)


def load_discovery_rule_catalog(
    root: Path,
    *,
    schema_registry: SchemaRegistry,
) -> tuple[Rule, ...]:
    """Load normalized Rule candidates recursively without granting active authority.

    Records must satisfy the shipped Rule 1.0.0 schema and model. The loader
    aggregates invalid records and duplicate ids, but deliberately does not
    resolve policy or ActionType execution references because discovery rows
    are candidate-only and cannot enter evaluation or action paths.
    """

    validator = Draft202012Validator(dict(schema_registry.get("rule", _DISCOVERY_SCHEMA_VERSION)))
    paths = sorted(root.rglob("*.yaml")) if root.is_dir() else []
    if not paths:
        raise RuleCatalogError(
            [RuleIssue(key=str(root), message="discovery catalog contains no Rule YAML files")]
        )

    issues: list[RuleIssue] = []
    loaded: list[Rule] = []
    seen_ids: dict[str, str] = {}
    for path in paths:
        origin = str(path.relative_to(root))
        try:
            raw = _yaml_load(path)
        except yaml.YAMLError as exc:
            issues.append(RuleIssue(key=origin, message=f"invalid YAML: {exc}"))
            continue
        if not isinstance(raw, Mapping):
            issues.append(RuleIssue(key=origin, message="top-level must be a mapping"))
            continue

        schema_errors = sorted(validator.iter_errors(dict(raw)), key=lambda error: list(error.path))
        if schema_errors:
            for error in schema_errors:
                location = ".".join(str(part) for part in error.absolute_path) or "<root>"
                issues.append(RuleIssue(key=f"{origin}:{location}", message=error.message))
            continue

        try:
            rule = Rule.model_validate(raw)
        except ValueError as exc:
            issues.append(RuleIssue(key=f"{origin}:<root>", message=str(exc)))
            continue
        if rule.schema_version != _DISCOVERY_SCHEMA_VERSION:
            issues.append(
                RuleIssue(
                    key=f"{origin}:schema_version",
                    message=(
                        "discovery rule catalog requires schema_version "
                        f"{_DISCOVERY_SCHEMA_VERSION}"
                    ),
                )
            )
            continue

        previous = seen_ids.get(rule.id)
        if previous is not None:
            issues.append(
                RuleIssue(
                    key=f"{origin}:id",
                    message=f"duplicate rule id {rule.id!r}; first loaded from {previous}",
                )
            )
            continue
        seen_ids[rule.id] = origin
        loaded.append(rule)

    if issues:
        raise RuleCatalogError(issues)
    return tuple(sorted(loaded, key=lambda rule: rule.id))


__all__ = ["load_discovery_rule_catalog"]
