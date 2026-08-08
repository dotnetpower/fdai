"""Cross-schema drift guard between pydantic models and JSON Schemas.

The JSON schemas are the source of truth
(:file:`services/core-control-plane/src/fdai/shared/contracts/<domain>/schema.json`). The pydantic
models are their hand-authored Python view. Whenever the two drift, the
verifier (which re-checks against the JSON Schema) and the pydantic view
(which the composition root uses at boundaries) disagree, and a
supposedly-valid payload starts failing downstream for cryptic reasons.

This test pins the two views field-set-equal so a drift PR either updates
both or fails loudly. Tracker: #18 G-4 hardening H10.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fdai.shared.contracts.models import (
    Action,
    Event,
    Incident,
    Rule,
    Workflow,
)

_CONTRACTS = Path(__file__).resolve().parents[3] / "src" / "fdai" / "shared" / "contracts"

# Pydantic name -> JSON Schema stem.
_PAIRS = {
    "event": (Event, "event"),
    "action": (Action, "action"),
    "rule": (Rule, "rule"),
    "incident": (Incident, "incident"),
    "workflow": (Workflow, "workflow"),
}


@pytest.mark.parametrize("stem,pair", sorted(_PAIRS.items()))
def test_pydantic_field_set_matches_json_schema(stem: str, pair: tuple[type, str]) -> None:
    model_cls, schema_stem = pair
    schema_path = _CONTRACTS / schema_stem / "schema.json"
    schema = json.loads(schema_path.read_text())

    schema_props = set(schema.get("properties", {}).keys())
    pyd_props = set(model_cls.model_fields.keys())

    only_in_schema = schema_props - pyd_props
    only_in_pydantic = pyd_props - schema_props

    assert not only_in_schema, (
        f"{stem}: JSON Schema has properties the pydantic model lacks: "
        f"{sorted(only_in_schema)}. Add them to the model or remove them "
        "from the schema in the same PR (schemas are the source of truth "
        "but the two views MUST agree)."
    )
    assert not only_in_pydantic, (
        f"{stem}: pydantic model has fields the JSON Schema lacks: "
        f"{sorted(only_in_pydantic)}. Add them to the schema or remove "
        "them from the model in the same PR."
    )


@pytest.mark.parametrize("stem,pair", sorted(_PAIRS.items()))
def test_json_schema_required_are_pydantic_required(stem: str, pair: tuple[type, str]) -> None:
    model_cls, schema_stem = pair
    schema_path = _CONTRACTS / schema_stem / "schema.json"
    schema = json.loads(schema_path.read_text())

    schema_required = set(schema.get("required", []))
    # A pydantic field is required if it has no default value AND is not
    # declared Optional via a union with None. model_fields[x].is_required()
    # captures that precisely.
    pyd_required = {name for name, field in model_cls.model_fields.items() if field.is_required()}

    only_in_schema = schema_required - pyd_required
    only_in_pydantic = pyd_required - schema_required

    assert not only_in_schema, (
        f"{stem}: fields required by the JSON Schema are optional in the "
        f"pydantic model: {sorted(only_in_schema)}. A payload missing "
        "these would pass validation() but fail the JSON Schema re-check."
    )
    assert not only_in_pydantic, (
        f"{stem}: fields required by the pydantic model are optional in "
        f"the JSON Schema: {sorted(only_in_pydantic)}. A payload missing "
        "these would pass the schema check but fail model construction."
    )
