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


def test_operator_proposal_normalizes_to_deterministic_event() -> None:
    proposal = {
        "idempotency_key": "operator-1::run-1",
        "correlation_id": "vm-task-example",
        "initiator_principal": "operator-1",
        "operator_initiated": True,
        "action_type": "tool.run-python-on-vm",
        "resource_id": "resource:compute/vm/gpu-worker",
        "event_type": "operator_request",
        "params": {
            "artifact_ref": "python-task:gpu.health@1.0.0#" + "a" * 64,
            "target_resource_ref": "resource:compute/vm/gpu-worker",
            "reason": "Run the governed GPU health task.",
        },
        "workflow_action": {
            "process_id": "process-1",
            "step_id": "run-task",
            "proposal_ref": "operator-1::run-1",
        },
    }

    first = EventIngest(validator=_validator()).ingest(proposal)
    replay = EventIngest(validator=_validator()).ingest(proposal)

    assert first is not None and replay is not None
    assert first.event_id == replay.event_id
    assert first.source == "operator_console"
    assert first.resource_ref == proposal["resource_id"]
    assert first.payload["operator_request"]["params"] == proposal["params"]
    assert first.payload["workflow_action"] == proposal["workflow_action"]


@pytest.mark.parametrize("resource_id", ("", "   "))
def test_operator_proposal_normalizes_blank_resource_to_none(resource_id: str) -> None:
    proposal = {
        "idempotency_key": "operator-1::resource-free",
        "initiator_principal": "operator-1",
        "operator_initiated": True,
        "action_type": "tool.generate-report",
        "resource_id": resource_id,
        "event_type": "operator_request",
        "params": {},
    }

    event = EventIngest(validator=_validator()).ingest(proposal)

    assert event is not None
    assert event.resource_ref is None
    assert event.payload["resource"]["resource_id"] is None


@pytest.mark.parametrize(
    "patch",
    (
        {"operator_initiated": "true"},
        {"params": None},
        {"initiator_principal": ""},
    ),
)
def test_malformed_operator_proposal_is_not_normalized(patch: dict[str, Any]) -> None:
    proposal = {
        "idempotency_key": "operator-1::run-1",
        "initiator_principal": "operator-1",
        "operator_initiated": True,
        "action_type": "tool.run-python-on-vm",
        "resource_id": "resource:compute/vm/gpu-worker",
        "event_type": "operator_request",
        "params": {},
        **patch,
    }

    with pytest.raises(ContractValidationError):
        EventIngest(validator=_validator()).ingest(proposal)
