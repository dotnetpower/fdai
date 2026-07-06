"""Unit tests for :mod:`aiopspilot.core.prompts.registry`.

Every construction is on a tmp catalog root so the tests are fully
hermetic. The shipped ``rule-catalog/prompts/`` tree gets its own
integration coverage in
``tests/core/prompts/test_yaml_matches_dataclass_default.py``.
"""

from __future__ import annotations

import json
from pathlib import Path
from textwrap import dedent

import pytest

from aiopspilot.core.prompts import (
    FileSystemPromptRegistry,
    PromptLayer,
    PromptMode,
    PromptRegistryError,
)

_SCHEMA_PATH = (
    Path(__file__).resolve().parents[3]
    / "rule-catalog"
    / "prompts"
    / "schema"
    / "prompt.schema.json"
)


def _write_schema(root: Path) -> None:
    """Copy the real JSON schema into ``root/prompts/schema/``.

    Tests validate against the same schema that ships with the repo -
    a diverging in-test schema would be a way to hide breakage.
    """

    dst = root / "prompts" / "schema" / "prompt.schema.json"
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(_SCHEMA_PATH.read_text())


def _write_prompt(root: Path, subdir: str, filename: str, body: str) -> Path:
    dst = root / "prompts" / subdir / filename
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(body)
    return dst


def test_registry_loads_valid_base_artifact(tmp_path: Path) -> None:
    _write_schema(tmp_path)
    _write_prompt(
        tmp_path,
        "base",
        "hello.v1.yaml",
        dedent(
            """
            id: hello
            version: 1
            layer: base
            applies_to:
              - t2.reasoner.primary
            token_budget: 32
            default_mode: enforce
            body: "hello"
            provenance:
              source: test
            """
        ),
    )
    reg = FileSystemPromptRegistry(tmp_path)
    art = reg.get_base("t2.reasoner.primary")
    assert art.id == "hello"
    assert art.version == 1
    assert art.layer is PromptLayer.BASE
    assert art.default_mode is PromptMode.ENFORCE
    assert art.token_budget == 32
    assert art.applies_to == ("t2.reasoner.primary",)


def test_registry_selects_highest_version(tmp_path: Path) -> None:
    _write_schema(tmp_path)
    for version in (1, 3, 2):
        _write_prompt(
            tmp_path,
            "base",
            f"hello.v{version}.yaml",
            dedent(
                f"""
                id: hello
                version: {version}
                layer: base
                applies_to:
                  - t2.reasoner.primary
                default_mode: enforce
                body: "body v{version}"
                provenance:
                  source: test
                """
            ),
        )
    reg = FileSystemPromptRegistry(tmp_path)
    assert reg.get_base("t2.reasoner.primary").version == 3


def test_registry_empty_applies_to_matches_any_capability(tmp_path: Path) -> None:
    _write_schema(tmp_path)
    _write_prompt(
        tmp_path,
        "base",
        "global.v1.yaml",
        dedent(
            """
            id: global
            version: 1
            layer: base
            body: "generic"
            provenance:
              source: test
            """
        ),
    )
    reg = FileSystemPromptRegistry(tmp_path)
    art = reg.get_base("any.capability.id")
    assert art.id == "global"


def test_registry_raises_when_no_base_matches(tmp_path: Path) -> None:
    _write_schema(tmp_path)
    _write_prompt(
        tmp_path,
        "base",
        "narrow.v1.yaml",
        dedent(
            """
            id: narrow
            version: 1
            layer: base
            applies_to:
              - t2.reasoner.primary
            body: "narrow"
            provenance:
              source: test
            """
        ),
    )
    reg = FileSystemPromptRegistry(tmp_path)
    with pytest.raises(LookupError, match="no base prompt"):
        reg.get_base("t2.reasoner.secondary")


def test_registry_rejects_filename_mismatch(tmp_path: Path) -> None:
    _write_schema(tmp_path)
    _write_prompt(
        tmp_path,
        "base",
        "wrong-name.yaml",
        dedent(
            """
            id: hello
            version: 1
            layer: base
            body: "x"
            provenance:
              source: test
            """
        ),
    )
    with pytest.raises(PromptRegistryError) as excinfo:
        FileSystemPromptRegistry(tmp_path)
    assert any("file name MUST be" in issue.message for issue in excinfo.value.issues)


def test_registry_aggregates_schema_violations(tmp_path: Path) -> None:
    _write_schema(tmp_path)
    _write_prompt(
        tmp_path,
        "base",
        "bad.v1.yaml",
        dedent(
            """
            id: bad
            version: 1
            layer: not-a-valid-layer
            body: ""
            provenance: {}
            """
        ),
    )
    with pytest.raises(PromptRegistryError) as excinfo:
        FileSystemPromptRegistry(tmp_path)
    messages = [issue.message for issue in excinfo.value.issues]
    # A missing enum value AND an empty body AND missing provenance.source
    # should all surface together.
    assert len(messages) >= 2


def test_registry_missing_prompts_dir_fails_fast(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="prompt catalog directory"):
        FileSystemPromptRegistry(tmp_path)


def test_registry_missing_schema_fails_fast(tmp_path: Path) -> None:
    (tmp_path / "prompts").mkdir()
    with pytest.raises(FileNotFoundError, match="schema"):
        FileSystemPromptRegistry(tmp_path)


def test_registry_artifacts_sorted_deterministically(tmp_path: Path) -> None:
    _write_schema(tmp_path)
    _write_prompt(
        tmp_path,
        "base",
        "alpha.v1.yaml",
        dedent(
            """
            id: alpha
            version: 1
            layer: base
            body: a
            provenance: {source: test}
            """
        ),
    )
    _write_prompt(
        tmp_path,
        "base",
        "beta.v2.yaml",
        dedent(
            """
            id: beta
            version: 2
            layer: base
            body: b
            provenance: {source: test}
            """
        ),
    )
    reg = FileSystemPromptRegistry(tmp_path)
    ids = [(a.id, a.version) for a in reg.artifacts()]
    assert ids == sorted(ids)


def test_registry_skips_schema_directory(tmp_path: Path) -> None:
    _write_schema(tmp_path)
    # A stray YAML placed inside the schema directory MUST be ignored.
    schema_dir = tmp_path / "prompts" / "schema"
    (schema_dir / "stray.yaml").write_text(
        dedent(
            """
            id: stray
            version: 1
            layer: base
            body: x
            provenance: {source: test}
            """
        )
    )
    # No other artifacts -> get_base raises, but constructor must not error.
    reg = FileSystemPromptRegistry(tmp_path)
    assert reg.artifacts() == ()


def test_registry_schema_json_is_valid_draft202012() -> None:
    """The shipped schema itself must parse as valid JSON Schema."""

    from jsonschema import Draft202012Validator

    schema = json.loads(_SCHEMA_PATH.read_text())
    # Raises if the schema is malformed against the meta-schema.
    Draft202012Validator.check_schema(schema)


def test_registry_get_packs_returns_empty_when_no_packs(tmp_path: Path) -> None:
    _write_schema(tmp_path)
    _write_prompt(
        tmp_path,
        "base",
        "hello.v1.yaml",
        dedent(
            """
            id: hello
            version: 1
            layer: base
            applies_to:
              - t2.reasoner.primary
            body: hi
            provenance: {source: test}
            """
        ),
    )
    reg = FileSystemPromptRegistry(tmp_path)
    assert reg.get_packs("t2.reasoner.primary") == ()


def test_registry_get_packs_keeps_highest_version_only(tmp_path: Path) -> None:
    _write_schema(tmp_path)
    _write_prompt(
        tmp_path,
        "base",
        "hello.v1.yaml",
        dedent(
            """
            id: hello
            version: 1
            layer: base
            applies_to: [t2.reasoner.primary]
            body: hi
            provenance: {source: test}
            """
        ),
    )
    for version in (1, 2):
        _write_prompt(
            tmp_path,
            "packs",
            f"pack-a.v{version}.yaml",
            dedent(
                f"""
                id: pack-a
                version: {version}
                layer: pack
                applies_to: [t2.reasoner.primary]
                body: p{version}
                provenance: {{source: test}}
                """
            ),
        )
    reg = FileSystemPromptRegistry(tmp_path)
    packs = reg.get_packs("t2.reasoner.primary")
    assert len(packs) == 1
    assert packs[0].version == 2


def test_registry_get_packs_filters_by_applies_to(tmp_path: Path) -> None:
    _write_schema(tmp_path)
    _write_prompt(
        tmp_path,
        "base",
        "hello.v1.yaml",
        dedent(
            """
            id: hello
            version: 1
            layer: base
            applies_to: [t2.reasoner.primary]
            body: hi
            provenance: {source: test}
            """
        ),
    )
    _write_prompt(
        tmp_path,
        "packs",
        "secondary-only.v1.yaml",
        dedent(
            """
            id: secondary-only
            version: 1
            layer: pack
            applies_to: [t2.reasoner.secondary]
            body: secondary
            provenance: {source: test}
            """
        ),
    )
    reg = FileSystemPromptRegistry(tmp_path)
    assert reg.get_packs("t2.reasoner.primary") == ()
    assert len(reg.get_packs("t2.reasoner.secondary")) == 1
