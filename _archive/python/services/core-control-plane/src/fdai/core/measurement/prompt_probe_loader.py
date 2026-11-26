"""Filesystem loader for recognition-probe scenarios (Wave 3 step D-2b-ii-beta).

Walks ``<catalog_root>/prompts/scenarios/`` and returns a tuple of
:class:`~fdai.core.measurement.prompt_probe_runner.RecognitionScenario`
instances the runner can consume directly. Every YAML is validated
against ``scenario.schema.json`` at load time; malformed files
aggregate into a single :class:`ScenarioLoaderError`, matching the
pattern in :mod:`fdai.core.prompts.registry` and
:mod:`fdai.core.tools.registry`.

The Wave 3 step D-2b-ii-gamma CLI runner consumes this loader; the
current step ships the loader + schema + directory so a fork can start
authoring scenarios without waiting for the CLI to land.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import yaml
from jsonschema import Draft202012Validator

from fdai.core.measurement.prompt_probe import (
    ExpectedResponse,
    RequiredField,
)
from fdai.core.measurement.prompt_probe_runner import RecognitionScenario
from fdai.core.operator_memory import OperatorScope

_SCHEMA_FILE: Final[str] = "scenario.schema.json"
_SCENARIOS_DIRNAME: Final[str] = "scenarios"
_PROMPTS_DIRNAME: Final[str] = "prompts"
_SCHEMA_DIRNAME: Final[str] = "schema"


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ScenarioLoaderIssue:
    """One aggregate-collected failure encountered while loading the tree."""

    path: str
    message: str


class ScenarioLoaderError(ValueError):
    """Raised when at least one scenario YAML fails validation.

    Mirrors :class:`fdai.core.prompts.registry.PromptRegistryError` so
    a reviewer sees every malformed scenario in one exception instead of
    fixing them one at a time.
    """

    def __init__(self, issues: list[ScenarioLoaderIssue]) -> None:
        self.issues: tuple[ScenarioLoaderIssue, ...] = tuple(issues)
        preview = "; ".join(f"{i.path}: {i.message}" for i in issues[:5])
        suffix = f" (+{len(issues) - 5} more)" if len(issues) > 5 else ""
        super().__init__(f"scenario catalog validation failed: {preview}{suffix}")


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


def load_scenarios(catalog_root: Path) -> tuple[RecognitionScenario, ...]:
    """Load every scenario YAML under ``<catalog_root>/prompts/scenarios/``.

    An empty ``catalog/`` sub-directory is legal - Wave 3 step D-2b-ii
    -beta ships with zero authored scenarios. The schema file MUST still
    be present so a broken tree fails fast at startup.

    The returned tuple is sorted by ``(id, version)`` so downstream
    consumers see a reproducible order across platforms.
    """

    scenarios_dir = catalog_root / _PROMPTS_DIRNAME / _SCENARIOS_DIRNAME
    if not scenarios_dir.is_dir():
        raise FileNotFoundError(f"scenario catalog directory not found at {scenarios_dir!s}")
    schema_path = scenarios_dir / _SCHEMA_DIRNAME / _SCHEMA_FILE
    if not schema_path.is_file():
        raise FileNotFoundError(f"scenario catalog schema not found at {schema_path!s}")
    validator = Draft202012Validator(json.loads(schema_path.read_text()))

    issues: list[ScenarioLoaderIssue] = []
    loaded: list[RecognitionScenario] = []
    for yaml_path in _iter_scenario_files(scenarios_dir):
        try:
            raw = yaml.safe_load(yaml_path.read_text())
        except yaml.YAMLError as exc:  # pragma: no cover - PyYAML detail
            issues.append(ScenarioLoaderIssue(path=str(yaml_path), message=f"invalid YAML: {exc}"))
            continue
        if not isinstance(raw, dict):
            issues.append(
                ScenarioLoaderIssue(
                    path=str(yaml_path),
                    message="top-level YAML MUST be a mapping",
                )
            )
            continue
        schema_errors = sorted(validator.iter_errors(raw), key=lambda e: list(e.absolute_path))
        if schema_errors:
            for err in schema_errors:
                pointer = "/".join(str(p) for p in err.absolute_path) or "<root>"
                issues.append(
                    ScenarioLoaderIssue(
                        path=f"{yaml_path}#{pointer}",
                        message=err.message,
                    )
                )
            continue
        filename_issue = _check_filename(yaml_path, raw)
        if filename_issue is not None:
            issues.append(filename_issue)
            continue
        loaded.append(_coerce(raw))

    if issues:
        raise ScenarioLoaderError(issues)

    loaded.sort(key=lambda s: (s.id, _capability_id_for_sort(s), _scope_ref_for_sort(s)))
    return tuple(loaded)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _iter_scenario_files(scenarios_dir: Path) -> Iterator[Path]:
    """Yield every YAML file under scenarios/ except the schema tree."""

    for path in sorted(scenarios_dir.rglob("*.yaml")):
        if _SCHEMA_DIRNAME in path.relative_to(scenarios_dir).parts:
            continue
        yield path


def _check_filename(path: Path, raw: dict[str, object]) -> ScenarioLoaderIssue | None:
    expected = f"{raw['id']}.v{raw['version']}.yaml"
    if path.name != expected:
        return ScenarioLoaderIssue(
            path=str(path),
            message=(f"file name MUST be '{expected}' to match id+version front-matter"),
        )
    return None


def _coerce(raw: dict[str, Any]) -> RecognitionScenario:
    """Turn a schema-validated mapping into a :class:`RecognitionScenario`."""

    scope_raw = raw.get("scope")
    scope: OperatorScope | None = None
    if isinstance(scope_raw, Mapping):
        scope = OperatorScope(
            resource_group_ref=str(scope_raw["resource_group_ref"]),
            resource_ref=(str(scope_raw["resource_ref"]) if "resource_ref" in scope_raw else None),
        )
    expected = _coerce_expected(raw["expected"])
    return RecognitionScenario(
        id=str(raw["id"]),
        capability_id=str(raw["capability_id"]),
        scope=scope,
        expected=expected,
    )


def _coerce_expected(raw: Mapping[str, Any]) -> ExpectedResponse:
    fields = tuple(
        RequiredField(
            name=str(field["name"]),
            expected_type=str(field["expected_type"]),
            non_empty=bool(field.get("non_empty", True)),
        )
        for field in raw["required_fields"]
    )
    expected_cited = tuple(str(rid) for rid in (raw.get("expected_cited_rule_ids") or []))
    canary_raw = raw.get("canary_tokens")
    canaries: Mapping[str, str] | None
    if isinstance(canary_raw, Mapping):
        canaries = {str(k): str(v) for k, v in canary_raw.items()}
    else:
        canaries = None
    return ExpectedResponse(
        required_fields=fields,
        expected_cited_rule_ids=expected_cited,
        canary_tokens=canaries,
    )


def _capability_id_for_sort(scenario: RecognitionScenario) -> str:
    return scenario.capability_id


def _scope_ref_for_sort(scenario: RecognitionScenario) -> str:
    """Deterministic sort key when two scenarios share the same id."""

    if scenario.scope is None:
        return ""
    return f"{scenario.scope.resource_group_ref}/{scenario.scope.resource_ref or ''}"


__all__ = [
    "ScenarioLoaderError",
    "ScenarioLoaderIssue",
    "load_scenarios",
]
