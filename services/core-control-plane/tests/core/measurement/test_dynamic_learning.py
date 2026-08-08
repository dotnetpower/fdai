"""Audit-driven Dynamic challenger learning runner."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

from fdai.core.assurance_twin.model_registry import RegistryUpdate
from fdai.core.measurement.runners import DynamicLearningRunner
from fdai.shared.contracts.models import ResponseOutcome
from fdai.shared.providers.testing.state_store import InMemoryStateStore

_NOW = datetime(2026, 7, 30, tzinfo=UTC)


def _outcome(index: int) -> ResponseOutcome:
    return ResponseOutcome.model_validate(
        {
            "schema_version": "1.0.0",
            "outcome_id": f"00000000-0000-0000-0000-{index:012d}",
            "idempotency_key": f"response-outcome:{index}",
            "action_id": f"00000000-0000-0000-0001-{index:012d}",
            "event_id": f"00000000-0000-0000-0002-{index:012d}",
            "action_type_id": "ops.scale-out",
            "target_digest": "0" * 64,
            "prediction_id": f"prediction-{index}",
            "metric": "latency_p99_ms",
            "expected_min": 90.0,
            "expected_max": 110.0,
            "observed_value": 100.0,
            "predicted_at": _NOW,
            "observation_deadline": _NOW + timedelta(minutes=5),
            "observed_at": _NOW + timedelta(minutes=1),
            "label": "verified",
            "verification_status": "verified",
            "verification_reason": "within_acceptable_range",
            "execution_mode": "shadow",
            "execution_outcome": "published",
            "decision": "auto",
            "evidence_refs": [f"effect:prediction-{index}"],
            "recorded_at": _NOW + timedelta(minutes=2),
        }
    )


class _Source:
    async def _iterate(self) -> AsyncIterator[ResponseOutcome]:
        yield _outcome(1)
        yield _outcome(2)

    def outcomes(self) -> AsyncIterator[ResponseOutcome]:
        return self._iterate()


class _Registry:
    async def update_from_outcome(self, outcome: ResponseOutcome) -> RegistryUpdate:
        accepted = str(outcome.outcome_id).endswith("000000000001")
        return RegistryUpdate(
            accepted,
            "challenger_updated" if accepted else "challenger_not_registered",
        )


async def test_dynamic_learning_runner_audits_acceptance_and_rejections() -> None:
    store = InMemoryStateStore()
    report = await DynamicLearningRunner(
        outcome_source=_Source(),
        registry=_Registry(),
        audit_store=store,
        clock=lambda: _NOW,
    ).run_once()

    assert report.total_outcomes == 2
    assert report.accepted_count == 1
    assert report.rejected_count == 1
    assert report.reasons == (
        ("challenger_not_registered", 1),
        ("challenger_updated", 1),
    )
    entry = tuple(store.audit_entries)[0]["entry"]
    assert entry["producer_principal"] == "Norns"
    assert entry["mode"] == "shadow"
