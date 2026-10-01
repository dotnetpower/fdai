from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from fdai.agents.mimir import Mimir
from fdai.agents.muninn import Muninn
from fdai.agents.norns import Norns
from fdai.core.learning import RuleCandidateHint
from fdai.core.operational_learning import CatalogReviewPackage, CatalogReviewPublicationReceipt
from fdai.shared.contracts.models import ForecastOutcome
from fdai.shared.providers.testing.state_store import InMemoryStateStore

from tests.agents.test_mimir_catalog_review import _candidate, _compiler
from tests.rule_catalog.test_rule_semantic_generation_events import _valid_result

_NOW = datetime(2026, 9, 1, tzinfo=UTC)


class _PublishingBus:
    def __init__(self, *, cancel_first: bool = False) -> None:
        self.cancel_first = cancel_first
        self.messages: list[tuple[str, str, dict[str, Any]]] = []

    async def publish(self, producer: str, topic: str, payload: dict[str, Any]) -> None:
        self.messages.append((producer, topic, dict(payload)))
        if self.cancel_first:
            self.cancel_first = False
            raise asyncio.CancelledError


async def test_muninn_projection_cas_failure_retries_from_fresh_read() -> None:
    class _FailFirstCas(InMemoryStateStore):
        def __init__(self) -> None:
            super().__init__()
            self.failed = False

        async def compare_and_set_state_with_audit(self, *args: Any, **kwargs: Any) -> bool:
            if not self.failed:
                self.failed = True
                return False
            return await super().compare_and_set_state_with_audit(*args, **kwargs)

    store = _FailFirstCas()
    muninn = Muninn(durable_state_store=store)
    record = {"idempotency_key": "turn-1", "correlation_id": "corr-1", "digest": "a" * 64}

    await muninn._sync_projection_record("conversation_turns", "turn-1", record)
    await muninn._sync_projection_record("conversation_turns", "turn-1", record)

    stored = await store.read_state(
        "pantheon/muninn/conversation-projections/conversation_turns/turn-1"
    )
    assert stored is not None
    assert stored["revision"] == 2
    assert muninn.behavior_snapshot()["conversation_projection:cas_retry"] == 1


async def test_muninn_pending_outbox_replays_after_cancelled_publish() -> None:
    store = InMemoryStateStore()
    muninn = Muninn(durable_state_store=store)
    bus = _PublishingBus(cancel_first=True)
    muninn.bind_bus(bus)  # type: ignore[arg-type]
    payload = {
        "producer_principal": "Muninn",
        "kind": "semantic_retrieval_failure",
        "correlation_id": "corr-outbox",
        "idempotency_key": "semantic-feedback:candidate-1",
    }

    with pytest.raises(asyncio.CancelledError):
        await muninn._publish_with_outbox(
            "pantheon/muninn/operational-outbox/test/candidate-1",
            "object.context-index",
            payload,
        )
    await muninn._publish_with_outbox(
        "pantheon/muninn/operational-outbox/test/candidate-1",
        "object.context-index",
        payload,
    )

    assert [message[2]["idempotency_key"] for message in bus.messages] == [
        "semantic-feedback:candidate-1",
        "semantic-feedback:candidate-1",
    ]
    outbox = await store.read_state("pantheon/muninn/operational-outbox/test/candidate-1")
    assert outbox is not None and outbox["state"] == "published"


async def test_muninn_case_history_retention_times_out_visibly() -> None:
    class _BlockedRetention:
        async def delete_due(self, **_values: object) -> tuple[str, ...]:
            await asyncio.Event().wait()
            return ()

    muninn = Muninn(
        case_history_retention=_BlockedRetention(),  # type: ignore[arg-type]
        provider_timeout_seconds=0.01,
    )

    with pytest.raises(TimeoutError):
        await muninn._apply_case_history_retention(
            {
                "source": "case-history-retention-scheduler",
                "event_id": "case-history-retention:event",
                "idempotency_key": "case-history-retention:key",
                "correlation_id": "case-history-retention:corr",
            }
        )

    assert muninn.behavior_snapshot()["case_history:retention_timeout"] == 1


async def test_mimir_same_key_lock_does_not_block_unrelated_candidate() -> None:
    class _BlockingPublisher:
        def __init__(self) -> None:
            self.first_started = asyncio.Event()
            self.release_first = asyncio.Event()
            self.packages: list[CatalogReviewPackage] = []

        async def publish(
            self,
            package: CatalogReviewPackage,
        ) -> CatalogReviewPublicationReceipt:
            self.packages.append(package)
            if len(self.packages) == 1:
                self.first_started.set()
                await self.release_first.wait()
            return CatalogReviewPublicationReceipt(
                package_digest=package.content_digest,
                review_ref=f"catalog-review:{len(self.packages)}",
                already_existed=False,
            )

    publisher = _BlockingPublisher()
    mimir = Mimir(catalog_candidate_compiler=_compiler(), catalog_review_publisher=publisher)
    mimir.bind_bus(_PublishingBus())  # type: ignore[arg-type]
    first = _candidate(0)
    second = _candidate(1)

    first_task = asyncio.create_task(mimir.on_typed_message("object.rule-candidate", first))
    await publisher.first_started.wait()
    await asyncio.wait_for(mimir.on_typed_message("object.rule-candidate", second), timeout=1)
    publisher.release_first.set()
    await first_task

    assert len(publisher.packages) == 2


async def test_mimir_activation_command_publish_times_out_visibly() -> None:
    class _BlockedBinder:
        async def bind_validation_result(self, _result: object) -> None:
            return None

        async def active_generation_identity(self, _corpus: object) -> None:
            return None

        async def publish_command(self, _command: object) -> None:
            await asyncio.Event().wait()

    mimir = Mimir(provider_timeout_seconds=0.01)
    mimir.bind_rule_generation_state_store(InMemoryStateStore())
    mimir.bind_rule_generation_activation_binder(_BlockedBinder())  # type: ignore[arg-type]

    with pytest.raises(TimeoutError):
        await mimir._publish_rule_generation_activation_command(_valid_result())

    assert mimir.behavior_snapshot()["rule_generation_activation_command_timeout"] == 1


def _forecast_payload() -> dict[str, Any]:
    outcome = ForecastOutcome.model_validate(
        {
            "schema_version": "1.0.0",
            "outcome_id": UUID(int=1),
            "idempotency_key": "forecast-outcome-1",
            "correlation_id": "corr-forecast",
            "prediction_id": UUID(int=2),
            "detector_id": "capacity-linear",
            "detector_version": "1.0.0",
            "access_scope_digest": "a" * 64,
            "target_digest": "b" * 64,
            "metric": "cpu",
            "feature_cutoff": _NOW,
            "horizon_started_at": _NOW,
            "horizon_ended_at": _NOW + timedelta(hours=1),
            "direction": "rising",
            "threshold": 90.0,
            "predicted_value": 95.0,
            "interval_lower": 90.0,
            "interval_upper": 99.0,
            "observed_value": 70.0,
            "actual_breach_at": None,
            "label": "false_positive",
            "evidence_refs": ["metric-window:1"],
            "telemetry_completeness": "complete",
            "closed_at": _NOW + timedelta(hours=2),
            "mode": "shadow",
        }
    )
    return {
        "producer_principal": "Muninn",
        "kind": "forecast_case_history",
        "correlation_id": "forecast-case-1",
        "idempotency_key": "forecast-case-1",
        "case_id": "case-1",
        "revision": 1,
        "manifest_digest": "c" * 64,
        "detector_id": outcome.detector_id,
        "metric": outcome.metric,
        "outcome_label": outcome.label.value,
        "case_ref": "case-history:case-1:1:" + "c" * 64,
    }


async def test_norns_cancelled_forecast_analysis_retries_case_revision() -> None:
    class _BlockingAnalyzer:
        def __init__(self) -> None:
            self.started = asyncio.Event()

        async def analyze(self, _payload: dict[str, Any]) -> RuleCandidateHint:
            self.started.set()
            await asyncio.Event().wait()
            raise AssertionError("unreachable")

    analyzer = _BlockingAnalyzer()
    norns = Norns(forecast_error_threshold=1, case_history_analyzer=analyzer)
    task = asyncio.create_task(norns.on_typed_message("object.context-index", _forecast_payload()))
    await analyzer.started.wait()
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    norns._case_history_analyzer = None

    await norns.on_typed_message("object.context-index", _forecast_payload())

    assert norns.pending_candidates[0]["source_signal"] == "forecast_case_history"
    assert "forecast_case:duplicate" not in norns.behavior_snapshot()
