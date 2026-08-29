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
