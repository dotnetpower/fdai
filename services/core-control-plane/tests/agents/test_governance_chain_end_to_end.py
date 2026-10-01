from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fdai.agents._framework import bragi_publication as bragi_publication_module
from fdai.agents._framework.adapters import InMemoryGithubIssueAdapter, InMemoryStateStore
from fdai.agents._framework.bragi_publication import _publication_key
from fdai.agents._framework.bus import InMemoryBus
from fdai.agents._framework.registry import load_pantheon
from fdai.agents._framework.runtime import PantheonRuntime
from fdai.agents.bragi import Bragi
from fdai.agents.mimir import Mimir
from fdai.agents.norns import Norns
from fdai.agents.saga import Saga
from fdai.core.learning import PostTurnReviewInput
from fdai.shared.providers.local.event_bus import LocalEventBus
from fdai.shared.providers.testing.state_store import InMemoryStateStore as DurableStateStore

from tests.agents.semantic_judgment_support import semantic_test_boundary

_RAW_TOPIC = "fdai.events.gs2"
_NOW = datetime(2026, 10, 1, tzinfo=UTC)


def _bus() -> InMemoryBus:
    return InMemoryBus(registry=load_pantheon(), isolate_handlers=False)


async def _run_until(runtime: PantheonRuntime, predicate, *, steps: int = 2000) -> None:  # type: ignore[no-untyped-def]
    run_task = asyncio.create_task(runtime.run())
    try:
        for _ in range(steps):
            await asyncio.sleep(0)
            if predicate():
                return
        raise AssertionError("runtime condition was not observed")
    finally:
        await runtime.stop()
        run_task.cancel()
        try:
            await run_task
        except (asyncio.CancelledError, Exception):  # noqa: S110 - cleanup path
            pass


def test_saga_forecast_outcome_audit_is_idempotently_fenced() -> None:
    saga = Saga()
    bus = _bus()
    saga.bind_bus(bus)
    payload = {
        "producer_principal": "Heimdall",
        "correlation_id": "forecast-corr",
        "idempotency_key": "forecast-outcome:source",
        "outcome_id": "outcome-1",
        "prediction_id": "prediction-1",
        "detector_id": "forecast.detector",
    }

    asyncio.run(saga.on_typed_message("object.forecast-outcome", payload))
    asyncio.run(saga.on_typed_message("object.forecast-outcome", payload))

    audits = bus.messages_on("object.audit-entry")
    assert len(audits) == 1
    assert audits[0].payload["idempotency_key"].startswith("audit-entry:forecast-outcome:")


def test_saga_audits_retained_normalized_ingress_event() -> None:
    saga = Saga()
    payload = {
        "producer_principal": "Huginn",
        "correlation_id": "ingress-corr",
        "idempotency_key": "event:retained",
        "event_type": "cloud.resource.alert",
        "resource_id": "resource-1",
    }

    asyncio.run(saga.on_typed_message("object.event", payload))

    entries = saga.audit_chain.entries_for_correlation("ingress-corr")
    assert len(entries) == 1
    assert saga.behavior_snapshot()["ingress_retention:audit_recorded"] == 1


def test_saga_legacy_handoff_deduplicates_by_problem_fingerprint() -> None:
    saga = Saga(github=InMemoryGithubIssueAdapter())
    saga.bind_bus(_bus())
    first = _legacy_handoff("handoff-a", "handoff-a")
    second = _legacy_handoff("handoff-b", "handoff-b")

    asyncio.run(saga.on_typed_message("object.handoff-escalation", first))
    asyncio.run(saga.on_typed_message("object.handoff-escalation", second))

    assert len(saga.github.issues) == 1
    assert saga.behavior_snapshot()["handoff:legacy_fingerprint_computed"] == 2


def test_saga_recovers_handoff_issue_publication_from_checkpoint() -> None:
    local_store = InMemoryStateStore()
    github = InMemoryGithubIssueAdapter()
    first = Saga(state_store=local_store, github=github)
    first.bind_bus(_bus())
    payload = _legacy_handoff("handoff-recover", "handoff-recover")
    first.bus = None

    try:
        asyncio.run(first.on_typed_message("object.handoff-escalation", payload))
    except RuntimeError as exc:
        assert "publication bus is unavailable" in str(exc)

    restarted = Saga(state_store=local_store, github=github)
    bus = _bus()
    restarted.bind_bus(bus)
    assert asyncio.run(restarted.recover_handoff_issue_publications()) == 1
    assert len(bus.messages_on("object.issue")) == 1


def test_mimir_issue_candidate_count_updates_after_later_candidate() -> None:
    store = DurableStateStore()
    mimir = Mimir(governance_state_store=store)
    mimir.bind_bus(_bus())

    asyncio.run(
        mimir.on_typed_message(
            "object.issue",
            {
                "producer_principal": "Saga",
                "correlation_id": "issue-corr",
                "idempotency_key": "issue:fp-1",
                "fingerprint": "fp-1",
                "issue_number": 7,
                "created": True,
            },
        )
    )
    asyncio.run(mimir.on_typed_message("object.rule-candidate", _rule_candidate("fp-1")))

    rows = asyncio.run(store.read_states("pantheon/mimir/governance/issue-fingerprints", limit=10))
    assert rows[0]["candidate_count"] == 1
    assert mimir.behavior_snapshot()["issue_fingerprint:candidate_count_updated"] == 1


def test_mimir_promotion_retries_publication_after_transient_failure() -> None:
    class FailingBus(InMemoryBus):
        def __init__(self) -> None:
            super().__init__(registry=load_pantheon(), isolate_handlers=False)
            self.fail_once = True

        async def publish(self, principal: str, topic: str, payload: dict[str, Any]) -> None:
            if topic == "object.rule" and self.fail_once:
                self.fail_once = False
                raise RuntimeError("transient")
            await super().publish(principal, topic, payload)

    mimir = Mimir(governance_state_store=DurableStateStore())
    bus = FailingBus()
    mimir.bind_bus(bus)
    reviewed = "catalog-pr:https://git.example.com/fdai/control-plane/pull/1@sha256:" + "a" * 64

    try:
        mimir.promote("static.rule", source="manual", reviewed_change_ref=reviewed)
    except RuntimeError:
        pass
    mimir.promote("static.rule", source="manual", reviewed_change_ref=reviewed)

    assert len(bus.messages_on("object.rule")) == 1
    assert mimir.behavior_snapshot()["promotion:publication_failed"] == 1


def test_mimir_promotion_persistence_failure_blocks_rule_publication() -> None:
    class FailingStore(DurableStateStore):
        async def read_state(self, key: str):  # type: ignore[no-untyped-def]
            if "rules/static.rule" in key:
                raise RuntimeError("durable write unavailable")
            return await super().read_state(key)

    mimir = Mimir(governance_state_store=FailingStore())
    bus = _bus()
    mimir.bind_bus(bus)
    reviewed = "catalog-pr:https://git.example.com/fdai/control-plane/pull/1@sha256:" + "a" * 64

    try:
        mimir.promote("static.rule", source="manual", reviewed_change_ref=reviewed)
    except RuntimeError as exc:
        assert "durable write unavailable" in str(exc)

    assert mimir.status("static.rule") is None
    assert bus.messages_on("object.rule") == []


def test_norns_records_single_issue_learning_as_collecting_signal() -> None:
    norns = Norns(promotion_threshold=3)

    asyncio.run(
        norns.on_typed_message(
            "object.issue",
            {
                "producer_principal": "Saga",
                "correlation_id": "issue-corr",
                "idempotency_key": "issue:fp-collect",
                "fingerprint": "fp-collect",
                "issue_number": 3,
            },
        )
    )

    behavior = norns.behavior_snapshot()
    assert behavior["issue_learning:observed"] == 1
    assert behavior["issue_learning:collecting"] == 1
    assert norns.pending_candidates == []


def test_bragi_proposal_sink_failure_is_audited_through_owned_handoff_topic() -> None:
    bragi = Bragi(
        semantic_judgment=semantic_test_boundary(),
        action_type_names=("ops.restart-service",),
    )
    saga = Saga()
    bus = _bus()
    bragi.bind_bus(bus)
    saga.bind_bus(bus)
    bus.subscribe("object.handoff-escalation", "Saga", saga.on_typed_message)

    async def fail(_proposal: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("sink unavailable")

    bragi.register_proposal_sink(fail)

    turn = asyncio.run(
        bragi.ask(
            session_id="proposal-error",
            user_id="operator",
            question="restart svc-1",
            initiator_role="Contributor",
            allow_action_proposal=True,
        )
    )

    assert turn.answer["abstain_reason"] == "proposal_sink_error"
    assert bragi.behavior_snapshot()["proposal:denial_audited"] == 1
    assert saga.behavior_snapshot()["handoff:operator_proposal_denied_audited"] == 1


def test_bragi_handoff_outbox_recovers_after_transient_publish_failure() -> None:
    class FailingBus(InMemoryBus):
        async def publish(self, principal: str, topic: str, payload: dict[str, Any]) -> None:
            if topic == "object.handoff-escalation":
                raise RuntimeError("transient")
            await super().publish(principal, topic, payload)

    store = DurableStateStore()
    first = Bragi(state_store=store)
    first.bind_bus(FailingBus(registry=load_pantheon(), isolate_handlers=False))

    status = asyncio.run(
        first._publish_handoff(
            session_id="s",
            question="unanswered",
            turn_index=0,
            intent_category="question_unanswered",
            resource_type="service",
            primary_agent="Bragi",
            failure_reason_code="no_route",
        )
    )
    assert status == "publish_failed"

    restarted = Bragi(state_store=store)
    saga = Saga()
    bus = _bus()
    restarted.bind_bus(bus)
    saga.bind_bus(bus)
    bus.subscribe("object.handoff-escalation", "Saga", saga.on_typed_message)
    assert asyncio.run(restarted.recover_bragi_publications()) == 1
    assert len(bus.messages_on("object.issue")) == 1


def test_bragi_post_turn_review_outbox_recovers_once_to_norns() -> None:
    class FailingBus(InMemoryBus):
        async def publish(self, principal: str, topic: str, payload: dict[str, Any]) -> None:
            if topic == "object.post-turn-review":
                raise RuntimeError("transient")
            await super().publish(principal, topic, payload)

    class Coordinator:
        def __init__(self) -> None:
            self.reviews: list[PostTurnReviewInput] = []

        async def review(self, review: PostTurnReviewInput) -> None:
            self.reviews.append(review)

    store = DurableStateStore()
    review = PostTurnReviewInput(
        review_id="review-1",
        principal_scope="sha256:" + "1" * 64,
        operator_turn_id="operator-1",
        assistant_turn_id="assistant-1",
        completed_at=_NOW,
    )
    first = Bragi(state_store=store)
    first.bind_bus(FailingBus(registry=load_pantheon(), isolate_handlers=False))
    try:
        asyncio.run(first.publish_post_turn_review(review))
    except RuntimeError:
        pass

    restarted = Bragi(state_store=store)
    coordinator = Coordinator()
    norns = Norns(post_turn_review=coordinator)
    bus = _bus()
    restarted.bind_bus(bus)
    norns.bind_bus(bus)
    bus.subscribe("object.post-turn-review", "Norns", norns.on_typed_message)
    assert asyncio.run(restarted.recover_bragi_publications()) == 1
    assert len(coordinator.reviews) == 1
    assert asyncio.run(restarted.recover_bragi_publications()) == 0
    assert len(coordinator.reviews) == 1


@pytest.mark.asyncio
async def test_bragi_publication_timeout_releases_claim_before_recovery(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    class SlowBus(InMemoryBus):
        def __init__(self) -> None:
            super().__init__(registry=load_pantheon(), isolate_handlers=False)
            self.accepted = 0
            self.cancelled = 0

        async def publish(self, principal: str, topic: str, payload: dict[str, Any]) -> None:
            if topic == "object.handoff-escalation":
                try:
                    await asyncio.sleep(60)
                except asyncio.CancelledError:
                    self.cancelled += 1
                    raise
                self.accepted += 1
                return
            await super().publish(principal, topic, payload)

    monkeypatch.setattr(
        bragi_publication_module,
        "_BRAGI_PUBLICATION_CLAIM_LEASE",
        timedelta(milliseconds=2),
    )
    store = DurableStateStore()
    payload = {
        "producer_principal": "Bragi",
        "correlation_id": "handoff-slow-timeout",
        "idempotency_key": "handoff:slow-timeout",
        "reason": "operator_handoff",
    }
    bragi = Bragi(state_store=store)
    slow_bus = SlowBus()
    bragi.bind_bus(slow_bus)

    with pytest.raises(TimeoutError):
        await bragi.publish_handoff_event(payload)

    key = _publication_key(payload)
    assert slow_bus.accepted == 0
    assert slow_bus.cancelled == 1
    assert (await store.read_state(key))["status"] == "pending"
    recovered = Bragi(state_store=store)
    bus = _bus()
    recovered.bind_bus(bus)

    assert await recovered.recover_bragi_publications() == 1
    assert len(bus.messages_on("object.handoff-escalation")) == 1
    assert bus.messages_on("object.handoff-escalation")[0].payload["idempotency_key"] == (
        "handoff:slow-timeout"
    )


def test_default_runtime_reports_unbound_post_turn_review_learning_degradation() -> None:
    runtime = PantheonRuntime.build(provider=LocalEventBus(), raw_event_topic=_RAW_TOPIC)
    norns = runtime.agents["Norns"]

    async def drive() -> dict[str, Any]:
        await _run_until(
            runtime,
            lambda: norns.behavior_snapshot().get("post_turn_review_unavailable", 0) == 1,
        )
        return runtime.health()

    async def publish_review() -> None:
        await asyncio.sleep(0)
        await runtime.bridge.publish(
            "Bragi",
            "object.post-turn-review",
            {
                "kind": "post_turn_review",
                "id": "post-turn-review-1",
                "correlation_id": "review-corr",
                "idempotency_key": "post-turn-review:1",
                "review": {"review_id": "review-1"},
            },
        )

    async def scenario() -> dict[str, Any]:
        publisher = asyncio.create_task(publish_review())
        try:
            return await drive()
        finally:
            await publisher

    health = asyncio.run(scenario())
    assert "Norns" in health["degradation"]["unavailable_agents"]
    assert "post_turn_review_unbound" in health["degradation"]["unavailable_sources"]["Norns"]


def _legacy_handoff(escalation_id: str, correlation_id: str) -> dict[str, Any]:
    return {
        "producer_principal": "Bragi",
        "id": escalation_id,
        "escalation_id": escalation_id,
        "correlation_id": correlation_id,
        "idempotency_key": f"handoff:{escalation_id}",
        "emitting_agent": "Bragi",
        "intent_category": "question_unanswered",
        "resource_type": "service",
        "failure_reason_code": "no_route",
        "emitted_at": _NOW.isoformat(),
    }


def _rule_candidate(fingerprint: str) -> dict[str, Any]:
    return {
        "producer_principal": "Norns",
        "correlation_id": "candidate-corr",
        "idempotency_key": "candidate:fp-1",
        "target_rule_id": "rule.fp",
        "proposal_kind": "new",
        "proposed_by": "Norns",
        "source_signal": "handoff_fingerprint",
        "evidence": {"fingerprint": fingerprint, "occurrence_count": 1},
    }
