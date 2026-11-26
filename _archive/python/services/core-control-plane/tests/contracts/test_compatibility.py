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


def test_adding_enum_where_none_existed_is_breaking() -> None:
    # H4: constraining a previously-free field to an enum invalidates data
    # that was valid before.
    old = _obj({"color": {"type": "string"}})
    new = _obj({"color": {"type": "string", "enum": ["red", "green"]}})
    report = check_schema_compatibility(old, new)
    assert report.level is CompatibilityLevel.BREAKING
    assert report.breaking_changes[0].kind == "enum_added"


def test_adding_type_where_none_existed_is_breaking() -> None:
    # H5: a field with no type accepted anything; adding a type narrows it.
    old = _obj({"a": {"description": "anything"}})
    new = _obj({"a": {"type": "string"}})
    report = check_schema_compatibility(old, new)
    assert report.level is CompatibilityLevel.BREAKING
    assert report.breaking_changes[0].kind == "type_changed"


def test_type_widening_to_nullable_is_compatible() -> None:
    # Widening a type to a superset (e.g. making it nullable) still accepts
    # every value old producers sent, so it is backward-compatible.
    old = _obj({"a": {"type": "string"}})
    new = _obj({"a": {"type": ["string", "null"]}})
    assert check_schema_compatibility(old, new).is_compatible


def test_type_narrowing_from_nullable_is_breaking() -> None:
    # Removing a member from the type set (no longer nullable) invalidates old
    # data that used it.
    old = _obj({"a": {"type": ["string", "null"]}})
    new = _obj({"a": {"type": "string"}})
    report = check_schema_compatibility(old, new)
    assert report.level is CompatibilityLevel.BREAKING
    assert report.breaking_changes[0].kind == "type_changed"


def test_type_list_reorder_is_not_breaking() -> None:
    # H6: type is a set; order must not produce a false positive.
    old = _obj({"a": {"type": ["string", "null"]}})
    new = _obj({"a": {"type": ["null", "string"]}})
    assert check_schema_compatibility(old, new).is_compatible


def test_removing_type_constraint_is_compatible() -> None:
    # H5 inverse: widening (dropping the type) is safe.
    old = _obj({"a": {"type": "string"}})
    new = _obj({"a": {"description": "now anything"}})
    assert check_schema_compatibility(old, new).is_compatible


def test_breaking_change_inside_array_items_is_detected() -> None:
    # H7: a removed field inside an array's element schema is breaking.
    old = _obj({"tags": {"type": "array", "items": _obj({"k": {"type": "string"}})}})
    new = _obj({"tags": {"type": "array", "items": _obj({})}})
    report = check_schema_compatibility(old, new)
    assert report.level is CompatibilityLevel.BREAKING
    assert report.breaking_changes[0].path == "tags[].k"
    assert report.breaking_changes[0].kind == "field_removed"
