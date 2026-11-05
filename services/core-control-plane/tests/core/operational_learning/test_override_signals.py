from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.operational_learning import (
    OverrideAuditPage,
    OverrideDiscoverySignalSource,
    OverrideSignalThresholds,
)

_START = datetime(2026, 8, 1, tzinfo=UTC)


class _Reader:
    def __init__(self, records: tuple[dict[str, object], ...], *, complete: bool = True) -> None:
        self.records = records
        self.complete = complete

    async def list_override_resolutions(
        self,
        *,
        window_start: datetime,
        window_end: datetime,
        limit: int,
    ) -> OverrideAuditPage:
        del window_start, window_end, limit
        return OverrideAuditPage(records=self.records, complete=self.complete)


def _record(index: int, *, scope: str | None = None) -> dict[str, object]:
    return {
        "action_kind": "governance.override_resolved",
        "event_id": f"event-{index}",
        "idempotency_key": f"event-{index}",
        "rule_id": "rule.example",
        "override_id": f"override-{index % 3}",
        "override_scope": scope or f"scope://org/account/rg-{index % 3}",
        "override_mode": "disabled" if index % 2 else "parameter-relaxation",
        "recorded_at": (_START + timedelta(days=index)).isoformat(),
    }


async def test_override_source_emits_only_after_all_thresholds_clear() -> None:
    source = OverrideDiscoverySignalSource(
        reader=_Reader(tuple(_record(index) for index in range(5))),
        thresholds=OverrideSignalThresholds(
            min_distinct_scopes=3,
            min_dwell_days=4,
            min_shadow_hits=5,
        ),
    )

    batch = await source.observe(
        window_start=_START,
        window_end=_START + timedelta(days=10),
        limit=10,
    )

    assert batch.complete is True
    assert len(batch.signals) == 1
    signal = batch.signals[0]
    assert signal.kind.value == "override"
    assert signal.facts["distinct_scope_count"] == 3
    assert signal.facts["dwell_days"] == 4
    assert signal.facts["shadow_hit_count"] == 5
    assert all(ref.startswith("audit:sha256:") for ref in signal.evidence_refs)


@pytest.mark.parametrize(
    "thresholds",
    [
        OverrideSignalThresholds(min_distinct_scopes=4, min_dwell_days=4, min_shadow_hits=5),
        OverrideSignalThresholds(min_distinct_scopes=3, min_dwell_days=5, min_shadow_hits=5),
        OverrideSignalThresholds(min_distinct_scopes=3, min_dwell_days=4, min_shadow_hits=6),
    ],
)
async def test_override_source_holds_when_any_threshold_is_missing(
    thresholds: OverrideSignalThresholds,
) -> None:
    source = OverrideDiscoverySignalSource(
        reader=_Reader(tuple(_record(index) for index in range(5))),
        thresholds=thresholds,
    )

    batch = await source.observe(
        window_start=_START,
        window_end=_START + timedelta(days=10),
        limit=10,
    )

    assert batch.signals == ()


async def test_override_source_preserves_incomplete_reader_state() -> None:
    source = OverrideDiscoverySignalSource(
        reader=_Reader(tuple(_record(index) for index in range(5)), complete=False),
        thresholds=OverrideSignalThresholds(
            min_distinct_scopes=3,
            min_dwell_days=4,
            min_shadow_hits=5,
        ),
    )

    batch = await source.observe(
        window_start=_START,
        window_end=_START + timedelta(days=10),
        limit=10,
    )

    assert batch.complete is False


async def test_override_source_rejects_non_override_audit_records() -> None:
    source = OverrideDiscoverySignalSource(
        reader=_Reader(({"action_kind": "other"},)),
    )

    with pytest.raises(ValueError, match="override-resolution"):
        await source.observe(
            window_start=_START,
            window_end=_START + timedelta(days=1),
            limit=10,
        )


def test_override_thresholds_and_page_validation() -> None:
    with pytest.raises(ValueError, match="thresholds MUST be integers"):
        OverrideSignalThresholds(min_distinct_scopes=True)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="thresholds MUST be positive"):
        OverrideSignalThresholds(min_distinct_scopes=0)
    with pytest.raises(ValueError, match="completeness MUST be boolean"):
        OverrideAuditPage(records=(), complete=1)  # type: ignore[arg-type]


async def test_override_source_validates_window_limit_and_record_fields() -> None:
    source = OverrideDiscoverySignalSource(reader=_Reader((_record(0), _record(1))))
    naive = datetime(2026, 8, 1, 0, 0)

    with pytest.raises(ValueError, match="window MUST be timezone-aware"):
        await source.observe(window_start=naive, window_end=_START, limit=5)
    with pytest.raises(ValueError, match="window MUST be timezone-aware"):
        await source.observe(window_start=_START, window_end=naive, limit=5)
    with pytest.raises(ValueError, match="window and limit MUST be valid"):
        await source.observe(
            window_start=_START + timedelta(days=2),
            window_end=_START,
            limit=5,
        )
    with pytest.raises(ValueError, match="window and limit MUST be valid"):
        await source.observe(window_start=_START, window_end=_START, limit=True)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="window and limit MUST be valid"):
        await source.observe(window_start=_START, window_end=_START, limit=0)
    with pytest.raises(ValueError, match="exceeded its record limit"):
        await source.observe(window_start=_START, window_end=_START, limit=1)

    incomplete_record = _record(0)
    incomplete_record["rule_id"] = ""
    incomplete_source = OverrideDiscoverySignalSource(reader=_Reader((incomplete_record,)))
    with pytest.raises(ValueError, match="audit record is incomplete"):
        await incomplete_source.observe(window_start=_START, window_end=_START, limit=5)

    naive_record = _record(0)
    naive_record["recorded_at"] = "2026-08-01T00:00:00"
    naive_source = OverrideDiscoverySignalSource(reader=_Reader((naive_record,)))
    with pytest.raises(ValueError, match="audit time MUST be timezone-aware"):
        await naive_source.observe(window_start=_START, window_end=_START, limit=5)
