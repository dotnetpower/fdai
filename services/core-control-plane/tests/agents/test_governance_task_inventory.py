"""Round 9 package G task-inventory and rate-limit audit regressions."""

from __future__ import annotations

import asyncio
import hashlib
from datetime import UTC, datetime, timedelta

from fdai.agents._framework.bragi_publication import handoff_event_payload
from fdai.agents._framework.bus import InMemoryBus
from fdai.agents._framework.registry import load_pantheon
from fdai.agents.bragi import Bragi
from fdai.agents.odin import Odin
from fdai.agents.saga import Saga
from fdai.agents.var import Var
from fdai.shared.providers.testing.state_store import InMemoryStateStore


def test_odin_maintenance_records_portfolio_review_summary() -> None:
    now = datetime(2032, 1, 2, 3, 4, 5, tzinfo=UTC)
    odin = Odin(clock=lambda: now)
    asyncio.run(
        odin.on_typed_message(
            "object.verdict",
            {
                "producer_principal": "Forseti",
                "correlation_id": "verdict-1",
                "idempotency_key": "verdict:1",
                "risk_verdict": "auto",
            },
        )
    )

    asyncio.run(odin.maintenance_tick())

    review = odin.health()["last_portfolio_review"]
    assert review == {
        "reviewed_at": now.isoformat(),
        "portfolio_window": 1,
        "outcomes": {"auto": 1},
        "advisory_priority_policy": ["resilience", "security", "change_safety", "cost", "capacity"],
        "priority_policy_action": "retain",
        "target_attainment_ratio": 1.0,
        "hil_ratio": 0.0,
        "deny_ratio": 0.0,
        "unknown_ratio": 0.0,
        "execution_authority": False,
    }
    assert odin.behavior_snapshot()["maintenance_tick:portfolio_reviewed"] == 1


def test_var_health_measures_pending_approval_sla_and_approver_availability() -> None:
    now = datetime(2032, 1, 2, tzinfo=UTC)
    var = Var(clock=lambda: now)
    asyncio.run(
        var.on_typed_message(
            "object.action-run",
            {
                "producer_principal": "Thor",
                "correlation_id": "approval-sla-1",
                "idempotency_key": "action-run:approval-sla-1",
                "resource_id": "resource-1",
                "action_type": "ops.restart-service",
                "state": "hil_pending",
                "decision_case": {
                    "created_at": (now - timedelta(hours=25)).isoformat(),
                },
            },
        )
    )
    var.record_behavior("approver_unauthorized")

    health = var.health()

    assert health["status"] == "degraded"
    assert health["status_reason"] == "approval_sla_breach"
    assert health["oldest_pending_ticket_age_evidence_state"] == "measured"
    assert health["oldest_pending_ticket_age_seconds"] == 25 * 60 * 60
    assert health["approval_sla_breach_count"] == 1
    assert health["approver_availability"]["blocked_decisions"] == 1
    assert health["kpis"]["hil_sla_compliance_rate"]["value"] == 0.0
    assert health["approver_availability"]["evidence_state"] == "measured"


async def test_bragi_maintenance_refreshes_durable_user_preference_index() -> None:
    store = InMemoryStateStore()
    bus = InMemoryBus(registry=load_pantheon())
    bragi = Bragi(state_store=store, clock=lambda: datetime(2032, 1, 2, tzinfo=UTC))
    bragi.bind_bus(bus)
    await store.write_state(
        "pantheon/bragi/user-preference-index/operator",
        {
            "principal_id": "operator@example.com",
            "locale": "ko",
            "verbosity": "detailed",
            "answer_detail": "deep",
            "answer_format": "bullets",
            "answer_preferences_enabled": True,
            "answer_intent_detail": {},
            "answer_intent_format": {},
            "share_with_learner": False,
            "revision": 7,
            "updated_at": datetime(2032, 1, 1, tzinfo=UTC).isoformat(),
        },
    )

    await bragi.maintenance_tick()

    messages = bus.messages_on("object.user-preference")
    principal_digest = hashlib.sha256(b"operator@example.com").hexdigest()
    assert len(messages) == 1
    assert messages[0].payload["producer_principal"] == "Bragi"
    assert messages[0].payload["correlation_id"]
    assert messages[0].payload["idempotency_key"] == f"user-preference:{principal_digest}:7"
    assert messages[0].payload["locale"] == "ko"
    assert bragi.health()["last_preference_index_refresh"]["preferences_published"] == 1


async def test_saga_rate_limit_overflow_publishes_non_learnable_audit_entry() -> None:
    bus = InMemoryBus(registry=load_pantheon())
    saga = Saga()
    saga.bind_bus(bus)

    await saga.record_rate_limit_overflow(
        "Norns",
        "object.rule-candidate",
        {"idempotency_key": "candidate:1", "candidate": "too-many"},
    )

    messages = bus.messages_on("object.audit-entry")
    assert len(messages) == 1
    payload = messages[0].payload
    assert payload["kind"] == "rate_limit_exceeded"
    assert payload["correlation_id"]
    assert payload["idempotency_key"]
    assert payload["overflowing_agent"] == "Norns"
    assert payload["overflowed_topic"] == "object.rule-candidate"
    assert payload["dropped_count"] == 1
    assert payload["non_learnable"] is True
    assert payload["execution_authority"] is False
    assert saga.audit_chain.entries[-1].topic == "object.audit-entry"


async def test_saga_issue_close_scan_requires_mimir_promotion_and_clean_window() -> None:
    now = datetime(2032, 1, 2, 1, 0, tzinfo=UTC)
    saga = Saga(clock=lambda: now)
    saga.bind_bus(InMemoryBus(registry=load_pantheon()))
    handoff = handoff_event_payload(
        session_id="session-close",
        question="unknown closeable",
        turn_index=0,
        reason="no_route",
        emitted_at=now - timedelta(hours=48),
    )
    fingerprint = str(handoff["problem_fingerprint"])
    await saga.on_typed_message("object.handoff-escalation", handoff)
    await saga.on_typed_message(
        "object.rule",
        {
            "producer_principal": "Mimir",
            "kind": "catalog_review_outcome",
            "correlation_id": "promotion-1",
            "idempotency_key": "catalog-review:promotion-1",
            "outcome": "promoted",
            "problem_fingerprint": fingerprint,
            "promotion_pr": "https://github.com/dotnetpower/fdai/pull/999",
            "clean_regression_started_at": (now - timedelta(hours=25)).isoformat(),
        },
    )

    await saga.maintenance_tick()

    issue = saga.github.issues[fingerprint]
    assert issue.open is False
    assert issue.closed_by_pr == "https://github.com/dotnetpower/fdai/pull/999"
    assert saga.state_store.get("issue_fingerprint_index", fingerprint)["open"] is False
    assert saga.audit_chain.entries[-1].topic == "object.issue"
    assert saga.behavior_snapshot()["maintenance_tick:issue_close_scan_closed"] == 1


async def test_saga_issue_close_scan_waits_for_clean_window() -> None:
    now = datetime(2032, 1, 2, 1, 0, tzinfo=UTC)
    saga = Saga(clock=lambda: now)
    saga.bind_bus(InMemoryBus(registry=load_pantheon()))
    handoff = handoff_event_payload(
        session_id="session-wait",
        question="unknown wait",
        turn_index=0,
        reason="no_route",
        emitted_at=now - timedelta(hours=48),
    )
    fingerprint = str(handoff["problem_fingerprint"])
    await saga.on_typed_message("object.handoff-escalation", handoff)
    await saga.on_typed_message(
        "object.rule",
        {
            "producer_principal": "Mimir",
            "kind": "catalog_review_outcome",
            "correlation_id": "promotion-2",
            "idempotency_key": "catalog-review:promotion-2",
            "outcome": "promoted",
            "problem_fingerprint": fingerprint,
            "promotion_pr": "https://github.com/dotnetpower/fdai/pull/1000",
            "clean_regression_started_at": (now - timedelta(hours=23, minutes=59)).isoformat(),
        },
    )

    await saga.maintenance_tick()

    assert saga.github.issues[fingerprint].open is True
    assert "maintenance_tick:issue_close_scan_closed" not in saga.behavior_snapshot()


async def test_saga_issue_close_scan_cancels_when_fingerprint_recurs_after_clean_start() -> None:
    now = datetime(2032, 1, 2, 1, 0, tzinfo=UTC)
    saga = Saga(clock=lambda: now)
    saga.bind_bus(InMemoryBus(registry=load_pantheon()))
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
    assert second["problem_fingerprint"] == fingerprint
    await saga.on_typed_message("object.handoff-escalation", first)
    await saga.on_typed_message(
        "object.rule",
        {
            "producer_principal": "Mimir",
            "kind": "catalog_review_outcome",
            "correlation_id": "promotion-recur",
            "idempotency_key": "catalog-review:promotion-recur",
            "outcome": "promoted",
            "problem_fingerprint": fingerprint,
            "promotion_pr": "https://github.com/dotnetpower/fdai/pull/1001",
            "clean_regression_started_at": (now - timedelta(hours=25)).isoformat(),
        },
    )
    await saga.on_typed_message("object.handoff-escalation", second)

    await saga.maintenance_tick()

    assert saga.github.issues[fingerprint].open is True
    assert saga.behavior_snapshot()["issue_close:recurrence_after_clean"] == 1
    assert "maintenance_tick:issue_close_scan_closed" not in saga.behavior_snapshot()


def test_saga_health_reports_awaiting_issue_auto_close_evidence_producer() -> None:
    saga = Saga()

    health = saga.health()

    assert health["issue_auto_close"] == "awaiting_promotion_evidence_producer"
    assert health["issue_auto_close_evidence_count"] == 0


async def test_saga_fingerprint_index_compaction_keeps_newest_entries() -> None:
    saga = Saga()
    for index in range(10_005):
        saga._put_fingerprint_index(  # noqa: SLF001 - maintenance compaction regression
            f"fingerprint-{index:05d}",
            {"issue_number": index + 1, "occurrence_count": 1, "open": index % 2 == 0},
        )

    compacted = await saga.compact_fingerprint_index()

    retained = saga.state_store.scan("issue_fingerprint_index")
    assert compacted == 5
    assert len(retained) == 10_000
    assert "fingerprint-00000" not in retained
    assert "fingerprint-00004" not in retained
    assert "fingerprint-00005" in retained
