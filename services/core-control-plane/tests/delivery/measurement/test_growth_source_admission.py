"""Strict version admission, explicit rejection, and latest source binding."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest
from fdai.delivery.measurement.postgres_growth import (
    PostgresResponseOutcomeSource,
    _mapping,
    _outcome_record,
    _response_outcome,
)
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from tests.assurance_twin.test_feedback_reliability import _feedback
from tests.delivery.measurement.test_dynamic_feedback_replay import _feedback as _versioned
from tests.delivery.measurement.test_growth_replay import _NOW, _Builder, _entry, _Source


@pytest.mark.parametrize("factory", [_feedback, _versioned])
def test_response_source_reads_v1_and_versioned_evidence(factory: Any) -> None:
    outcome = factory(1)
    entry = {
        **outcome.model_dump(mode="json"),
        "actor": "Thor",
        "action_kind": "measurement.action_outcome.v1",
        "mode": "shadow",
        "scorable": True,
        "verification_passed": True,
    }
    assert _response_outcome(entry) == outcome


async def test_invalid_and_unsupported_rows_are_explicitly_rejected_once() -> None:
    store = InMemoryStateStore()

    class Source(PostgresResponseOutcomeSource):
        async def _rows(self, after_seq: int) -> list[Mapping[str, Any]]:
            return [
                {"seq": i, "entry": entry}
                for i, entry in enumerate(
                    (
                        {"schema_version": "9.0.0"},
                        {"schema_version": ["1.0.0"]},
                        {"schema_version": "1.1.0", "outcome_revision": 1},
                        "invalid-json",
                        _feedback(1).model_dump(mode="json"),
                    ),
                    1,
                )
                if i > after_seq
            ]

    source = Source(dsn="unused-local-fake", state_store=store)
    assert len([outcome async for outcome in source.outcomes()]) == 1
    assert [outcome async for outcome in source.outcomes()] == []
    entries = [record["entry"] for record in store.audit_entries]
    assert len(entries) == 4
    assert {entry["action_kind"] for entry in entries} == {"dynamic.learning.source_rejected"}
    assert all(entry["promotion_authority"] is False for entry in entries)
    assert _mapping("invalid-json") == {}


@pytest.mark.parametrize("rollback", [None, "false", 0])
def test_absent_or_coerced_rollback_is_not_a_verified_success(rollback: Any) -> None:
    assert (
        _outcome_record(
            {**_entry(), "rollback_succeeded": rollback},
            recorded_at=_NOW,
        )
        is None
    )


async def test_evicted_or_replaced_authoritative_source_cannot_use_pending_copy() -> None:
    source = _Source(InMemoryStateStore(), [_entry()])
    records = [record async for record in source.outcomes()]
    source.entries.clear()
    assert await _Builder(source).build(records[0]) is None
    source.entries.append({**_entry(), "action_type_id": "ops.restart-service"})
    assert await _Builder(source).build(records[0]) is None


async def test_growth_source_explicitly_audits_unsupported_version() -> None:
    store = InMemoryStateStore()
    source = _Source(store, [{**_entry(), "schema_version": "9.0.0"}])
    assert [record async for record in source.outcomes()] == []
    assert (
        tuple(store.audit_entries)[-1]["entry"]["reason"]
        == "pattern_outcome_invalid_or_unsupported"
    )
