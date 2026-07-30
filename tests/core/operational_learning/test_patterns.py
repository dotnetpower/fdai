from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from fdai.core.operational_learning import pattern_case_from_response_outcome
from fdai.shared.contracts.models import ResponseOutcome

_NOW = datetime(2026, 7, 31, tzinfo=UTC)


def _outcome(*, label: str, mode: str) -> ResponseOutcome:
    observed = label != "unscorable"
    return ResponseOutcome.model_validate(
        {
            "schema_version": "1.0.0",
            "outcome_id": UUID("00000000-0000-0000-0000-000000000101"),
            "idempotency_key": "response-outcome:test-101",
            "action_id": UUID("00000000-0000-0000-0000-000000000102"),
            "event_id": UUID("00000000-0000-0000-0000-000000000103"),
            "action_type_id": "ops.scale-out",
            "target_digest": "a" * 64,
            "prediction_id": "prediction-1",
            "metric": "availability",
            "expected_min": 0.99,
            "expected_max": 1.0,
            "observed_value": 0.995 if observed else None,
            "predicted_at": _NOW,
            "observation_deadline": _NOW + timedelta(minutes=5),
            "observed_at": _NOW + timedelta(minutes=1) if observed else None,
            "label": label,
            "verification_status": (
                "verified" if label == "verified" else "mismatch" if observed else "hold"
            ),
            "verification_reason": "test-evidence",
            "execution_mode": mode,
            "execution_outcome": "succeeded",
            "decision": "auto",
            "evidence_refs": ["effect:prediction-1"],
            "recorded_at": _NOW + timedelta(minutes=2),
        }
    )


def test_only_verified_enforce_outcome_is_reusable() -> None:
    case = pattern_case_from_response_outcome(_outcome(label="verified", mode="enforce"))

    assert case is not None
    assert case.reusable is True


def test_mismatch_is_negative_evidence() -> None:
    case = pattern_case_from_response_outcome(_outcome(label="mismatch", mode="shadow"))

    assert case is not None
    assert case.reusable is False


def test_shadow_success_and_unscorable_outcome_are_held() -> None:
    assert pattern_case_from_response_outcome(_outcome(label="verified", mode="shadow")) is None
    assert pattern_case_from_response_outcome(_outcome(label="unscorable", mode="shadow")) is None
