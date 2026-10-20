"""Bound canonical Mapping/Sequence expansion before copying or normalization."""

from __future__ import annotations

import json
import tracemalloc
from collections import UserDict
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta, timezone
from typing import NoReturn

import pytest
from fdai.delivery import inventory_collection
from fdai.delivery.inventory_json_budget import inventory_json_exceeds_budget
from fdai.shared.providers.inventory import InventoryBatch, ResourceRecord
from fdai.shared.providers.ontology_instance import normalize_json_value


def _unexpected_materialization(*args: object, **kwargs: object) -> NoReturn:
    raise AssertionError("copy or normalization started before expanded JSON admission")


@pytest.mark.parametrize("kind", ["mapping", "sequence"])
@pytest.mark.parametrize("phase", ["collection", "chunk", "batches"])
def test_expanded_input_is_refused_before_materialization(
    monkeypatch: pytest.MonkeyPatch, kind: str, phase: str
) -> None:
    properties: UserDict[str, object]
    if kind == "mapping":
        size = 17 * 1024 * 1024 if phase == "collection" else 2 * 1024 * 1024
        properties = UserDict({"blob": "x" * size})
    else:
        count = 9_000_000 if phase == "collection" else 600_000
        properties = UserDict({"items": range(count)})
    batch = InventoryBatch(
        resources=(ResourceRecord(resource_id="resource-1", type="compute.vm", props=properties),)
    )
    if phase == "collection":
        monkeypatch.setattr(inventory_collection, "asdict", _unexpected_materialization)
        with pytest.raises(inventory_collection.InventoryStreamError, match="byte bound"):
            inventory_collection.NormalizedCollectionBudget().consume(batch)
    else:
        monkeypatch.setattr(
            inventory_collection, "redact_runtime_environment", _unexpected_materialization
        )
        with pytest.raises(ValueError, match="byte bound|chunk capacity"):
            if phase == "chunk":
                inventory_collection.resource_chunk(
                    attempt_id="attempt-1",
                    context_digest="sha256:" + "0" * 64,
                    sequence=0,
                    previous_digest=None,
                    batch=batch,
                )
            else:
                list(inventory_collection.resource_chunk_batches(batch))


class _UnmaterializedSequence(Sequence[object]):
    def __len__(self) -> int:
        return 1_000_000_000

    def __getitem__(self, index: object) -> NoReturn:
        raise AssertionError("oversized sequence was iterated")


def test_huge_sequence_is_refused_before_iteration() -> None:
    assert inventory_json_exceeds_budget(
        _UnmaterializedSequence(), maximum_bytes=inventory_collection.MAX_CHUNK_BYTES
    )


@pytest.mark.parametrize("extra_byte", [0, 1])
def test_canonical_mapping_sequence_exact_chunk_byte_bound(extra_byte: int) -> None:
    value: UserDict[str, object] = UserDict({"items": range(10), "padding": ""})
    encoded = json.dumps(
        normalize_json_value(value), ensure_ascii=True, separators=(",", ":")
    ).encode()
    padding = inventory_collection.MAX_CHUNK_BYTES - len(encoded) + extra_byte
    value["padding"] = "x" * padding
    assert (
        len(
            json.dumps(
                normalize_json_value(value), ensure_ascii=True, separators=(",", ":")
            ).encode()
        )
        == inventory_collection.MAX_CHUNK_BYTES + extra_byte
    )
    assert inventory_json_exceeds_budget(
        value, maximum_bytes=inventory_collection.MAX_CHUNK_BYTES
    ) is bool(extra_byte)


@pytest.mark.parametrize(
    "value",
    [range(0), range(4), (None, True, False, "escaped\n"), [[], {"text": "example"}]],
)
def test_canonical_small_sequences_preserve_byte_accounting(value: object) -> None:
    encoded = json.dumps(
        normalize_json_value(value), ensure_ascii=True, separators=(",", ":")
    ).encode()
    assert not inventory_json_exceeds_budget(value, maximum_bytes=len(encoded))
    assert inventory_json_exceeds_budget(value, maximum_bytes=len(encoded) - 1)


def test_expanded_sequence_refusal_has_bounded_incremental_allocation() -> None:
    batch = InventoryBatch(
        resources=(
            ResourceRecord(
                resource_id="resource-1", type="compute.vm", props={"items": range(9_000_000)}
            ),
        )
    )
    tracemalloc.start()
    try:
        with pytest.raises(inventory_collection.InventoryStreamError, match="byte bound"):
            inventory_collection.NormalizedCollectionBudget().consume(batch)
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    assert peak < 128 * 1024


@pytest.mark.parametrize("phase", ["chunk", "batches"])
def test_numeric_digits_are_counted_before_sequence_materialization(
    monkeypatch: pytest.MonkeyPatch, phase: str
) -> None:
    batch = InventoryBatch(
        resources=(
            ResourceRecord(
                resource_id="resource-1", type="compute.vm", props={"items": range(200_000)}
            ),
        )
    )
    monkeypatch.setattr(
        inventory_collection, "redact_runtime_environment", _unexpected_materialization
    )
    with pytest.raises(ValueError, match="byte bound|chunk capacity"):
        if phase == "chunk":
            inventory_collection.resource_chunk(
                attempt_id="attempt-1",
                context_digest="sha256:" + "0" * 64,
                sequence=0,
                previous_digest=None,
                batch=batch,
            )
        else:
            list(inventory_collection.resource_chunk_batches(batch))


@pytest.mark.parametrize(
    "value",
    [
        0,
        -123456,
        1.25,
        -0.0,
        datetime(2026, 10, 21, tzinfo=UTC),
        datetime(2026, 10, 21, tzinfo=timezone(timedelta(hours=9))),
    ],
)
def test_known_scalar_sizes_match_canonical_values(value: object) -> None:
    encoded = json.dumps(normalize_json_value(value), separators=(",", ":")).encode()
    assert not inventory_json_exceeds_budget(value, maximum_bytes=len(encoded))
    assert inventory_json_exceeds_budget(value, maximum_bytes=len(encoded) - 1)


@pytest.mark.parametrize("sign", [-1, 1])
def test_large_integer_is_refused_without_decimal_string_materialization(sign: int) -> None:
    assert inventory_json_exceeds_budget(sign * 10**5000, maximum_bytes=1024)


def test_naive_datetime_stays_encoder_owned() -> None:
    value = datetime(2026, 10, 21)
    encoded = json.dumps(value, default=str, separators=(",", ":")).encode()
    assert not inventory_json_exceeds_budget(value, maximum_bytes=len(encoded))


def test_unknown_scalar_conversion_stays_with_the_existing_encoder() -> None:
    class DeferredScalar:
        def __str__(self) -> NoReturn:
            raise AssertionError("preflight called an arbitrary string converter")

    assert not inventory_json_exceeds_budget(DeferredScalar(), maximum_bytes=1)
