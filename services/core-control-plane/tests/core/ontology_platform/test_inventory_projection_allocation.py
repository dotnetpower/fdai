"""Reject expanded projection input before any normalization or graph materialization."""

from __future__ import annotations

import tracemalloc
from itertools import repeat
from typing import NoReturn

import pytest
from fdai.core.ontology_platform import inventory_projection
from fdai.core.ontology_platform.inventory_projection_bounds import (
    _MAX_PROJECTION_CHARACTERS,
    _MAX_PROJECTION_VALUES,
    validate_projection_allocation,
)
from fdai.delivery.inventory_collection import (
    MAX_CHUNK_BYTES,
    MAX_COLLECTION_BYTES,
    NormalizedCollectionBudget,
)
from fdai.delivery.inventory_json_budget import inventory_json_exceeds_budget
from fdai.shared.providers.inventory import InventoryBatch, ResourceRecord


def _unexpected_normalization(*args: object, **kwargs: object) -> NoReturn:
    raise AssertionError("normalization started before projection allocation admission")


def test_expanded_aliases_are_rejected_before_normalization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shared = {"note": "x" * (32 * 1024)}
    resource = ResourceRecord(
        resource_id="resource-1", type="compute.vm", props={"items": [shared] * 4096}
    )
    monkeypatch.setattr(inventory_projection, "normalize_json_value", _unexpected_normalization)

    with pytest.raises(ValueError, match="projection allocation exceeds"):
        inventory_projection.build_inventory_ontology_projection(
            generation="generation-1", resources=(resource,)
        )


def test_cyclic_properties_are_rejected_before_normalization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    properties: dict[str, object] = {}
    properties["cycle"] = properties
    resource = ResourceRecord(resource_id="resource-1", type="compute.vm", props=properties)
    monkeypatch.setattr(inventory_projection, "normalize_json_value", _unexpected_normalization)

    with pytest.raises(ValueError, match="projection contains cyclic"):
        inventory_projection.build_inventory_ontology_projection(
            generation="generation-1", resources=(resource,)
        )


@pytest.mark.parametrize("extra_character", [0, 1])
def test_actual_character_limit_accepts_equality_and_rejects_next_unit(
    extra_character: int,
) -> None:
    value = "x" * (_MAX_PROJECTION_CHARACTERS + extra_character)
    if extra_character:
        with pytest.raises(ValueError, match="projection allocation exceeds"):
            validate_projection_allocation((value,))
    else:
        validate_projection_allocation((value,))


@pytest.mark.parametrize("extra_value", [0, 1])
def test_actual_expanded_value_limit_accepts_equality_and_rejects_overflow(
    extra_value: int,
) -> None:
    values = repeat(None, _MAX_PROJECTION_VALUES + extra_value)
    if extra_value:
        with pytest.raises(ValueError, match="expanded-value bound"):
            validate_projection_allocation(values)
    else:
        validate_projection_allocation(values)


def test_byte_admissible_dense_records_are_held_before_projection_copying(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    items: list[list[object]] = [[]] * 100_000
    resources = tuple(
        ResourceRecord(resource_id=f"resource-{index}", type="compute.vm", props={"items": items})
        for index in range(24)
    )
    budget = NormalizedCollectionBudget()
    budget.consume(InventoryBatch(resources=resources))
    assert budget.byte_count < MAX_COLLECTION_BYTES
    assert not inventory_json_exceeds_budget(resources[0], maximum_bytes=MAX_CHUNK_BYTES - 65536)
    assert len(resources) * len(items) > _MAX_PROJECTION_VALUES
    monkeypatch.setattr(inventory_projection, "normalize_json_value", _unexpected_normalization)
    with pytest.raises(ValueError, match="expanded-value bound"):
        inventory_projection.build_inventory_ontology_projection(
            generation="generation-1", resources=resources
        )


def test_alias_refusal_has_bounded_incremental_allocation() -> None:
    shared = {"note": "x" * (32 * 1024)}
    resource = ResourceRecord(
        resource_id="resource-1", type="compute.vm", props={"items": [shared] * 4096}
    )
    tracemalloc.start()
    try:
        with pytest.raises(ValueError, match="projection allocation exceeds"):
            inventory_projection.build_inventory_ontology_projection(
                generation="generation-1", resources=(resource,)
            )
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    assert peak < 512 * 1024


def test_small_aliases_are_charged_without_being_rejected_as_cycles() -> None:
    shared = {"note": ["first", "second"]}
    resource = ResourceRecord(
        resource_id="resource-1", type="compute.vm", props={"items": [shared] * 8}
    )
    result = inventory_projection.build_inventory_ontology_projection(
        generation="generation-1", resources=(resource,)
    )
    assert len(result.objects) == 1
    assert result.objects[0].properties["properties"]["items"] == [shared] * 8


def test_dataclass_iteration_keeps_its_own_record_between_fields() -> None:
    validate_projection_allocation(
        (ResourceRecord(resource_id="resource-1", type="compute.vm", props={"note": "valid"}),)
    )


def test_sequence_cycle_is_rejected() -> None:
    values: list[object] = []
    values.append(values)
    with pytest.raises(ValueError, match="projection contains cyclic"):
        validate_projection_allocation((values,))


def test_excessive_depth_is_rejected_without_recursive_copying() -> None:
    value: object = "leaf"
    for _ in range(140):
        value = [value]
    with pytest.raises(ValueError, match="input nesting exceeds"):
        validate_projection_allocation((value,))
