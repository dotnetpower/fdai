"""Secured evidence inputs MUST come from a plan node, never from a model literal."""

from __future__ import annotations

from typing import Any

from fdai.core.ontology_platform.operational_functions import operational_function_types


def _object_inputs(schema: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    properties = (schema or {}).get("properties", {})
    if not isinstance(properties, dict):
        return {}
    return {
        name: value
        for name, value in properties.items()
        if isinstance(value, dict) and value.get("type") == "object"
    }


def test_every_object_valued_function_input_is_dependency_only() -> None:
    unmarked = [
        (function_type.name, name)
        for function_type in operational_function_types(())
        for name, schema in _object_inputs(function_type.input_schema).items()
        if schema.get("x-fdai-dependency-only") is not True
    ]
    assert unmarked == [], (
        "object-valued FunctionType inputs carry gateway-secured query results or "
        "evidence bundles; an unmarked input lets a proposed plan substitute a "
        f"model-authored literal for secured evidence: {unmarked}"
    )
