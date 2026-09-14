"""Trial state cannot renew through restart, upgrades, malformed input or clock rollback."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.licensing.trial import TRIAL_DURATION, TrialRecord, TrialStatus

START = datetime(2026, 9, 14, tzinfo=UTC)


def _record() -> TrialRecord:
    return TrialRecord("a" * 64, "b" * 64, START, START)


def test_trial_has_exact_30_day_window() -> None:
    record = _record()
    assert record.expires_at == START + timedelta(days=30)
    assert (
        record.observe(now=record.expires_at - timedelta(microseconds=1)).status
        is TrialStatus.ACTIVE
    )
    assert record.observe(now=record.expires_at).status is TrialStatus.EXPIRED


def test_restart_preserves_activation_and_advances_revision() -> None:
    previous = _record().observe(now=START + timedelta(days=2))
    restarted = TrialRecord.from_mapping(previous.to_mapping())
    current = restarted.observe(now=START + timedelta(days=3))
    assert current.activated_at == START
    assert current.expires_at == previous.expires_at
    assert current.revision == previous.revision + 1
    assert "image_digest" not in current.to_mapping()
    assert "source_commit" not in current.to_mapping()


def test_clock_rollback_cannot_reactivate_trial() -> None:
    previous = _record().observe(now=START + timedelta(days=3))
    blocked = previous.observe(now=START + timedelta(days=2))
    assert blocked.status is TrialStatus.CLOCK_BLOCKED
    assert blocked.last_observed_at == previous.last_observed_at
    assert blocked.observe(now=START + timedelta(days=4)).status is TrialStatus.CLOCK_BLOCKED


def test_expired_trial_cannot_be_reset_by_backdated_time() -> None:
    expired = _record().observe(now=START + TRIAL_DURATION)
    assert expired.observe(now=START).status is TrialStatus.CLOCK_BLOCKED
    assert expired.activated_at == START


@pytest.mark.parametrize(
    "field,value",
    [
        ("revision", True),
        ("revision", 0),
        ("clock_blocked", 1),
        ("deployment_binding", "invalid"),
        ("expires_at", START.isoformat()),
        ("activated_at", "2026-09-14T00:00:00"),
        ("activated_at", "2026-09-14T00:00:00Z"),
    ],
)
def test_invalid_durable_record_is_not_repaired(field: str, value: object) -> None:
    payload = _record().to_mapping()
    payload[field] = value
    with pytest.raises(ValueError):
        TrialRecord.from_mapping(payload)


def test_non_utc_observation_and_pre_activation_state_are_rejected() -> None:
    with pytest.raises(ValueError, match="UTC"):
        _record().observe(now=START.replace(tzinfo=None))
    with pytest.raises(ValueError, match="precede"):
        replace(_record(), last_observed_at=START - timedelta(seconds=1))
