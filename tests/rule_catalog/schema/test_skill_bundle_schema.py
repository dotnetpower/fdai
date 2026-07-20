"""Public governed skill bundle schema tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pytest
from jsonschema import Draft202012Validator

from fdai.core.skills import encode_skill_bundle_manifest

_SCHEMA = Path("rule-catalog/schema/skill-bundle.schema.json")


def _manifest() -> dict[str, object]:
    return cast(
        dict[str, object],
        json.loads(
            encode_skill_bundle_manifest(
                {
                    "name": "incident-evidence-pack",
                    "version": "1.0.0",
                    "description": "Reviewed incident evidence procedures.",
                    "source": "publisher.example",
                    "members": [
                        {"name": "inventory-evidence", "version": "==1.0.0"},
                        {"name": "log-evidence", "version": "==2.0.0"},
                    ],
                    "allowed_agents": ["Bragi"],
                    "required_tools": ["query_inventory", "query_log"],
                    "instruction": "Use members in declared order.",
                }
            )
        ),
    )


def test_public_schema_accepts_canonical_bundle_manifest() -> None:
    schema = json.loads(_SCHEMA.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)

    Draft202012Validator(schema).validate(_manifest())


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("version", "v1"),
        ("members", []),
        ("members", [{"name": "inventory-evidence", "version": ">=1.0.0"}]),
        ("instruction", "x" * 8193),
        ("digest", "not-a-digest"),
    ],
)
def test_public_schema_rejects_invalid_bundle_contract(field: str, value: object) -> None:
    schema = json.loads(_SCHEMA.read_text(encoding="utf-8"))
    manifest = _manifest()
    manifest[field] = value

    assert list(Draft202012Validator(schema).iter_errors(manifest))
