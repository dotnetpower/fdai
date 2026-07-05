"""Every shipped JSON Schema must itself be a valid draft-2020-12 document.

A malformed schema is a startup bug — this test catches it before the
validator ever runs against a real event.
"""

from __future__ import annotations

import pytest
from jsonschema import Draft202012Validator

from aiopspilot.shared.contracts.registry import PackageResourceSchemaRegistry

SCHEMA_NAMES = [
    "event",
    "action",
    "rule",
    "ontology/object-type",
    "ontology/link-type",
    "ontology/action-type",
]


@pytest.mark.parametrize("name", SCHEMA_NAMES)
def test_shipped_schema_is_valid_draft_2020_12(name: str) -> None:
    registry = PackageResourceSchemaRegistry()
    schema = registry.get(name)

    # Raises if the schema violates the meta-schema.
    Draft202012Validator.check_schema(dict(schema))


def test_registry_exposes_every_shipped_schema() -> None:
    registry = PackageResourceSchemaRegistry()
    assert sorted(registry.names()) == sorted(SCHEMA_NAMES)


def test_every_shipped_schema_declares_semver_id() -> None:
    """Every schema must carry a semver `$id` — required by our versioning rules."""
    registry = PackageResourceSchemaRegistry()
    for name in SCHEMA_NAMES:
        schema = registry.get(name)
        schema_id = schema.get("$id")
        assert isinstance(schema_id, str), f"{name}: $id missing"
        # e.g. https://aiopspilot.dev/schemas/event/1.0.0
        parts = schema_id.rstrip("/").split("/")
        version = parts[-1]
        assert version.count(".") == 2, f"{name}: $id does not end in a semver ({schema_id!r})"
