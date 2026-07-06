"""Unit tests for :mod:`aiopspilot.core.tools.registry`.

Every case builds a bespoke catalog in a tmp path so the tests are
hermetic. A small integration case at the end confirms the shipped
Wave 2.5-B tree (three shadow-mode tools plus the schema) loads without
error.
"""

from __future__ import annotations

import json
from pathlib import Path
from textwrap import dedent

import pytest
import yaml

from aiopspilot.core.prompts.types import PromptMode
from aiopspilot.core.tools import (
    FileSystemToolRegistry,
    ToolRegistryError,
)

_SCHEMA_PATH = (
    Path(__file__).resolve().parents[3]
    / "rule-catalog"
    / "prompts"
    / "tools"
    / "schema"
    / "tool.schema.json"
)


def _write_schema(root: Path) -> None:
    dst = root / "prompts" / "tools" / "schema" / "tool.schema.json"
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(_SCHEMA_PATH.read_text())


def _write_tool(root: Path, filename: str, body: str) -> Path:
    dst = root / "prompts" / "tools" / "catalog" / filename
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(body)
    return dst


def _minimal_tool_yaml(
    *,
    tool_id: str = "rule.query",
    version: int = 1,
    default_mode: str = "shadow",
    output_wrapper: str | None = None,
) -> str:
    """Return a syntactically valid tool YAML document.

    Built via :func:`yaml.safe_dump` so parameter interpolation cannot
    accidentally break the indentation of downstream keys (the previous
    f-string / dedent build fell into exactly that trap for optional
    fields).
    """

    doc: dict[str, object] = {
        "id": tool_id,
        "version": version,
        "description": "Query the rule catalog.",
        "input_schema": {
            "type": "object",
            "properties": {"rule_id": {"type": "string"}},
        },
        "capability_gate": {
            "requires_tier": "T2",
            "cost_budget_usd_per_call": 0.0,
        },
        "default_mode": default_mode,
        "provider": "RuleCatalogQueryProvider",
        "provenance": {"source": "test"},
    }
    if output_wrapper is not None:
        doc["output_wrapper"] = output_wrapper
    return yaml.safe_dump(doc, sort_keys=False)


def test_registry_loads_empty_catalog(tmp_path: Path) -> None:
    _write_schema(tmp_path)
    reg = FileSystemToolRegistry(tmp_path)
    assert reg.artifacts() == ()


def test_registry_loads_valid_tool(tmp_path: Path) -> None:
    _write_schema(tmp_path)
    _write_tool(tmp_path, "rule.query.v1.yaml", _minimal_tool_yaml())
    reg = FileSystemToolRegistry(tmp_path)
    tools = reg.artifacts()
    assert len(tools) == 1
    tool = tools[0]
    assert tool.id == "rule.query"
    assert tool.version == 1
    assert tool.default_mode is PromptMode.SHADOW
    assert tool.capability_gate.requires_tier == "T2"
    assert tool.capability_gate.cost_budget_usd_per_call == 0.0
    assert tool.provider == "RuleCatalogQueryProvider"
    assert tool.input_schema["type"] == "object"


def test_registry_get_returns_highest_version(tmp_path: Path) -> None:
    _write_schema(tmp_path)
    for version in (1, 3, 2):
        _write_tool(
            tmp_path,
            f"rule.query.v{version}.yaml",
            _minimal_tool_yaml(version=version),
        )
    reg = FileSystemToolRegistry(tmp_path)
    assert reg.get("rule.query").version == 3


def test_registry_get_raises_when_unknown(tmp_path: Path) -> None:
    _write_schema(tmp_path)
    _write_tool(tmp_path, "rule.query.v1.yaml", _minimal_tool_yaml())
    reg = FileSystemToolRegistry(tmp_path)
    with pytest.raises(LookupError, match="no tool"):
        reg.get("web.search")


def test_registry_rejects_filename_mismatch(tmp_path: Path) -> None:
    _write_schema(tmp_path)
    _write_tool(tmp_path, "wrong-name.yaml", _minimal_tool_yaml())
    with pytest.raises(ToolRegistryError) as excinfo:
        FileSystemToolRegistry(tmp_path)
    assert any("file name MUST be" in issue.message for issue in excinfo.value.issues)


def test_registry_rejects_output_wrapper_without_untrusted_marker(
    tmp_path: Path,
) -> None:
    """Safety invariant: a wrapper without ``trusted="false"`` collapses
    the prompt-injection defense documented in the design doc.
    """

    _write_schema(tmp_path)
    _write_tool(
        tmp_path,
        "rule.query.v1.yaml",
        _minimal_tool_yaml(output_wrapper="<tool_result>{}</tool_result>"),
    )
    with pytest.raises(ToolRegistryError) as excinfo:
        FileSystemToolRegistry(tmp_path)
    assert any('trusted="false"' in issue.message for issue in excinfo.value.issues)


def test_registry_accepts_output_wrapper_with_untrusted_marker(tmp_path: Path) -> None:
    _write_schema(tmp_path)
    _write_tool(
        tmp_path,
        "rule.query.v1.yaml",
        _minimal_tool_yaml(
            output_wrapper='<tool_result trusted="false" tool="rule.query">{}</tool_result>',
        ),
    )
    reg = FileSystemToolRegistry(tmp_path)
    assert reg.get("rule.query").output_wrapper is not None


def test_registry_aggregates_schema_violations(tmp_path: Path) -> None:
    _write_schema(tmp_path)
    _write_tool(
        tmp_path,
        "bad.v1.yaml",
        dedent(
            """
            id: bad
            version: 1
            description: ""
            input_schema:
              type: array
            capability_gate: {}
            provenance: {}
            """
        ),
    )
    with pytest.raises(ToolRegistryError) as excinfo:
        FileSystemToolRegistry(tmp_path)
    # Empty description, wrong input_schema.type, and missing
    # provenance.source MUST all surface together in one aggregate error.
    assert len(excinfo.value.issues) >= 2


def test_registry_missing_tools_dir_fails_fast(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="tool catalog directory"):
        FileSystemToolRegistry(tmp_path)


def test_registry_missing_schema_fails_fast(tmp_path: Path) -> None:
    (tmp_path / "prompts" / "tools").mkdir(parents=True)
    with pytest.raises(FileNotFoundError, match="tool catalog schema"):
        FileSystemToolRegistry(tmp_path)


def test_registry_artifacts_sorted_deterministically(tmp_path: Path) -> None:
    _write_schema(tmp_path)
    _write_tool(tmp_path, "beta.v1.yaml", _minimal_tool_yaml(tool_id="beta"))
    _write_tool(tmp_path, "alpha.v1.yaml", _minimal_tool_yaml(tool_id="alpha"))
    reg = FileSystemToolRegistry(tmp_path)
    ids = [(a.id, a.version) for a in reg.artifacts()]
    assert ids == sorted(ids)


def test_registry_shipped_tree_loads() -> None:
    """The shipped Wave 2.5-B tree ships schema + three shadow-mode tools.

    Loading it MUST succeed and expose exactly those three tools; every
    shipped tool MUST be in shadow mode so no live prompt content changes
    until Wave 2.5-B step 2 promotes them individually.
    """

    repo_root = Path(__file__).resolve().parents[3]
    reg = FileSystemToolRegistry(repo_root / "rule-catalog")
    ids = {a.id for a in reg.artifacts()}
    assert ids == {"rule.query", "state.query", "audit.query"}
    assert all(a.default_mode is PromptMode.SHADOW for a in reg.artifacts())


def test_registry_shipped_schema_is_valid_draft202012() -> None:
    """The shipped tool schema must itself parse as valid JSON Schema."""

    from jsonschema import Draft202012Validator

    schema = json.loads(_SCHEMA_PATH.read_text())
    Draft202012Validator.check_schema(schema)
