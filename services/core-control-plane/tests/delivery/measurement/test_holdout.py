from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from fdai.core.measurement.pattern_growth import (
    OutcomeRecord,
    TemporalHoldoutConfig,
    TemporalHoldoutValidator,
)
from fdai.core.tiers.t1_lightweight.tier import LearnedAction
from fdai.delivery.measurement.holdout import (
    HoldoutVerifiedPatternBuilder,
    StateStoreTemporalHoldoutEvidenceSource,
)
from fdai.shared.providers.testing.state_store import InMemoryStateStore

_OBSERVED_AT = datetime(2026, 8, 1, tzinfo=UTC)


class _Builder:
    async def build(
        self,
        _record: OutcomeRecord,
    ) -> tuple[Sequence[float], LearnedAction]:
        return (
            (0.1, 0.2),
            LearnedAction(
                signature="pattern-1",
                rule_id="rule-1",
                action_type="remediate.tag-add",
                params={},
                incident_id="incident-1",
                success_rate=0.0,
                reuse_count=0,
            ),
        )


def _record() -> OutcomeRecord:
    return OutcomeRecord(
        action_id="action-1",
        action_type_id="remediate.tag-add",
        observed_at=_OBSERVED_AT,
        was_auto=True,
        was_verified=True,
        was_rolled_back=False,
    )


async def _builder(store: InMemoryStateStore) -> HoldoutVerifiedPatternBuilder:
    return HoldoutVerifiedPatternBuilder(
        delegate=_Builder(),
        evidence_source=StateStoreTemporalHoldoutEvidenceSource(store),
        validator=TemporalHoldoutValidator(
            config=TemporalHoldoutConfig(min_samples=2, fp_rate_ceiling=0.5)
        ),
        audit_store=store,
    )


async def test_complete_passing_holdout_releases_shadow_candidate() -> None:
    store = InMemoryStateStore()
    await store.write_state(
        "measurement:pattern_holdout:pattern-1",
        {
            "pattern_id": "pattern-1",
            "complete": True,
            "samples": [
                {
                    "pattern_id": "pattern-1",
                    "observed_at": (_OBSERVED_AT + timedelta(days=1)).isoformat(),
                    "was_correct": True,
                },
                {
                    "pattern_id": "pattern-1",
                    "observed_at": (_OBSERVED_AT + timedelta(days=2)).isoformat(),
                    "was_correct": True,
                },
            ],
        },
    )

    built = await (await _builder(store)).build(_record())

    assert built is not None
    entry = store.audit_entries[-1]["entry"]
    assert entry["outcome"] == "pass"
    assert entry["evidence_complete"] is True
    assert entry["promotion_authority"] is False


async def test_incomplete_holdout_is_audited_and_kept_inert() -> None:
    store = InMemoryStateStore()

    built = await (await _builder(store)).build(_record())

    assert built is None
    entry = store.audit_entries[-1]["entry"]
    assert entry["outcome"] == "insufficient_data"
    assert entry["evidence_complete"] is False


async def test_complete_failed_holdout_is_audited_and_kept_inert() -> None:
    store = InMemoryStateStore()
    await store.write_state(
        "measurement:pattern_holdout:pattern-1",
        {
            "pattern_id": "pattern-1",
            "complete": True,
            "samples": [
                {
                    "pattern_id": "pattern-1",
                    "observed_at": (_OBSERVED_AT + timedelta(days=1)).isoformat(),
                    "was_correct": False,
                },
                {
                    "pattern_id": "pattern-1",
                    "observed_at": (_OBSERVED_AT + timedelta(days=2)).isoformat(),
                    "was_correct": False,
                },
            ],
        },
    )

    built = await (await _builder(store)).build(_record())

    assert built is None
    entry = store.audit_entries[-1]["entry"]
    assert entry["outcome"] == "fail_fp_rate"
    assert entry["evidence_complete"] is True


async def test_malformed_holdout_is_audited_without_releasing_candidate() -> None:
    store = InMemoryStateStore()
    await store.write_state(
        "measurement:pattern_holdout:pattern-1",
        {
            "pattern_id": "different-pattern",
            "complete": True,
            "samples": [],
        },
    )

    built = await (await _builder(store)).build(_record())

    assert built is None
    entry = store.audit_entries[-1]["entry"]
    assert entry["reason"] == "holdout_evidence_invalid"
    assert entry["promotion_authority"] is False
