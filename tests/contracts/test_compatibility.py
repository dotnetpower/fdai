"""Tests for the schema compatibility (evolution guard) checker."""

from __future__ import annotations

from fdai.shared.contracts.compatibility import (
    CompatibilityLevel,
    check_schema_compatibility,
)


def _obj(props: dict, required: list[str] | None = None) -> dict:
    schema: dict = {"type": "object", "properties": props}
    if required is not None:
        schema["required"] = required
    return schema


def test_identical_schema_is_compatible() -> None:
    s = _obj({"a": {"type": "string"}}, ["a"])
    assert check_schema_compatibility(s, s).is_compatible


def test_added_optional_field_is_compatible() -> None:
    old = _obj({"a": {"type": "string"}}, ["a"])
    new = _obj({"a": {"type": "string"}, "b": {"type": "integer"}}, ["a"])
    assert check_schema_compatibility(old, new).is_compatible


def test_removed_field_is_breaking() -> None:
    old = _obj({"a": {"type": "string"}, "b": {"type": "integer"}})
    new = _obj({"a": {"type": "string"}})
    report = check_schema_compatibility(old, new)
    assert report.level is CompatibilityLevel.BREAKING
    assert report.breaking_changes[0].kind == "field_removed"
    assert report.breaking_changes[0].path == "b"


def test_type_change_is_breaking() -> None:
    old = _obj({"a": {"type": "string"}})
    new = _obj({"a": {"type": "integer"}})
    report = check_schema_compatibility(old, new)
    assert report.level is CompatibilityLevel.BREAKING
    assert report.breaking_changes[0].kind == "type_changed"


def test_newly_required_field_is_breaking() -> None:
    old = _obj({"a": {"type": "string"}, "b": {"type": "integer"}}, ["a"])
    new = _obj({"a": {"type": "string"}, "b": {"type": "integer"}}, ["a", "b"])
    report = check_schema_compatibility(old, new)
    assert report.level is CompatibilityLevel.BREAKING
    assert report.breaking_changes[0].kind == "required_added"


def test_relaxing_required_to_optional_is_compatible() -> None:
    old = _obj({"a": {"type": "string"}}, ["a"])
    new = _obj({"a": {"type": "string"}}, [])
    assert check_schema_compatibility(old, new).is_compatible


def test_enum_narrowing_is_breaking() -> None:
    old = _obj({"s": {"type": "string", "enum": ["x", "y", "z"]}})
    new = _obj({"s": {"type": "string", "enum": ["x", "y"]}})
    report = check_schema_compatibility(old, new)
    assert report.level is CompatibilityLevel.BREAKING
    assert report.breaking_changes[0].kind == "enum_narrowed"


def test_enum_widening_is_compatible() -> None:
    old = _obj({"s": {"type": "string", "enum": ["x", "y"]}})
    new = _obj({"s": {"type": "string", "enum": ["x", "y", "z"]}})
    assert check_schema_compatibility(old, new).is_compatible


def test_nested_object_breaking_change_is_detected() -> None:
    old = _obj({"meta": _obj({"a": {"type": "string"}})})
    new = _obj({"meta": _obj({"a": {"type": "integer"}})})
    report = check_schema_compatibility(old, new)
    assert report.level is CompatibilityLevel.BREAKING
    assert report.breaking_changes[0].path == "meta.a"
    assert report.breaking_changes[0].kind == "type_changed"
