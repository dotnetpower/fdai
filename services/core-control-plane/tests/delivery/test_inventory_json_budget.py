"""Inventory byte admission runs before record copying and large string encoding."""

from __future__ import annotations

import json
import tracemalloc
from dataclasses import asdict

import pytest
from fdai.delivery import inventory_collection
from fdai.delivery import inventory_json_budget as json_budget
from fdai.delivery.azure import inventory
from fdai.delivery.azure.inventory import ResourceQueryResult, _GenerationBudget
from fdai.delivery.inventory_collection import InventoryStreamError, NormalizedCollectionBudget
from fdai.delivery.inventory_json_budget import inventory_json_exceeds_budget
from fdai.shared.providers.inventory import InventoryBatch, ResourceRecord


@pytest.mark.parametrize("owner", ["collection", "provider"])
@pytest.mark.parametrize(
    "padding",
    ["x" * 4096, "\n" * 256, "\U0001f600" * 128],
    ids=["ascii", "control-escape", "surrogate-pair"],
)
def test_oversized_record_is_rejected_before_deepcopy(monkeypatch, owner, padding):
    record = ResourceRecord("example", "compute.vm", {"padding": padding})
    copied = []
    module = inventory_collection if owner == "collection" else inventory

    def traced_asdict(value):
        copied.append(value)
        return asdict(value)

    monkeypatch.setattr(module, "asdict", traced_asdict)
    if owner == "collection":
        monkeypatch.setattr(module, "MAX_COLLECTION_BYTES", 512)
        budget = NormalizedCollectionBudget()
        with pytest.raises(InventoryStreamError, match="byte bound"):
            budget.consume(InventoryBatch(resources=(record,)))
    else:
        monkeypatch.setattr(module, "MAX_GENERATION_BYTES", 512)
        budget = _GenerationBudget()
        with pytest.raises(RuntimeError, match="byte capacity"):
            budget.consume(ResourceQueryResult(resources=(record,)))
    assert copied == []


@pytest.mark.parametrize("owner", ["collection", "provider"])
def test_remaining_generation_allowance_is_checked_before_next_copy(monkeypatch, owner):
    first = ResourceRecord("first", "compute.vm", {"padding": "x" * 200})
    second = ResourceRecord("second", "compute.vm", {"padding": "x" * 200})
    first_size = len(
        json.dumps(asdict(first), ensure_ascii=True, separators=(",", ":"), default=str)
    )
    copied = []
    module = inventory_collection if owner == "collection" else inventory

    def traced_asdict(value):
        copied.append(value.resource_id)
        return asdict(value)

    monkeypatch.setattr(module, "asdict", traced_asdict)
    if owner == "collection":
        monkeypatch.setattr(module, "MAX_COLLECTION_BYTES", first_size + 64)
        budget = NormalizedCollectionBudget()
        error = InventoryStreamError
    else:
        monkeypatch.setattr(module, "MAX_GENERATION_BYTES", first_size + 64)
        budget = _GenerationBudget()
        error = RuntimeError
    batch_type = InventoryBatch if owner == "collection" else ResourceQueryResult
    budget.consume(batch_type(resources=(first,)))
    with pytest.raises(error, match="byte"):
        budget.consume(batch_type(resources=(second,)))
    assert copied == ["first"]


@pytest.mark.parametrize("owner", ["collection", "provider"])
def test_rejecting_four_megabyte_string_keeps_scratch_allocation_bounded(monkeypatch, owner):
    record = ResourceRecord("example", "compute.vm", {"padding": "x" * (4 * 1024 * 1024)})
    if owner == "collection":
        monkeypatch.setattr(inventory_collection, "MAX_COLLECTION_BYTES", 512)
        budget = NormalizedCollectionBudget()
        batch = InventoryBatch(resources=(record,))
        error = InventoryStreamError
    else:
        monkeypatch.setattr(inventory, "MAX_GENERATION_BYTES", 512)
        budget = _GenerationBudget()
        batch = ResourceQueryResult(resources=(record,))
        error = RuntimeError
    tracemalloc.start()
    try:
        with pytest.raises(error, match="byte"):
            budget.consume(batch)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert peak < 128 * 1024


@pytest.mark.parametrize(
    "value",
    [
        "",
        "plain text",
        '\n\t\r\b\f"\\',
        "\u0000\u001f",
        "\U0001f600" * 2049,
        "\ud800",
        [None, True, False, ("nested", {"key": "value"})],
    ],
    ids=["empty", "ascii", "escapes", "controls", "astral", "surrogate", "containers"],
)
def test_preflight_preserves_exact_string_and_container_boundaries(value):
    size = len(json.dumps(value, ensure_ascii=True, separators=(",", ":")))
    assert not inventory_json_exceeds_budget(value, maximum_bytes=size)
    assert inventory_json_exceeds_budget(value, maximum_bytes=size - 1)


@pytest.mark.parametrize(
    "value",
    [
        None,
        True,
        False,
        0,
        -(10**20),
        10**20,
        1.25,
        -1e-300,
        1e300,
        "",
        'escaped\n"text',
        "\U0001f600" * 17,
        {"nested": ["text", None, 42]},
        {1: "integer key"},
    ],
)
@pytest.mark.parametrize("shape", ["scalar", "list", "mapping"])
def test_preflight_never_rejects_data_accepted_at_its_exact_json_size(value, shape):
    if shape == "list":
        value = [value, value, value]
    elif shape == "mapping":
        value = {"one": value, "two": value}
    record = ResourceRecord("example", "compute.vm", {"value": value})
    size = len(json.dumps(asdict(record), ensure_ascii=True, separators=(",", ":"), default=str))
    assert not inventory_json_exceeds_budget(record, maximum_bytes=size)


def test_escape_expansion_is_checked_with_bounded_encoder_inputs(monkeypatch):
    lengths = []
    encode = json_budget.encode_basestring_ascii

    def traced_encode(value):
        lengths.append(len(value))
        return encode(value)

    monkeypatch.setattr(json_budget, "encode_basestring_ascii", traced_encode)
    assert inventory_json_exceeds_budget("\U0001f600" * 2049, maximum_bytes=4096)
    assert lengths == [1024]


@pytest.mark.parametrize("owner", ["collection", "provider"])
def test_exact_existing_encoder_accounting_is_preserved(monkeypatch, owner):
    record = ResourceRecord(
        "example", "compute.vm", {"number": 12345, "fraction": 1.25, "text": "\n"}
    )
    size = len(json.dumps(asdict(record), ensure_ascii=True, separators=(",", ":"), default=str))
    if owner == "collection":
        monkeypatch.setattr(inventory_collection, "MAX_COLLECTION_BYTES", size)
        budget = NormalizedCollectionBudget()
        budget.consume(InventoryBatch(resources=(record,)))
        assert budget.byte_count == size
    else:
        monkeypatch.setattr(inventory, "MAX_GENERATION_BYTES", size)
        budget = _GenerationBudget()
        budget.consume(ResourceQueryResult(resources=(record,)))
        assert budget.encoded_bytes == size
