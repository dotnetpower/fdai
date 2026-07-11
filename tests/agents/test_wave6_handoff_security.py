"""Wave 6 end-to-end tests: Handoff + Security escalation.

Full chain:
- RBAC-insufficient action proposal -> Forseti verdict=deny +
  SecurityEvent -> Heimdall severity classify -> Var admin card
  (deduped, rate-limited).
- Unhandled Bragi query -> Saga escalate_to_github_issue with
  fingerprint dedup -> Norns count -> Mimir candidate -> issue
  auto-close.
"""

from __future__ import annotations

import asyncio

from fdai.agents._framework.bus import InMemoryBus
from fdai.agents._framework.registry import load_pantheon
from fdai.agents.bragi import Bragi
from fdai.agents.forseti import Forseti
from fdai.agents.heimdall import Heimdall
from fdai.agents.mimir import Mimir
from fdai.agents.norns import Norns
from fdai.agents.saga import Saga, compute_fingerprint
from fdai.agents.var import Var

# ---------------------------------------------------------------------------
# Security escalation: RBAC deny -> SecurityEvent -> admin card
# ---------------------------------------------------------------------------


def test_security_high_severity_produces_one_admin_card() -> None:
    reg = load_pantheon()
    bus = InMemoryBus(registry=reg)
    forseti = Forseti(bus=bus)
    var = Var(bus=bus)
    heimdall = Heimdall(bus=bus)
    heimdall.register_alerter(var.deliver_admin_card)

    bus.subscribe("object.security-event", "Heimdall", heimdall.on_typed_message)
    bus.subscribe("object.event", "Forseti", forseti.on_typed_message)

    # RBAC-denied delete of a storage account -> high severity (irreversible)
    asyncio.run(
        forseti.judge(
            {
                "event_type": "restart_needed",  # rule-matched action id
                "resource_id": "sa-1",
                "correlation_id": "c1",
                "initiator_principal": "guest@example.com",
            }
        )
    )
    # guest@example.com allowed only ops.restart-service; that's what
    # rule-match maps to, so we need to override with a delete attempt.
    # Direct call to force denial path:
    asyncio.run(
        forseti._emit_security_event(
            event={"correlation_id": "c-del", "resource_id": "sa-1"},
            initiator="guest@example.com",
            action_type="remediate.delete-storage",
        )
    )
    cards = var.admin_channel.cards
    assert len(cards) == 1
    assert cards[0].severity == "high"
    assert cards[0].initiator_principal == "guest@example.com"


def test_security_repeated_attempts_dedup_into_single_card_with_counter() -> None:
    reg = load_pantheon()
    bus = InMemoryBus(registry=reg)
    forseti = Forseti(bus=bus)
    var = Var(bus=bus)
    heimdall = Heimdall(bus=bus)
    heimdall.register_alerter(var.deliver_admin_card)
    bus.subscribe("object.security-event", "Heimdall", heimdall.on_typed_message)

    for i in range(3):
        asyncio.run(
            forseti._emit_security_event(
                event={"correlation_id": f"c-{i}", "resource_id": "sa-1"},
                initiator="guest@example.com",
                action_type="remediate.delete-storage",
            )
        )
    cards = var.admin_channel.cards
    # Dedup: exactly one card in the channel, but counter incremented
    assert len(cards) == 1
    assert cards[0].counter == 3


def test_security_rate_limit_stops_further_cards() -> None:
    reg = load_pantheon()
    bus = InMemoryBus(registry=reg)
    forseti = Forseti(bus=bus)
    var = Var(bus=bus)
    heimdall = Heimdall(bus=bus, alert_rate_per_hour=2)
    heimdall.register_alerter(var.deliver_admin_card)
    bus.subscribe("object.security-event", "Heimdall", heimdall.on_typed_message)

    # 5 distinct actions from same user -> classified critical after 3
    # distinct. Only first 2 alerts should be sent (rate limit=2).
    for i, action in enumerate(("a.b", "c.d", "e.f", "g.h", "i.j")):
        asyncio.run(
            forseti._emit_security_event(
                event={"correlation_id": f"c-{i}", "resource_id": "sa-1"},
                initiator="attacker@example.com",
                action_type=action,
            )
        )
    # attacker got at most 2 cards (rate limit)
    attacker_cards = [
        c for c in var.admin_channel.cards if c.initiator_principal == "attacker@example.com"
    ]
    assert len(attacker_cards) <= 2


def test_heimdall_recent_events_keyspace_is_bounded() -> None:
    # A long-lived observer sees one entry per distinct resource id; without a
    # cap the per-resource map leaks one entry per resource ever seen.
    from fdai.agents.heimdall import _MAX_TRACKED_KEYS

    h = Heimdall()
    for i in range(_MAX_TRACKED_KEYS + 50):
        asyncio.run(h.on_typed_message("object.event", {"resource_id": f"r{i}", "event_type": "x"}))
    assert len(h._recent_events) == _MAX_TRACKED_KEYS  # noqa: SLF001


def test_security_rate_limit_recovers_after_window() -> None:
    # Regression: the per-hour alert budget must RECOVER when the window rolls
    # over. A monotonic counter with no window would silence the initiator
    # forever after the first burst - an attacker could burn the quota, then
    # operate with every later security alert suppressed.
    clock = {"t": 1000.0}
    reg = load_pantheon()
    bus = InMemoryBus(registry=reg)
    var = Var(bus=bus)
    heimdall = Heimdall(bus=bus, alert_rate_per_hour=2, clock=lambda: clock["t"])
    heimdall.register_alerter(var.deliver_admin_card)

    def emit(action: str, i: int) -> None:
        asyncio.run(
            heimdall.on_typed_message(
                "object.security-event",
                {
                    "correlation_id": f"c-{i}",
                    "resource_id": "sa-1",
                    "initiator_principal": "attacker@example.com",
                    "attempted_action": action,
                    "severity_hint": "critical",  # force high severity -> card
                },
            )
        )

    def attacker_card_count() -> int:
        return len(
            [c for c in var.admin_channel.cards if c.initiator_principal == "attacker@example.com"]
        )

    # Three events in one window -> only 2 cards (rate limit = 2).
    for i, action in enumerate(("a.b", "c.d", "e.f")):
        emit(action, i)
    assert attacker_card_count() == 2
    # Advance past the rolling hour -> budget recovers, the next event alerts.
    clock["t"] += 3601.0
    emit("k.l", 99)
    # The permanent-silence bug would leave this pinned at 2.
    assert attacker_card_count() == 3


# ---------------------------------------------------------------------------
# Handoff: Bragi abstain -> Saga -> Norns -> Mimir -> auto close
# ---------------------------------------------------------------------------


def test_bragi_abstain_creates_saga_issue_and_promotes_via_norns() -> None:
    reg = load_pantheon()
    bus = InMemoryBus(registry=reg)
    bragi = Bragi()
    saga = Saga()
    norns = Norns(promotion_threshold=3)
    mimir = Mimir()

    bus.subscribe("object.issue", "Norns", norns.on_typed_message)
    bus.subscribe("object.rule-candidate", "Mimir", mimir.on_typed_message)

    # Bragi has no responder registered -> ask returns handoff_needed
    turn = asyncio.run(
        bragi.ask(
            session_id="s",
            user_id="op@example.com",
            question="what is the meaning of life",
        )
    )
    assert turn.answer["handoff_needed"] is True

    # Escalation with a stable fingerprint (Wave 6 wires this;
    # Wave 4 Bragi does not auto-escalate yet)
    fp = compute_fingerprint(
        intent_category=turn.answer.get("abstain_reason", "unknown"),
        resource_type="",
        normalized_selector="",
        primary_agent="Bragi",
        failure_reason_code="no_route",
    )
    # Emit three times, each via bus so Norns sees them
    for i in range(3):
        outcome = saga.escalate_to_github_issue(
            fingerprint=fp,
            emitting_agent="Bragi",
            intent_category=turn.answer.get("abstain_reason", "unknown"),
            failure_reason_code="no_route",
            correlation_id=f"corr-{i}",
        )
        asyncio.run(
            bus.publish(
                "Saga",
                "object.issue",
                {
                    "producer_principal": "Saga",
                    "correlation_id": f"corr-{i}",
                    "fingerprint": fp,
                    "issue_number": outcome["issue_number"],
                },
            )
        )
    # One GitHub issue with 2 comments (3 occurrences)
    assert len(saga.github.issues) == 1
    only_issue = next(iter(saga.github.issues.values()))
    assert only_issue.number == 1
    assert len(only_issue.comments) == 2

    # Norns crossed threshold -> one candidate
    assert len(norns.pending_candidates) == 1
    # Simulate publishing that candidate to Mimir via the bus
    asyncio.run(
        bus.publish(
            "Norns",
            "object.rule-candidate",
            {
                "producer_principal": "Norns",
                "correlation_id": "corr-cand",
                "target_rule_id": "auto.gen.route",
                **norns.pending_candidates[0],
            },
        )
    )
    assert len(mimir.pending_candidates()) == 1
    mimir.promote("auto.gen.route", source="handoff")

    # Auto-close by Saga after promotion
    saga.close_issue(fingerprint=fp, closed_by_pr="https://example.invalid/pr/7")
    assert saga.github.issues[fp].open is False
    assert "pr/7" in " ".join(saga.github.issues[fp].comments)
