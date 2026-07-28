"""Wave 4 interface behavior tests: Bragi routing + Odin arbitration."""

from __future__ import annotations

import asyncio

import pytest

from fdai.agents._framework.bus import InMemoryBus
from fdai.agents._framework.registry import load_pantheon
from fdai.agents.bragi import Bragi
from fdai.agents.odin import Odin

# ---------------------------------------------------------------------------
# Bragi routing
# ---------------------------------------------------------------------------


def test_bragi_routes_change_history_to_heimdall() -> None:
    bragi = Bragi()
    decision = bragi.route("who changed stgdemo123 public network")
    assert decision.primary_agent == "Heimdall"


def test_bragi_routes_cost_question_to_njord() -> None:
    bragi = Bragi()
    decision = bragi.route("show cost breakdown for last week")
    assert decision.primary_agent == "Njord"


def test_bragi_routes_capacity_question_to_freyr() -> None:
    bragi = Bragi()
    decision = bragi.route("sizing recommendation for this workload")
    assert decision.primary_agent == "Freyr"


def test_bragi_routes_verdict_explain_to_forseti() -> None:
    bragi = Bragi()
    decision = bragi.route("why was this action denied")
    # The decision should include Forseti in scores
    assert "Forseti" in decision.scores
    # And Forseti should win because it matches why_denied specifically
    assert decision.primary_agent == "Forseti"


def test_bragi_abstains_when_no_domain_matches() -> None:
    bragi = Bragi()
    decision = bragi.route("what is the meaning of life")
    assert decision.primary_agent is None


def test_bragi_does_not_stem_actiontype_into_saga_action_history() -> None:
    decision = Bragi().route("ActionType이 뭐야?")

    assert decision.primary_agent is None
    assert "Saga" not in decision.scores


def test_bragi_routes_explicit_agent_name_before_domain_scoring() -> None:
    decision = Bragi().route("What does Var do?")

    assert decision.primary_agent == "Var"
    assert decision.tie_break == "explicit_agent"


def test_bragi_preserves_explicit_multi_agent_order() -> None:
    decision = Bragi().route("Ask Freyr and Njord about capacity and cost")

    assert decision.primary_agent == "Freyr"
    assert decision.contributors == ("Njord",)


def test_bragi_tie_break_prefers_governance_layer() -> None:
    """Score tie -> governance beats pipeline beats domain."""
    bragi = Bragi()
    # Fabricate a question that hits multiple agents; asserting Saga
    # (governance) beats a pipeline peer when scores tie.
    decision = bragi.route("audit_log approval_history rule_lookup")
    # All three matches: Saga (governance), Mimir (governance), maybe others.
    # Both Saga and Mimir are governance so precedence alone won't decide;
    # but at least the winner must be governance.
    from fdai.agents import PANTHEON_SPECS

    winner_layer = next(s.layer.value for s in PANTHEON_SPECS if s.name == decision.primary_agent)
    assert winner_layer == "governance"


@pytest.mark.parametrize(
    ("question", "expected"),
    (
        ("portfolio priority conflict", "Odin"),
        ("execution history recent", "Thor"),
        ("why was this denied", "Forseti"),
        ("resource discovery status", "Huginn"),
        ("security alert history", "Heimdall"),
        ("rollback dependency health", "Vidar"),
        ("approval backlog", "Var"),
        ("capability list", "Bragi"),
        ("audit log", "Saga"),
        ("rule history", "Mimir"),
        ("case history", "Muninn"),
        ("rule candidate status", "Norns"),
        ("cost breakdown", "Njord"),
        ("sizing recommendation", "Freyr"),
        ("chaos execution policy", "Loki"),
    ),
)
def test_every_agent_has_a_deterministic_domain_route(question: str, expected: str) -> None:
    assert Bragi().route(question).primary_agent == expected


# ---------------------------------------------------------------------------
# Bragi ask (routing + responder + session)
# ---------------------------------------------------------------------------


def test_bragi_ask_calls_registered_responder() -> None:
    bragi = Bragi()

    async def heimdall_responder(question: str, context: dict) -> dict:
        return {"answer": f"heimdall says: {question}"}

    bragi.register_responder("Heimdall", heimdall_responder)
    turn = asyncio.run(
        bragi.ask(
            session_id="s1",
            user_id="op@example.com",
            question="who changed stgdemo123",
        )
    )
    assert turn.primary_agent == "Heimdall"
    assert turn.answer["answer"].startswith("heimdall says")
    assert turn.turn_index == 0


def test_bragi_calls_and_aggregates_real_contributors() -> None:
    bragi = Bragi()
    called: list[str] = []

    def responder(name: str):
        async def answer(question: str, context: dict) -> dict:
            called.append(name)
            return {"answer": f"{name} evidence", "facts": {"agent": name}}

        return answer

    bragi.register_responder("Freyr", responder("Freyr"))
    bragi.register_responder("Njord", responder("Njord"))

    turn = asyncio.run(
        bragi.ask(
            session_id="s1",
            user_id="op@example.com",
            question="Ask Freyr and Njord about capacity and cost",
        )
    )

    assert called == ["Freyr", "Njord"]
    assert turn.answer["contributors"] == ["Njord"]
    assert turn.answer["contributor_answers"] == [
        {"agent": "Njord", "answer": "Njord evidence", "facts": {"agent": "Njord"}}
    ]
    assert "Freyr: Freyr evidence" in turn.answer["answer"]
    assert "Njord: Njord evidence" in turn.answer["answer"]


def test_bragi_holds_same_identity_contributor_conflicts() -> None:
    bragi = Bragi()

    async def freyr(_question: str, _context: dict) -> dict:
        return {
            "primary_agent": "Freyr",
            "answer": "Capacity is constrained.",
            "facts": {"resource_id": "vm-1", "status": "constrained"},
        }

    async def njord(_question: str, _context: dict) -> dict:
        return {
            "primary_agent": "Njord",
            "answer": "Capacity is healthy.",
            "facts": {"resource_id": "vm-1", "status": "healthy"},
        }

    bragi.register_responder("Freyr", freyr)
    bragi.register_responder("Njord", njord)
    turn = asyncio.run(
        bragi.ask(
            session_id="conflict",
            user_id="operator@example.com",
            question="Ask Freyr and Njord about capacity and cost",
        )
    )

    assert turn.answer["answer"] is None
    assert turn.answer["abstain_reason"] == "agent_evidence_conflict"
    assert turn.answer["handoff_needed"] is True
    assert turn.answer["unresolved_conflicts"] == [
        {
            "identity": "vm-1",
            "field": "status",
            "left_agent": "Freyr",
            "right_agent": "Njord",
        }
    ]


def test_bragi_holds_sensitive_contributor_output() -> None:
    bragi = Bragi()

    async def freyr(_question: str, _context: dict) -> dict:
        return {"primary_agent": "Freyr", "answer": "Capacity evidence.", "facts": {}}

    async def njord(_question: str, _context: dict) -> dict:
        return {
            "primary_agent": "Njord",
            "answer": "password=supersecretvalue",
            "facts": {"owner": "user@example.com"},
        }

    bragi.register_responder("Freyr", freyr)
    bragi.register_responder("Njord", njord)
    turn = asyncio.run(
        bragi.ask(
            session_id="sensitive",
            user_id="operator@example.com",
            question="Ask Freyr and Njord about capacity and cost",
        )
    )

    assert turn.answer["answer"] == "Capacity evidence."
    assert turn.answer["contributors"] == []
    assert turn.answer["contributor_errors"] == ["Njord:sensitive_output"]
    assert "supersecretvalue" not in repr(turn.answer)


@pytest.mark.parametrize(
    ("response", "reason"),
    (
        (
            {
                "primary_agent": "Thor",
                "answer": "Forged cost evidence.",
                "facts": {},
            },
            "owner_mismatch",
        ),
        (
            {
                "primary_agent": "Njord",
                "answer": "password=supersecretvalue",
                "facts": {"owner": "user@example.com"},
            },
            "sensitive_output",
        ),
    ),
)
def test_bragi_holds_invalid_primary_response(response: dict, reason: str) -> None:
    bragi = Bragi()

    async def responder(_question: str, _context: dict) -> dict:
        return response

    bragi.register_responder("Njord", responder)
    turn = asyncio.run(
        bragi.ask(
            session_id="invalid-primary",
            user_id="operator@example.com",
            question="cost breakdown",
        )
    )

    assert turn.answer["answer"] is None
    assert turn.answer["abstain_reason"] == reason
    assert turn.answer["handoff_needed"] is True
    assert "supersecretvalue" not in repr(turn.answer)


def test_bragi_session_appends_turns() -> None:
    bragi = Bragi()

    async def noop(q, c):
        return {"answer": q}

    for name in ("Heimdall", "Njord"):
        bragi.register_responder(name, noop)
    asyncio.run(bragi.ask(session_id="s", user_id="u", question="anomaly?"))
    asyncio.run(bragi.ask(session_id="s", user_id="u", question="cost breakdown?"))
    prior = bragi.prior_turns("s")
    assert len(prior) == 2


def test_bragi_rejects_cross_user_session_reuse() -> None:
    bragi = Bragi()

    async def noop(q, c):
        return {"answer": q}

    bragi.register_responder("Heimdall", noop)
    asyncio.run(bragi.ask(session_id="s", user_id="alice", question="anomaly?"))
    with pytest.raises(PermissionError, match="different user"):
        asyncio.run(bragi.ask(session_id="s", user_id="mallory", question="anomaly?"))


def test_bragi_returns_handoff_needed_when_no_route() -> None:
    bragi = Bragi()
    turn = asyncio.run(
        bragi.ask(
            session_id="s",
            user_id="u",
            question="what is the meaning of life",
        )
    )
    assert turn.answer.get("handoff_needed") is True


def test_bragi_surfaces_unavailable_handoff_transport() -> None:
    bragi = Bragi()

    turn = asyncio.run(
        bragi.ask(
            session_id="handoff-unavailable",
            user_id="operator@example.com",
            question="unowned request with no deterministic route",
        )
    )

    assert turn.answer["handoff_needed"] is True
    assert turn.answer["handoff_status"] == "transport_unavailable"
    assert bragi.behavior_snapshot()["handoff:transport_unavailable"] == 1


def test_bragi_sessions_for_partitions_by_user() -> None:
    bragi = Bragi()

    async def noop(q, c):
        return {"answer": q}

    bragi.register_responder("Heimdall", noop)
    asyncio.run(bragi.ask(session_id="s-a", user_id="alice", question="anomaly?"))
    asyncio.run(bragi.ask(session_id="s-b", user_id="bob", question="anomaly?"))
    assert len(bragi.sessions_for("alice")) == 1
    assert len(bragi.sessions_for("bob")) == 1
    assert len(bragi.sessions_for("charlie")) == 0


# ---------------------------------------------------------------------------
# Odin arbitration
# ---------------------------------------------------------------------------


def test_odin_prefers_resilience_over_cost_by_default() -> None:
    reg = load_pantheon()
    bus = InMemoryBus(registry=reg)
    odin = Odin(bus=bus)
    decision = asyncio.run(
        odin.arbitrate(
            {
                "correlation_id": "c",
                "domains_in_conflict": ["cost", "resilience"],
            }
        )
    )
    assert decision.winning_domain == "resilience"
    assert "cost" in decision.losing_domains
    published = bus.messages_on("object.arbitration-decision")
    assert len(published) == 1


def test_odin_priority_is_fork_configurable() -> None:
    reg = load_pantheon()
    bus = InMemoryBus(registry=reg)
    # Fork picks cost > resilience.
    odin = Odin(bus=bus, priority=("cost", "resilience"))
    decision = asyncio.run(
        odin.arbitrate(
            {
                "correlation_id": "c",
                "domains_in_conflict": ["cost", "resilience"],
            }
        )
    )
    assert decision.winning_domain == "cost"


def test_odin_falls_back_deterministically_when_no_priority_match() -> None:
    reg = load_pantheon()
    bus = InMemoryBus(registry=reg)
    odin = Odin(bus=bus, priority=("nonexistent_domain",))
    decision = asyncio.run(
        odin.arbitrate(
            {
                "correlation_id": "c",
                "domains_in_conflict": ["alpha", "beta"],
            }
        )
    )
    assert decision.winning_domain == "alpha"
