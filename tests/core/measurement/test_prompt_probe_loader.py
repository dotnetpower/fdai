"""Unit tests for :mod:`aiopspilot.core.measurement.prompt_probe_loader`."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from aiopspilot.core.measurement.prompt_probe_loader import (
    ScenarioLoaderError,
    load_scenarios,
)
from aiopspilot.core.operator_memory import OperatorScope

_SCHEMA_PATH = (
    Path(__file__).resolve().parents[3]
    / "rule-catalog"
    / "prompts"
    / "scenarios"
    / "schema"
    / "scenario.schema.json"
)


def _write_schema(root: Path) -> None:
    dst = root / "prompts" / "scenarios" / "schema" / "scenario.schema.json"
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(_SCHEMA_PATH.read_text())


def _write_scenario(root: Path, filename: str, body: dict) -> None:
    dst = root / "prompts" / "scenarios" / "catalog" / filename
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(yaml.safe_dump(body, sort_keys=False))


def _minimal_scenario(
    *,
    scenario_id: str = "smoke",
    version: int = 1,
    capability_id: str = "t2.reasoner.primary",
    scope: dict | None = None,
    canaries: dict | None = None,
    cited: list[str] | None = None,
) -> dict:
    doc: dict[str, object] = {
        "id": scenario_id,
        "version": version,
        "capability_id": capability_id,
        "expected": {
            "required_fields": [
                {"name": "action_type", "expected_type": "string"},
                {"name": "params", "expected_type": "object", "non_empty": False},
            ]
        },
        "provenance": {"source": "test"},
    }
    if scope is not None:
        doc["scope"] = scope
    if canaries is not None:
        doc["expected"]["canary_tokens"] = canaries  # type: ignore[index]
    if cited is not None:
        doc["expected"]["expected_cited_rule_ids"] = cited  # type: ignore[index]
    return doc


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_load_empty_catalog(tmp_path: Path) -> None:
    _write_schema(tmp_path)
    scenarios = load_scenarios(tmp_path)
    assert scenarios == ()


def test_load_minimal_scenario_produces_recognition_scenario(tmp_path: Path) -> None:
    _write_schema(tmp_path)
    _write_scenario(tmp_path, "smoke.v1.yaml", _minimal_scenario())

    scenarios = load_scenarios(tmp_path)

    assert len(scenarios) == 1
    scenario = scenarios[0]
    assert scenario.id == "smoke"
    assert scenario.capability_id == "t2.reasoner.primary"
    assert scenario.scope is None
    field_names = [f.name for f in scenario.expected.required_fields]
    assert field_names == ["action_type", "params"]
    # ``non_empty`` defaults to ``True`` when the field omits it; the second
    # required field explicitly opts out.
    non_empty_flags = [f.non_empty for f in scenario.expected.required_fields]
    assert non_empty_flags == [True, False]


def test_load_scenario_with_scope_and_canaries(tmp_path: Path) -> None:
    _write_schema(tmp_path)
    _write_scenario(
        tmp_path,
        "scoped.v1.yaml",
        _minimal_scenario(
            scenario_id="scoped",
            scope={"resource_group_ref": "rg-prod", "resource_ref": "res-42"},
            canaries={"base": "CN_PINNED"},
            cited=["rule.a", "rule.b"],
        ),
    )

    scenarios = load_scenarios(tmp_path)

    assert scenarios[0].scope == OperatorScope(resource_group_ref="rg-prod", resource_ref="res-42")
    assert scenarios[0].expected.canary_tokens == {"base": "CN_PINNED"}
    assert scenarios[0].expected.expected_cited_rule_ids == ("rule.a", "rule.b")


def test_load_scenario_with_rg_only_scope(tmp_path: Path) -> None:
    """``resource_ref`` is optional; a scenario that binds only to a
    resource group MUST load with ``resource_ref=None``."""

    _write_schema(tmp_path)
    _write_scenario(
        tmp_path,
        "rg-only.v1.yaml",
        _minimal_scenario(
            scenario_id="rg-only",
            scope={"resource_group_ref": "rg-prod"},
        ),
    )

    scenarios = load_scenarios(tmp_path)

    assert scenarios[0].scope == OperatorScope(resource_group_ref="rg-prod", resource_ref=None)


def test_load_sorts_by_id_then_capability(tmp_path: Path) -> None:
    _write_schema(tmp_path)
    _write_scenario(tmp_path, "beta.v1.yaml", _minimal_scenario(scenario_id="beta"))
    _write_scenario(tmp_path, "alpha.v1.yaml", _minimal_scenario(scenario_id="alpha"))

    scenarios = load_scenarios(tmp_path)

    assert [s.id for s in scenarios] == ["alpha", "beta"]


# ---------------------------------------------------------------------------
# Fail-closed paths
# ---------------------------------------------------------------------------


def test_load_rejects_missing_scenarios_directory(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="scenario catalog directory"):
        load_scenarios(tmp_path)


def test_load_rejects_missing_schema(tmp_path: Path) -> None:
    (tmp_path / "prompts" / "scenarios").mkdir(parents=True)
    with pytest.raises(FileNotFoundError, match="scenario catalog schema"):
        load_scenarios(tmp_path)


def test_load_rejects_filename_mismatch(tmp_path: Path) -> None:
    _write_schema(tmp_path)
    _write_scenario(tmp_path, "wrong-name.yaml", _minimal_scenario())

    with pytest.raises(ScenarioLoaderError) as excinfo:
        load_scenarios(tmp_path)
    assert any("file name MUST be" in issue.message for issue in excinfo.value.issues)


def test_load_aggregates_schema_violations(tmp_path: Path) -> None:
    _write_schema(tmp_path)
    _write_scenario(
        tmp_path,
        "bad.v1.yaml",
        {
            "id": "bad",
            "version": 1,
            "capability_id": "",  # empty -> violates minLength: 1
            "expected": {
                "required_fields": [
                    {"name": "action_type", "expected_type": "integer"},  # unsupported
                ],
            },
            "provenance": {},  # missing source
        },
    )

    with pytest.raises(ScenarioLoaderError) as excinfo:
        load_scenarios(tmp_path)
    # Multiple issues should surface in one aggregate error.
    assert len(excinfo.value.issues) >= 2


def test_load_rejects_top_level_non_mapping(tmp_path: Path) -> None:
    _write_schema(tmp_path)
    dst = tmp_path / "prompts" / "scenarios" / "catalog" / "list.v1.yaml"
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text("- id: not-a-mapping\n")

    with pytest.raises(ScenarioLoaderError) as excinfo:
        load_scenarios(tmp_path)
    assert any("MUST be a mapping" in issue.message for issue in excinfo.value.issues)


def test_load_ignores_yaml_under_schema_directory(tmp_path: Path) -> None:
    """A stray YAML inside ``schema/`` MUST NOT be treated as a scenario."""

    _write_schema(tmp_path)
    stray = tmp_path / "prompts" / "scenarios" / "schema" / "stray.yaml"
    stray.write_text("id: stray\nversion: 1\n")

    # No exception, no scenarios (the stray was skipped).
    assert load_scenarios(tmp_path) == ()


def test_shipped_scenario_schema_is_valid_draft202012() -> None:
    """The schema itself MUST parse as valid JSON Schema."""

    from jsonschema import Draft202012Validator

    schema = json.loads(_SCHEMA_PATH.read_text())
    Draft202012Validator.check_schema(schema)


def test_shipped_tree_loads_empty_scenarios() -> None:
    """The upstream ships zero authored scenarios in Wave 3 step
    D-2b-ii-beta; loading MUST succeed with an empty tuple."""

    repo_root = Path(__file__).resolve().parents[3]
    scenarios = load_scenarios(repo_root / "rule-catalog")
    assert scenarios == ()


def test_prompt_registry_still_loads_with_scenarios_present() -> None:
    """A regression guard: `FileSystemPromptRegistry` MUST skip the
    `scenarios/` peer subsystem, otherwise the shipped scenario tree
    would trip prompt-schema validation the way tools/ did before
    step 2.5-A."""

    from aiopspilot.core.prompts.registry import FileSystemPromptRegistry

    repo_root = Path(__file__).resolve().parents[3]
    reg = FileSystemPromptRegistry(repo_root / "rule-catalog")
    # If we got here, the loader saw scenarios/ but did not choke.
    assert reg.artifacts()  # sanity: prompts still land
