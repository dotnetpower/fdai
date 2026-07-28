"""Verified audit outcome parsing for pattern growth."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

from fdai.delivery.measurement.postgres_growth import (
    PostgresVerifiedOutcomeSource,
    _latest_outcome_rows,
    _outcome_record,
)
from fdai.shared.providers.testing.state_store import InMemoryStateStore


def _entry() -> dict[str, object]:
    return {
        "action_id": "action-1",
        "action_type_id": "remediate.tag-add",
        "observed_at": "2026-07-15T00:00:00Z",
        "execution_mode": "enforce",
        "verification_passed": True,
        "decision": "auto",
        "rollback_succeeded": False,
    }


def test_verified_enforce_auto_outcome_is_eligible() -> None:
    record = _outcome_record(
        _entry(),
        recorded_at=datetime(2026, 7, 15, tzinfo=UTC),
    )
    assert record is not None
    assert record.was_auto is True
    assert record.was_verified is True
    assert record.was_rolled_back is False


def test_missing_verification_is_not_inferred() -> None:
    entry = _entry()
    entry.pop("verification_passed")
    assert _outcome_record(entry, recorded_at=datetime(2026, 7, 15, tzinfo=UTC)) is None


def test_explicit_verification_failure_is_preserved_for_rejection() -> None:
    entry = _entry()
    entry["verification_passed"] = False

    record = _outcome_record(entry, recorded_at=datetime(2026, 7, 15, tzinfo=UTC))

    assert record is not None
    assert record.was_verified is False


def test_shadow_execution_is_not_training_data() -> None:
    entry = _entry()
    entry["execution_mode"] = "shadow"
    assert _outcome_record(entry, recorded_at=datetime(2026, 7, 15, tzinfo=UTC)) is None


def test_rollback_is_recorded_as_adverse() -> None:
    entry = _entry()
    entry["rollback_succeeded"] = True
    record = _outcome_record(
        entry,
        recorded_at=datetime(2026, 7, 15, tzinfo=UTC),
    )
    assert record is not None
    assert record.was_rolled_back is True


def test_outcome_at_future_skew_boundary_is_eligible() -> None:
    recorded_at = datetime(2026, 7, 15, tzinfo=UTC)
    entry = _entry()
    entry["observed_at"] = (recorded_at + timedelta(minutes=5)).isoformat()

    assert _outcome_record(entry, recorded_at=recorded_at) is not None


def test_outcome_beyond_future_skew_is_not_eligible() -> None:
    recorded_at = datetime(2026, 7, 15, tzinfo=UTC)
    entry = _entry()
    entry["observed_at"] = (recorded_at + timedelta(minutes=5, seconds=1)).isoformat()

    assert _outcome_record(entry, recorded_at=recorded_at) is None


def test_naive_outcome_timestamp_is_not_eligible() -> None:
    entry = _entry()
    entry["observed_at"] = "2026-07-15T00:00:00"

    assert _outcome_record(entry, recorded_at=datetime(2026, 7, 15, tzinfo=UTC)) is None


def test_latest_outcome_rows_keep_only_highest_sequence_per_action() -> None:
    first = _entry()
    correction = {**_entry(), "verification_passed": False}
    independent = {**_entry(), "action_id": "action-2"}
    rows = [
        {"seq": 1, "entry": first},
        {"seq": 2, "entry": correction},
        {"seq": 3, "entry": independent},
    ]

    assert [row["seq"] for row in _latest_outcome_rows(rows)] == [2, 3]


async def test_outcome_source_advances_watermark_over_superseded_rows(
    monkeypatch,
) -> None:
    recorded_at = datetime(2026, 7, 15, tzinfo=UTC)
    rows = [
        {"seq": 1, "entry": _entry(), "created_at": recorded_at},
        {
            "seq": 2,
            "entry": {**_entry(), "verification_passed": False},
            "created_at": recorded_at,
        },
        {
            "seq": 3,
            "entry": {**_entry(), "action_id": "action-2"},
            "created_at": recorded_at,
        },
    ]
    store = InMemoryStateStore()
    source = PostgresVerifiedOutcomeSource(dsn="postgresql://example", state_store=store)
    monkeypatch.setattr(source, "_rows", AsyncMock(return_value=rows))

    records = [record async for record in source.outcomes()]

    assert [(record.action_id, record.was_verified) for record in records] == [
        ("action-1", False),
        ("action-2", True),
    ]
    assert await store.read_state("measurement:pattern_growth:watermark") == {"seq": 3}
