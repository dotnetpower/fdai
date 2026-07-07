"""The AppConfig JSON Schema is itself valid draft-2020-12.

Same idea as ``tests/contracts/test_schemas_valid.py`` - a malformed config
schema is a startup bug worth catching before the loader runs on real env.
"""

from __future__ import annotations

import json
from importlib import resources
from typing import Any, cast

from jsonschema import Draft202012Validator


def _load_schema() -> dict[str, Any]:
    raw = resources.files("fdai.shared.config").joinpath("schema.json").read_text(encoding="utf-8")
    return cast(dict[str, Any], json.loads(raw))


def test_config_schema_is_valid_draft_2020_12() -> None:
    schema = _load_schema()
    Draft202012Validator.check_schema(schema)


def test_config_schema_declares_semver_id() -> None:
    schema = _load_schema()
    schema_id = schema.get("$id")
    assert isinstance(schema_id, str)
    version = schema_id.rstrip("/").split("/")[-1]
    assert version.count(".") == 2, f"$id does not end in semver ({schema_id!r})"


def test_config_schema_lists_autonomy_mode_default_first_class() -> None:
    """The autonomy-mode-default enum MUST be present with 'shadow' as the default."""
    schema = _load_schema()
    props = schema["properties"]["runtime"]["properties"]["autonomy_mode_default"]
    assert props["enum"] == ["shadow", "enforce"]
    assert props.get("default") == "shadow"
