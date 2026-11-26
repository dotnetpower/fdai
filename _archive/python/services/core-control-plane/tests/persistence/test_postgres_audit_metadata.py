"""Unit tests for deterministic PostgreSQL audit metadata normalization."""

from __future__ import annotations

from uuid import UUID

from fdai.delivery.persistence.postgres import (
    _audit_action_kind,
    _audit_actor,
    _audit_event_id,
)


def test_missing_event_id_is_deterministic_and_nonzero() -> None:
    payload = {"idempotency_key": "measurement-run-1", "action_kind": "measurement.run"}

    first = _audit_event_id(payload)
    second = _audit_event_id(payload)

    assert first == second
    assert UUID(first).int != 0


def test_invalid_event_id_falls_back_to_stable_correlation() -> None:
    payload = {"event_id": "not-a-uuid", "correlation_id": "corr-1"}

    assert UUID(_audit_event_id(payload)).int != 0
    assert _audit_event_id(payload) == _audit_event_id(payload)


def test_actor_and_action_kind_use_explicit_fallback_vocabulary() -> None:
    assert _audit_actor({}) == "fdai.system"
    assert _audit_actor({"producer_principal": "Saga"}) == "Saga"
    assert _audit_action_kind({}) == "audit.record"
    assert _audit_action_kind({"kind": "incident.open"}) == "incident.open"
