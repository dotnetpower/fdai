from copy import deepcopy
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from fdai.delivery.canary_cli import build_canary_event
from fdai.delivery.canary_sequence import MAX_CANARY_AUDITS, consumed_canary_sequence
from fdai.delivery.self_health_canary import _validated_recorded_at
from fdai.shared.providers.audit_hash import GENESIS_HASH, next_hash
from fdai.shared.providers.self_health import SelfHealthExporterUnavailableError

NOW = datetime(2026, 10, 21, 6, 0, tzinfo=UTC)
BASE = NOW - timedelta(seconds=60)
SLOT = "aks-job:00000000-0000-0000-0000-000000000001"


def facts(*outcomes: str, base: datetime = BASE) -> tuple[dict[str, Any], ...]:
    event = build_canary_event(slot=SLOT, now=base)
    rows: list[dict[str, Any]] = []
    previous = GENESIS_HASH
    for attempt, outcome in enumerate(outcomes, 1):
        started = base + timedelta(seconds=attempt * 2)
        for phase in ("started", outcome):
            if phase == "pending":
                continue
            at = started + timedelta(seconds=int(phase != "started"))
            entry = {
                "actor": "fdai.canary-job",
                "action_kind": (
                    "control_loop.canary" if phase == "success" else "control_loop.canary.attempt"
                ),
                "tier": "canary",
                "decision": "no-op",
                "outcome": phase,
                "event_id": str(event.event_id),
                "correlation_id": event.correlation_id,
                "idempotency_key": event.idempotency_key,
                "mode": "shadow",
                "detected_at": base.isoformat(),
                "attempt_id": str(UUID(int=attempt)),
                "started_at": started.isoformat(),
                "recorded_at": at.isoformat(),
            }
            if phase == "success":
                entry["latency_ms"] = int((at - base).total_seconds() * 1000)
            elif phase in {"failure", "cancelled"}:
                entry["error_type"] = "CancelledError" if phase == "cancelled" else "RuntimeError"
            digest = next_hash(previous, entry)
            rows.append(
                {
                    "seq": len(rows) + 1,
                    **{
                        name: entry[name]
                        for name in ("actor", "action_kind", "event_id", "correlation_id", "mode")
                    },
                    "entry": entry,
                    "previous_hash": previous,
                    "entry_hash": digest,
                }
            )
            previous = digest
    return tuple(rows)


@pytest.mark.parametrize("outcome", ["success", "failure", "cancelled"])
def test_complete_sequence_preserves_the_exact_terminal(outcome: str) -> None:
    rows = facts(outcome)
    result = consumed_canary_sequence(rows, slot=SLOT, truncated=False, now=NOW)
    assert result.outcome == outcome
    if outcome == "cancelled":
        with pytest.raises(SelfHealthExporterUnavailableError) as failure:
            _ = result.value
        assert failure.value.reason == "source_incomplete"
    else:
        assert result.value == Decimal(int(outcome == "success"))
    assert result.observed_at == BASE + timedelta(seconds=3)
    assert result.sequence_digest.startswith("sha256:") and len(result.sequence_digest) == 71
    assert result == consumed_canary_sequence(deepcopy(rows), slot=SLOT, truncated=False, now=NOW)


@pytest.mark.parametrize("outcome", ["success", "failure", "cancelled"])
def test_a_retry_has_its_own_start_and_never_reuses_an_earlier_success(outcome: str) -> None:
    result = consumed_canary_sequence(
        facts("success", outcome), slot=SLOT, truncated=False, now=NOW
    )
    assert result.outcome == outcome
    assert result.observed_at == BASE + timedelta(seconds=5)
    assert (
        result.sequence_digest
        != consumed_canary_sequence(
            facts(outcome), slot=SLOT, truncated=False, now=NOW
        ).sequence_digest
    )


@pytest.mark.parametrize(
    ("rows", "truncated", "reason"),
    [
        ((), False, "source_missing"),
        (facts("success"), True, "source_incomplete"),
        (facts("success") * (MAX_CANARY_AUDITS + 1), False, "source_incomplete"),
        (facts("pending"), False, "source_incomplete"),
        (facts("success", "pending"), False, "source_incomplete"),
        (facts("success")[1:], False, "source_malformed"),
        (tuple(reversed(facts("success"))), False, "source_malformed"),
        ((facts("pending")[0], facts("success", "pending")[-1]), False, "source_malformed"),
    ],
)
def test_missing_incomplete_truncated_and_overlapping_sequences_never_pass(
    rows: tuple[dict[str, Any], ...], truncated: bool, reason: str
) -> None:
    with pytest.raises(SelfHealthExporterUnavailableError) as failure:
        consumed_canary_sequence(rows, slot=SLOT, truncated=truncated, now=NOW)
    assert failure.value.reason == reason


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("attempt_id", None),
        ("attempt_id", str(UUID(int=0))),
        ("attempt_id", "not-an-attempt"),
        ("started_at", BASE.isoformat()),
        ("started_at", BASE.replace(tzinfo=None).isoformat()),
        ("outcome", "healthy"),
        ("actor", "not-the-canary"),
        ("mode", "not-a-mode"),
        ("latency_ms", True),
        ("latency_ms", 0),
    ],
)
def test_even_rehashed_malformed_terminal_facts_are_rejected(field: str, value: object) -> None:
    rows = facts("success")
    rows[-1]["entry"][field] = value
    rows[-1]["entry_hash"] = next_hash(rows[-1]["previous_hash"], rows[-1]["entry"])
    with pytest.raises(SelfHealthExporterUnavailableError) as failure:
        consumed_canary_sequence(rows, slot=SLOT, truncated=False, now=NOW)
    assert failure.value.reason == "source_malformed"


def test_a_different_native_execution_cannot_borrow_this_sequence() -> None:
    with pytest.raises(SelfHealthExporterUnavailableError) as failure:
        consumed_canary_sequence(
            facts("success"),
            slot="aks-job:00000000-0000-0000-0000-000000000002",
            truncated=False,
            now=NOW,
        )
    assert failure.value.reason == "source_malformed"


@pytest.mark.parametrize("outcome", ["failure", "cancelled"])
@pytest.mark.parametrize("error_type", [None, "", True, "private provider detail"])
def test_interruption_requires_a_bounded_error_class_not_raw_provider_text(
    outcome: str, error_type: object
) -> None:
    rows = facts(outcome)
    rows[-1]["entry"]["error_type"] = error_type
    rows[-1]["entry_hash"] = next_hash(rows[-1]["previous_hash"], rows[-1]["entry"])
    with pytest.raises(SelfHealthExporterUnavailableError) as failure:
        consumed_canary_sequence(rows, slot=SLOT, truncated=False, now=NOW)
    assert failure.value.reason == "source_malformed"


def test_a_future_terminal_cannot_be_reported_as_current() -> None:
    with pytest.raises(SelfHealthExporterUnavailableError) as failure:
        consumed_canary_sequence(facts("success"), slot=SLOT, truncated=False, now=BASE)
    assert failure.value.reason == "source_from_future"


def test_legacy_success_remains_an_age_observation_but_not_a_complete_sequence() -> None:
    row = facts("success")[-1]
    del row["entry"]["attempt_id"]
    del row["entry"]["started_at"]
    row["entry_hash"] = next_hash(row["previous_hash"], row["entry"])
    assert _validated_recorded_at(row) == BASE + timedelta(seconds=3)
    with pytest.raises(SelfHealthExporterUnavailableError) as failure:
        consumed_canary_sequence((row,), slot=SLOT, truncated=False, now=NOW)
    assert failure.value.reason == "source_malformed"
