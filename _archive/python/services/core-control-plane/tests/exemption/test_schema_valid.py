"""The shipped exemption JSON Schema is valid draft-2020-12."""

from __future__ import annotations

import json
from importlib import resources
from typing import Any, cast

from jsonschema import Draft202012Validator


def _load_schema() -> dict[str, Any]:
    raw = (
        resources.files("fdai.rule_catalog.schema")
        .joinpath("exemption.schema.json")
        .read_text(encoding="utf-8")
    )
    return cast(dict[str, Any], json.loads(raw))


def test_exemption_schema_is_valid_draft_2020_12() -> None:
    Draft202012Validator.check_schema(_load_schema())


def test_exemption_schema_declares_semver_id() -> None:
    schema = _load_schema()
    schema_id = schema.get("$id")
    assert isinstance(schema_id, str)
    version = schema_id.rstrip("/").split("/")[-1]
    assert version.count(".") == 2, f"$id does not end in semver ({schema_id!r})"
