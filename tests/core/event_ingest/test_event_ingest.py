"""EventIngest - normalize + deduplicate boundary."""

from __future__ import annotations

from typing import Any

import pytest

from fdai.core.event_ingest import EventIngest
from fdai.shared.contracts.models import Event, Mode
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.contracts.validation import (
    ContractValidationError,
    JsonSchemaContractValidator,
    JsonSchemaEventValidator,
)


def _validator() -> JsonSchemaEventValidator:
    return JsonSchemaEventValidator(JsonSchemaContractValidator(PackageResourceSchemaRegistry()))


def test_ingest_accepts_valid_event(valid_event: dict[str, Any]) -> None:
    ingest = EventIngest(validator=_validator())
    got = ingest.ingest(valid_event)
    assert isinstance(got, Event)
    assert got.event_id.hex == valid_event["event_id"].replace("-", "")
    assert got.mode is Mode.SHADOW


def test_ingest_accepts_pre_validated_event_instance(
    valid_event: dict[str, Any],
) -> None:
    """A caller that already holds an ``Event`` (e.g. an in-process
    replay) MUST NOT be forced to serialize back to a dict."""
    event = Event.model_validate(valid_event)
    ingest = EventIngest(validator=_validator())
    assert ingest.ingest(event) is event


def test_duplicate_idempotency_key_returns_none(valid_event: dict[str, Any]) -> None:
    ingest = EventIngest(validator=_validator())
    assert ingest.ingest(valid_event) is not None
    second = ingest.ingest(valid_event)
    assert second is None


def test_seen_keys_tracks_processed(valid_event: dict[str, Any]) -> None:
    ingest = EventIngest(validator=_validator())
    ingest.ingest(valid_event)
    assert valid_event["idempotency_key"] in ingest.seen_keys()


def test_schema_invalid_raises_contract_error(valid_event: dict[str, Any]) -> None:
    ingest = EventIngest(validator=_validator())
    del valid_event["event_id"]
    with pytest.raises(ContractValidationError):
        ingest.ingest(valid_event)


def test_two_distinct_events_both_pass(valid_event: dict[str, Any]) -> None:
    ingest = EventIngest(validator=_validator())
    first = ingest.ingest(valid_event)
    second_raw = {
        **valid_event,
        "event_id": "00000000-0000-0000-0000-000000000099",
        "idempotency_key": "another-key",
    }
    second = ingest.ingest(second_raw)
    assert first is not None
    assert second is not None
    assert ingest.seen_keys() == {
        valid_event["idempotency_key"],
        "another-key",
    }


def test_max_entries_must_be_positive() -> None:
    """Constructor rejects a zero/negative cache bound - the safety-core
    contract is that the cache always has a defined FIFO window."""
    with pytest.raises(ValueError, match="max_entries"):
        EventIngest(validator=_validator(), max_entries=0)


def test_bounded_cache_evicts_oldest_entries(valid_event: dict[str, Any]) -> None:
    """The dedupe cache is a bounded FIFO. Once ``max_entries`` is
    exceeded, the earliest-inserted key is evicted, and a re-delivery
    of the evicted event is treated as fresh (fail forward - the
    executor's own idempotency guard is the durable stop)."""
    ingest = EventIngest(validator=_validator(), max_entries=2)

    def _event(seq: int) -> dict[str, Any]:
        return {
            **valid_event,
            "event_id": f"00000000-0000-0000-0000-{seq:012x}",
            "idempotency_key": f"key-{seq}",
        }

    assert ingest.ingest(_event(1)) is not None
    assert ingest.ingest(_event(2)) is not None
    # This insert evicts key-1 (oldest).
    assert ingest.ingest(_event(3)) is not None
    assert ingest.seen_keys() == {"key-2", "key-3"}
    # key-2 is still in-cache -> re-delivery is deduped.
    assert ingest.ingest(_event(2)) is None
    # key-1 was evicted -> re-delivery is accepted as fresh. This
    # itself evicts the oldest entry (key-2) since capacity is 2.
    assert ingest.ingest(_event(1)) is not None
    assert ingest.seen_keys() == {"key-3", "key-1"}
