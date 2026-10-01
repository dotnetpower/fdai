from __future__ import annotations

import asyncio
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from fdai.agents._framework.bragi_publication import handoff_event_payload
from fdai.agents._framework.bus import InMemoryBus
from fdai.agents._framework.mimir_maintenance import (
    MimirCatalogPromotionOutcome,
    MimirDeprecationCandidate,
    MimirRegressionResult,
    MimirRuleSourcePollResult,
)
from fdai.agents._framework.registry import load_pantheon
from fdai.agents._framework.runtime import PantheonRuntime
from fdai.agents._framework.state_store_issue_tracker import StateStoreIssueTrackerAdapter
from fdai.agents.mimir import (
    Mimir,
    _issue_close_evidence_idempotency_key,
    _rule_publication_key,
)
from fdai.agents.norns import Norns
from fdai.agents.saga import Saga
from fdai.shared.providers.testing.event_bus import InMemoryEventBus
from fdai.shared.providers.testing.state_store import InMemoryStateStore


class _PromotionReader:
    def __init__(self) -> None:
        self.outcomes: list[MimirCatalogPromotionOutcome] = []

    async def read_promotion_outcomes(
        self,
        *,
        limit: int,
        now: datetime,
    ) -> Sequence[MimirCatalogPromotionOutcome]:
        return tuple(self.outcomes[:limit])


class _RegressionRunner:
    def __init__(self, *, started_at: datetime) -> None:
        self.started_at = started_at
        self.calls = 0

    async def run_regression(
        self,
        outcome: MimirCatalogPromotionOutcome,
        *,
        now: datetime,
    ) -> MimirRegressionResult:
        self.calls += 1
        return MimirRegressionResult(
            passed=True,
            started_at=self.started_at,
            completed_at=self.started_at + timedelta(minutes=5),
            evidence_ref=f"regression:{outcome.rule_id}",
        )


class _SelectiveRegressionRunner(_RegressionRunner):
    def __init__(self, *, started_at: datetime, failing_rule_ids: set[str]) -> None:
        super().__init__(started_at=started_at)
        self.failing_rule_ids = failing_rule_ids

    async def run_regression(
        self,
        outcome: MimirCatalogPromotionOutcome,
        *,
        now: datetime,
    ) -> MimirRegressionResult:
        self.calls += 1
        if outcome.rule_id in self.failing_rule_ids:
            raise RuntimeError("regression unavailable")
        return MimirRegressionResult(
            passed=True,
            started_at=self.started_at,
            completed_at=self.started_at + timedelta(minutes=5),
            evidence_ref=f"regression:{outcome.rule_id}",
        )


class _SlowPromotionReader(_PromotionReader):
    async def read_promotion_outcomes(
        self,
        *,
        limit: int,
        now: datetime,
    ) -> Sequence[MimirCatalogPromotionOutcome]:
        await asyncio.sleep(1)
        return ()


class _FailingRuleSourcePoller:
    async def poll_rule_sources(
        self,
        *,
        limit: int,
        now: datetime,
    ) -> MimirRuleSourcePollResult:
        raise RuntimeError("poll failed")


class _SlowDeprecationReader:
    async def stale_or_retired_rules(
        self,
        *,
        limit: int,
        now: datetime,
    ) -> Sequence[MimirDeprecationCandidate]:
        await asyncio.sleep(1)
        return ()


class _FailingBus(InMemoryBus):
    async def publish(self, principal: str, topic: str, payload: dict[str, Any]) -> None:
        raise RuntimeError("broker unavailable")


class _RuleSourcePoller:
    async def poll_rule_sources(
        self,
        *,
        limit: int,
        now: datetime,
    ) -> MimirRuleSourcePollResult:
        return MimirRuleSourcePollResult(checked=1, changed=0, evidence_ref="source-poll:1")


class _DeprecationReader:
    async def stale_or_retired_rules(
        self,
        *,
        limit: int,
        now: datetime,
    ) -> Sequence[MimirDeprecationCandidate]:
        return (
            MimirDeprecationCandidate(
                rule_id="rule.stale",
                reason="retired_window_elapsed",
                evidence_ref="deprecation:1",
                observed_at=now,
            ),
        )


def _wire(saga: Saga, norns: Norns, mimir: Mimir) -> InMemoryBus:
    bus = InMemoryBus(registry=load_pantheon())
    saga.bind_bus(bus)
    norns.bind_bus(bus)
    mimir.bind_bus(bus)
    bus.subscribe("object.issue", "Norns", norns.on_typed_message)
    bus.subscribe("object.rule-candidate", "Mimir", mimir.on_typed_message)
    bus.subscribe("object.rule", "Saga", saga.on_typed_message)
    return bus


async def test_mimir_promotion_evidence_closes_only_after_clean_24h_window() -> None:
    now = datetime(2032, 1, 2, 1, 0, tzinfo=UTC)
    store = InMemoryStateStore()
    saga = Saga(clock=lambda: now)
    norns = Norns(promotion_threshold=1)
    mimir = Mimir(governance_state_store=store, clock=lambda: now)
    bus = _wire(saga, norns, mimir)
    saga.bind_issue_close_promotion_evidence_producer()
    reader = _PromotionReader()
    runner = _RegressionRunner(started_at=now - timedelta(hours=25))
    mimir.bind_catalog_promotion_outcome_reader(reader)
    mimir.bind_regression_runner(runner)
    mimir.bind_rule_source_poller(_RuleSourcePoller())
    mimir.bind_rule_deprecation_reader(_DeprecationReader())

    handoff = handoff_event_payload(
        session_id="session-close",
        question="unknown closeable",
        turn_index=0,
        reason="no_route",
        emitted_at=now - timedelta(hours=48),
    )
    fingerprint = str(handoff["problem_fingerprint"])
    await saga.on_typed_message("object.handoff-escalation", handoff)
    reader.outcomes.append(
        MimirCatalogPromotionOutcome(
            problem_fingerprint=fingerprint,
            promotion_pr="https://github.com/dotnetpower/fdai/pull/999",
            correlation_id="promotion-1",
            outcome="promoted",
            rule_id="rule.closeable",
            promoted_at=now - timedelta(hours=26),
        )
    )

    await mimir.maintenance_tick()
    await saga.maintenance_tick()

    issue = saga.github.issues[fingerprint]
    assert issue.open is False
    assert issue.closed_by_pr == "https://github.com/dotnetpower/fdai/pull/999"
    rule_messages = bus.messages_on("object.rule")
    assert rule_messages[-1].principal == "Mimir"
    assert (
        rule_messages[-1].payload["clean_regression_started_at"]
        == (now - timedelta(hours=25)).isoformat()
    )
    assert saga.behavior_snapshot()["maintenance_tick:issue_close_scan_closed"] == 1

    await mimir.maintenance_tick()

    assert runner.calls == 1
    assert len(bus.messages_on("object.rule")) == 1


async def test_mimir_promotion_evidence_waits_when_regression_window_is_short() -> None:
    now = datetime(2032, 1, 2, 1, 0, tzinfo=UTC)
    saga = Saga(clock=lambda: now)
    norns = Norns(promotion_threshold=1)
    mimir = Mimir(governance_state_store=InMemoryStateStore(), clock=lambda: now)
    _wire(saga, norns, mimir)
    saga.bind_issue_close_promotion_evidence_producer()
    reader = _PromotionReader()
    mimir.bind_catalog_promotion_outcome_reader(reader)
    mimir.bind_regression_runner(_RegressionRunner(started_at=now - timedelta(hours=23)))
    mimir.bind_rule_source_poller(_RuleSourcePoller())
    mimir.bind_rule_deprecation_reader(_DeprecationReader())
    handoff = handoff_event_payload(
        session_id="session-wait",
        question="unknown wait",
        turn_index=0,
        reason="no_route",
        emitted_at=now - timedelta(hours=48),
    )
    fingerprint = str(handoff["problem_fingerprint"])
    await saga.on_typed_message("object.handoff-escalation", handoff)
    reader.outcomes.append(
        MimirCatalogPromotionOutcome(
            problem_fingerprint=fingerprint,
            promotion_pr="https://github.com/dotnetpower/fdai/pull/1000",
            correlation_id="promotion-short",
            outcome="promoted",
            rule_id="rule.wait",
            promoted_at=now - timedelta(hours=24),
        )
    )

    await mimir.maintenance_tick()
    await saga.maintenance_tick()

    assert saga.github.issues[fingerprint].open is True
    assert "maintenance_tick:issue_close_scan_closed" not in saga.behavior_snapshot()


async def test_saga_rehydrates_issue_close_eligibility_after_restart() -> None:
    now = datetime(2032, 1, 2, 1, 0, tzinfo=UTC)
    store = InMemoryStateStore()
    first = Saga(
        durable_state_store=store,
        github=StateStoreIssueTrackerAdapter(store),
        clock=lambda: now,
    )
    first.bind_bus(InMemoryBus(registry=load_pantheon()))
    first.bind_issue_close_promotion_evidence_producer()
    handoff = handoff_event_payload(
        session_id="session-restart-close",
        question="unknown restart close",
        turn_index=0,
        reason="no_route",
        emitted_at=now - timedelta(hours=48),
    )
    fingerprint = str(handoff["problem_fingerprint"])
    await first.on_typed_message("object.handoff-escalation", handoff)
    await first.on_typed_message(
        "object.rule",
        {
            "producer_principal": "Mimir",
            "kind": "catalog_review_outcome",
            "problem_fingerprint": fingerprint,
            "promotion_pr": "https://github.com/dotnetpower/fdai/pull/1100",
            "clean_regression_started_at": (now - timedelta(hours=25)).isoformat(),
            "outcome": "promoted",
            "correlation_id": "promotion-restart",
        },
    )

    restarted = Saga(
        durable_state_store=store,
        github=StateStoreIssueTrackerAdapter(store),
        clock=lambda: now,
    )
    restarted.bind_issue_close_promotion_evidence_producer()

    assert await restarted.scan_issue_closures() == 1
    assert restarted.github.issues[fingerprint].open is False
    assert restarted.github.issues[fingerprint].closed_by_pr == (
        "https://github.com/dotnetpower/fdai/pull/1100"
    )
    health = restarted.health()
    assert health["issue_auto_close"] == "evidence_available"
    assert health["issue_auto_close_last_recovered"] == 1


async def test_saga_cancels_mimir_close_when_fingerprint_recurs_after_clean_start() -> None:
    now = datetime(2032, 1, 2, 1, 0, tzinfo=UTC)
    saga = Saga(clock=lambda: now)
    norns = Norns(promotion_threshold=1)
    mimir = Mimir(governance_state_store=InMemoryStateStore(), clock=lambda: now)
    _wire(saga, norns, mimir)
    saga.bind_issue_close_promotion_evidence_producer()
    reader = _PromotionReader()
    mimir.bind_catalog_promotion_outcome_reader(reader)
    runner = _RegressionRunner(started_at=now - timedelta(hours=25))
    mimir.bind_regression_runner(runner)
    mimir.bind_rule_source_poller(_RuleSourcePoller())
    mimir.bind_rule_deprecation_reader(_DeprecationReader())
    first = handoff_event_payload(
        session_id="session-recur-1",
        question="unknown recurring",
        turn_index=0,
        reason="no_route",
        emitted_at=now - timedelta(hours=48),
    )
    second = handoff_event_payload(
        session_id="session-recur-2",
        question="unknown recurring",
        turn_index=0,
        reason="no_route",
        emitted_at=now - timedelta(hours=23),
    )
    fingerprint = str(first["problem_fingerprint"])
    await saga.on_typed_message("object.handoff-escalation", first)
    reader.outcomes.append(
        MimirCatalogPromotionOutcome(
            problem_fingerprint=fingerprint,
            promotion_pr="https://github.com/dotnetpower/fdai/pull/1001",
            correlation_id="promotion-recur",
            outcome="promoted",
            rule_id="rule.recur",
            promoted_at=now - timedelta(hours=26),
        )
    )
    await mimir.maintenance_tick()
    await saga.on_typed_message("object.handoff-escalation", second)

    await saga.maintenance_tick()
    await mimir.maintenance_tick()

    assert saga.github.issues[fingerprint].open is True
    assert saga.behavior_snapshot()["issue_close:recurrence_after_clean"] == 1
    assert runner.calls == 1


async def test_mimir_retries_pending_issue_close_evidence_publication() -> None:
    now = datetime(2032, 1, 2, 1, 0, tzinfo=UTC)
    store = InMemoryStateStore()
    mimir = Mimir(governance_state_store=store, clock=lambda: now)
    bus = InMemoryBus(registry=load_pantheon())
    mimir.bind_bus(bus)
    reader = _PromotionReader()
    outcome = MimirCatalogPromotionOutcome(
        problem_fingerprint="fp-pending-publication",
        promotion_pr="https://github.com/dotnetpower/fdai/pull/1002",
        correlation_id="promotion-pending-publication",
        outcome="promoted",
        rule_id="rule.pending.publication",
        promoted_at=now - timedelta(hours=26),
    )
    reader.outcomes.append(outcome)
    mimir.bind_catalog_promotion_outcome_reader(reader)
    mimir.bind_regression_runner(_RegressionRunner(started_at=now - timedelta(hours=25)))
    idempotency_key = _issue_close_evidence_idempotency_key(outcome)
    payload = {
        "producer_principal": "Mimir",
        "kind": "catalog_review_outcome",
        "correlation_id": outcome.correlation_id,
        "idempotency_key": idempotency_key,
        "outcome": outcome.outcome,
        "problem_fingerprint": outcome.problem_fingerprint,
        "fingerprint": outcome.problem_fingerprint,
        "promotion_pr": outcome.promotion_pr,
        "clean_regression_started_at": (now - timedelta(hours=25)).isoformat(),
        "rule_id": outcome.rule_id,
        "candidate_digest": outcome.candidate_digest,
        "package_digest": outcome.package_digest,
        "review_ref": outcome.review_ref,
        "norns_issue_close_support": None,
        "grants_issue_close_authority": False,
    }
    await store.write_state(
        _rule_publication_key(idempotency_key),
        {
            "kind": "mimir_rule_publication",
            "revision": 1,
            "status": "pending",
            "topic": "object.rule",
            "idempotency_key": idempotency_key,
            "correlation_id": outcome.correlation_id,
            "payload": payload,
        },
    )

    await mimir.maintenance_tick()

    assert len(bus.messages_on("object.rule")) == 1
    assert bus.messages_on("object.rule")[0].payload["idempotency_key"] == idempotency_key
    assert (await store.read_state(_rule_publication_key(idempotency_key)))["status"] == (
        "published"
    )
    assert "promotion_evidence:duplicate" not in mimir.behavior_snapshot()


async def test_norns_inert_eligibility_alone_never_closes_or_mutates_issues() -> None:
    current = datetime(2032, 1, 2, tzinfo=UTC)
    saga = Saga(clock=lambda: current)
    norns = Norns(
        promotion_threshold=99,
        issue_close_quiet_window=timedelta(hours=1),
        clock=lambda: current,
    )
    mimir = Mimir(governance_state_store=InMemoryStateStore(), clock=lambda: current)
    bus = _wire(saga, norns, mimir)
    handoff = handoff_event_payload(
        session_id="session-inert",
        question="unknown inert",
        turn_index=0,
        reason="no_route",
        emitted_at=current - timedelta(hours=48),
    )
    fingerprint = str(handoff["problem_fingerprint"])

    await saga.on_typed_message("object.handoff-escalation", handoff)
    current += timedelta(hours=2)
    await norns.maintenance_tick()
    await saga.maintenance_tick()

    assert saga.github.issues[fingerprint].open is True
    rule_candidate = bus.messages_on("object.rule-candidate")[-1]
    assert rule_candidate.principal == "Norns"
    assert rule_candidate.payload["kind"] == "issue_close_eligibility_signal"
    assert rule_candidate.payload["closure_eligibility"]["grants_issue_authority"] is False
    assert not any(message.principal == "Norns" for message in bus.messages_on("object.issue"))
    assert "maintenance_tick:issue_close_scan_closed" not in saga.behavior_snapshot()
    assert mimir.health()["maintenance"]["norns_issue_close_support_count"] == 1


async def test_mimir_replays_pending_issue_close_evidence_after_restart() -> None:
    now = datetime(2032, 1, 2, 1, 0, tzinfo=UTC)
    store = InMemoryStateStore()
    reader = _PromotionReader()
    runner = _RegressionRunner(started_at=now - timedelta(hours=25))
    outcome = MimirCatalogPromotionOutcome(
        problem_fingerprint="fp-replay",
        promotion_pr="https://github.com/dotnetpower/fdai/pull/1002",
        correlation_id="promotion-replay",
        outcome="promoted",
        rule_id="rule.replay",
        promoted_at=now - timedelta(hours=26),
    )
    reader.outcomes.append(outcome)
    first = Mimir(governance_state_store=store, clock=lambda: now)
    first.bind_catalog_promotion_outcome_reader(reader)
    first.bind_regression_runner(runner)
    first.bind_bus(_FailingBus(registry=load_pantheon()))

    try:
        await first.maintenance_tick()
    except RuntimeError:
        pass
    rows, _total = await store.read_state_page(
        "pantheon/mimir/governance/rule-publications/",
        limit=1,
        field="status",
        value="pending",
    )
    assert len(rows) == 1
    pending_key = str(rows[0]["idempotency_key"])

    restarted = Mimir(governance_state_store=store, clock=lambda: now)
    bus = InMemoryBus(registry=load_pantheon())
    restarted.bind_bus(bus)

    assert await restarted.recover_governance_state() == 1
    messages = bus.messages_on("object.rule")
    assert len(messages) == 1
    assert messages[0].payload["idempotency_key"] == pending_key


async def test_mimir_port_timeouts_and_regression_exceptions_are_isolated() -> None:
    now = datetime(2032, 1, 2, 1, 0, tzinfo=UTC)
    reader = _PromotionReader()
    reader.outcomes.extend(
        [
            MimirCatalogPromotionOutcome(
                problem_fingerprint="fp-fail",
                promotion_pr="https://github.com/dotnetpower/fdai/pull/1003",
                correlation_id="promotion-fail",
                outcome="promoted",
                rule_id="rule.fail",
                promoted_at=now - timedelta(hours=26),
            ),
            MimirCatalogPromotionOutcome(
                problem_fingerprint="fp-ok",
                promotion_pr="https://github.com/dotnetpower/fdai/pull/1004",
                correlation_id="promotion-ok",
                outcome="promoted",
                rule_id="rule.ok",
                promoted_at=now - timedelta(hours=26),
            ),
        ]
    )
    mimir = Mimir(
        governance_state_store=InMemoryStateStore(),
        clock=lambda: now,
        provider_timeout_seconds=0.01,
    )
    bus = InMemoryBus(registry=load_pantheon())
    mimir.bind_bus(bus)
    mimir.bind_catalog_promotion_outcome_reader(reader)
    mimir.bind_regression_runner(
        _SelectiveRegressionRunner(
            started_at=now - timedelta(hours=25),
            failing_rule_ids={"rule.fail"},
        )
    )
    mimir.bind_rule_source_poller(_FailingRuleSourcePoller())
    mimir.bind_rule_deprecation_reader(_SlowDeprecationReader())

    await mimir.maintenance_tick()

    health = mimir.health()
    assert health["maintenance"]["rule_source_poll"]["status"] == "failed"
    assert health["maintenance"]["deprecation_cycle"]["status"] == "timeout"
    assert mimir.behavior_snapshot()["promotion_evidence:regression_failed"] == 1
    assert len(bus.messages_on("object.rule")) == 1
    assert bus.messages_on("object.rule")[0].payload["rule_id"] == "rule.ok"

    timeout_mimir = Mimir(provider_timeout_seconds=0.01)
    timeout_mimir.bind_catalog_promotion_outcome_reader(_SlowPromotionReader())
    timeout_mimir.bind_regression_runner(_RegressionRunner(started_at=now - timedelta(hours=25)))
    await timeout_mimir.maintenance_tick()
    assert timeout_mimir.health()["maintenance"]["regression_suite"]["status"] == "timeout"


async def test_norns_quiet_window_support_is_once_per_episode() -> None:
    current = datetime(2032, 1, 2, tzinfo=UTC)
    norns = Norns(
        promotion_threshold=99,
        issue_close_quiet_window=timedelta(hours=1),
        clock=lambda: current,
    )
    mimir = Mimir()
    bus = InMemoryBus(registry=load_pantheon())
    norns.bind_bus(bus)
    mimir.bind_bus(bus)
    bus.subscribe("object.rule-candidate", "Mimir", mimir.on_typed_message)

    await norns.on_typed_message(
        "object.issue",
        {
            "producer_principal": "Saga",
            "fingerprint": "fp-quiet",
            "correlation_id": "issue-1",
            "idempotency_key": "issue-1",
        },
    )
    current += timedelta(minutes=30)
    await norns.maintenance_tick()
    assert bus.messages_on("object.rule-candidate") == []

    current += timedelta(minutes=31)
    await norns.maintenance_tick()
    await norns.maintenance_tick()
    assert len(bus.messages_on("object.rule-candidate")) == 1
    assert mimir.health()["maintenance"]["norns_issue_close_support_count"] == 1

    await norns.on_typed_message(
        "object.issue",
        {
            "producer_principal": "Saga",
            "fingerprint": "fp-quiet",
            "correlation_id": "issue-2",
            "idempotency_key": "issue-2",
        },
    )
    current += timedelta(minutes=30)
    await norns.maintenance_tick()
    assert len(bus.messages_on("object.rule-candidate")) == 1
    current += timedelta(minutes=31)
    await norns.maintenance_tick()
    assert len(bus.messages_on("object.rule-candidate")) == 2
    assert all(
        message.payload["kind"] == "issue_close_eligibility_signal"
        for message in bus.messages_on("object.rule-candidate")
    )


async def test_runtime_binds_optional_mimir_ports_and_marks_saga_only_with_reader_and_runner() -> (
    None
):
    reader = _PromotionReader()
    runner = _RegressionRunner(started_at=datetime(2032, 1, 1, tzinfo=UTC))

    runtime = PantheonRuntime.build(
        provider=InMemoryEventBus(),
        raw_event_topic="fdai.events",
        mimir_promotion_outcome_reader=reader,
        mimir_regression_runner=runner,
        mimir_rule_source_poller=_RuleSourcePoller(),
        mimir_rule_deprecation_reader=_DeprecationReader(),
    )

    assert runtime.agents["Saga"].health()["issue_auto_close"] == "awaiting_promotion_evidence"
    await runtime.agents["Mimir"].maintenance_tick()
    assert runtime.agents["Mimir"].health()["maintenance"]["rule_source_poll"]["status"] == (
        "measured"
    )

    runtime_without_runner = PantheonRuntime.build(
        provider=InMemoryEventBus(),
        raw_event_topic="fdai.events",
        mimir_promotion_outcome_reader=reader,
    )
    assert runtime_without_runner.agents["Saga"].health()["issue_auto_close"] == (
        "awaiting_promotion_evidence_producer"
    )


async def test_mimir_maintenance_unbound_records_bounded_noop_without_degrading_health() -> None:
    mimir = Mimir(governance_state_store=InMemoryStateStore())

    await mimir.maintenance_tick()

    health = mimir.health()
    assert health["status"] == "ok"
    assert health["maintenance"]["rule_source_poll"]["outcome"] == "bounded_noop"
    assert health["maintenance"]["regression_suite"]["outcome"] == "bounded_noop"
    assert health["maintenance"]["deprecation_cycle"]["outcome"] == "bounded_noop"


def test_saga_health_distinguishes_bound_producer_from_unbound() -> None:
    saga = Saga()
    assert saga.health()["issue_auto_close"] == "awaiting_promotion_evidence_producer"

    saga.bind_issue_close_promotion_evidence_producer()

    assert saga.health()["issue_auto_close"] == "awaiting_promotion_evidence"
    assert saga.health()["issue_auto_close_producer_bound"] is True
