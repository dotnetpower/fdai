"""Verified audit outcome parsing for pattern growth."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from fdai.core.measurement.pattern_growth import OutcomeRecord
from fdai.core.tiers.t1_lightweight.testing import DeterministicEmbeddingModel
from fdai.delivery.measurement.postgres_growth import (
    PostgresVerifiedOutcomeSource,
    PostgresVerifiedPatternBuilder,
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


def _growth_record() -> OutcomeRecord:
    return OutcomeRecord(
        action_id="action-1",
        action_type_id="ops.scale-out",
        observed_at=datetime(2026, 8, 1, tzinfo=UTC),
        was_auto=True,
        was_verified=True,
        was_rolled_back=False,
    )


async def test_operational_pattern_builder_requires_case_context(monkeypatch) -> None:
    builder = PostgresVerifiedPatternBuilder(
        dsn="postgresql://example",
        embedding_model=DeterministicEmbeddingModel(),
    )
    entry = {
        "embedding_projection": "operational failure",
        "params": {},
        "rule_id": "learned.operational.example",
        "incident_id": "incident-1",
    }
    monkeypatch.setattr(builder, "_entry", AsyncMock(return_value=entry))

    assert await builder.build(_growth_record()) is None


async def test_operational_pattern_builder_preserves_case_context(monkeypatch) -> None:
    builder = PostgresVerifiedPatternBuilder(
        dsn="postgresql://example",
        embedding_model=DeterministicEmbeddingModel(),
    )
    entry = {
        "embedding_projection": "operational failure",
        "params": {},
        "rule_id": "learned.operational.example",
        "incident_id": "incident-1",
        "operational_case": {
            "case_ref": f"case-history:case-a:1:{'a' * 64}",
            "failure_fingerprint": "f" * 64,
            "resource_type": "kubernetes.service",
            "action_type": "ops.scale-out",
            "required_topology_role": "serves",
            "graph_digest": "b" * 64,
            "owner_digest": "c" * 64,
            "evidence_cutoff": "2026-08-01T00:00:00+00:00",
        },
    }
    monkeypatch.setattr(builder, "_entry", AsyncMock(return_value=entry))

    result = await builder.build(_growth_record())

    assert result is not None
    assert result[1].operational_case is not None


async def test_operational_pattern_signature_binds_case_context(monkeypatch) -> None:
    builder = PostgresVerifiedPatternBuilder(
        dsn="postgresql://example",
        embedding_model=DeterministicEmbeddingModel(),
    )
    base = {
        "embedding_projection": "operational failure",
        "params": {"replicas": 3},
        "rule_id": "learned.operational.example",
        "incident_id": "incident-1",
        "operational_case": {
            "case_ref": f"case-history:case-a:1:{'a' * 64}",
            "failure_fingerprint": "f" * 64,
            "resource_type": "kubernetes.service",
            "action_type": "ops.scale-out",
            "required_topology_role": "serves",
            "graph_digest": "b" * 64,
            "owner_digest": "c" * 64,
            "evidence_cutoff": "2026-08-01T00:00:00+00:00",
        },
    }
    changed = {
        **base,
        "operational_case": {
            **base["operational_case"],  # type: ignore[dict-item]
            "case_ref": f"case-history:case-a:2:{'d' * 64}",
        },
    }
    monkeypatch.setattr(builder, "_entry", AsyncMock(side_effect=(base, changed)))

    first = await builder.build(_growth_record())
    second = await builder.build(_growth_record())

    assert first is not None and second is not None
    assert first[1].signature != second[1].signature


async def test_pattern_builder_rejects_non_finite_embedding(monkeypatch) -> None:
    class _NonFiniteEmbedding:
        dim = 384

        async def embed(self, text: str) -> list[float]:
            vector = [0.0] * self.dim
            vector[0] = float("nan")
            return vector

    builder = PostgresVerifiedPatternBuilder(
        dsn="postgresql://example",
        embedding_model=_NonFiniteEmbedding(),
    )
    monkeypatch.setattr(
        builder,
        "_entry",
        AsyncMock(
            return_value={
                "embedding_projection": "operational failure",
                "params": {},
                "rule_id": "legacy.rule",
                "incident_id": "incident-1",
            }
        ),
    )

    with pytest.raises(ValueError, match="MUST be finite"):
        await builder.build(_growth_record())
