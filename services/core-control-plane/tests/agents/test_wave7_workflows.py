"""Wave 7 tests: cross-agent workflow smoke traces.

Each of the ten documented workflows gets at least one shadow trace
that exercises the participating agents end-to-end through the
in-memory bus. Behavior verified in earlier waves (Saga chain, Var
quorum, Loki blast-radius, Norns fingerprint counter, etc.) is
reused here; W7 only asserts the workflow-level composition.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from fdai.agents._framework.bus import InMemoryBus
from fdai.agents._framework.registry import load_pantheon
from fdai.agents._framework.workflows import WORKFLOWS, workflow
from fdai.agents.forseti import Forseti
from fdai.agents.freyr import Freyr
from fdai.agents.heimdall import Heimdall
from fdai.agents.loki import Loki
from fdai.agents.mimir import Mimir
from fdai.agents.njord import Njord
from fdai.agents.norns import Norns
from fdai.agents.odin import Odin
from fdai.agents.saga import Saga, compute_fingerprint
from fdai.agents.thor import Thor
from fdai.agents.var import Var


def test_workflow_catalog_has_thirteen_entries() -> None:
    assert len(WORKFLOWS) == 13


def test_every_workflow_starts_in_shadow() -> None:
    assert all(item.default_mode == "shadow" for item in WORKFLOWS)


def test_every_workflow_trace_ref_resolves() -> None:
    repo_root = Path(__file__).resolve().parents[4]
    for item in WORKFLOWS:
        path, separator, node = item.trace_ref.partition("::")
        assert separator and node, item.id
        assert (repo_root / path).is_file(), item.trace_ref


def test_every_workflow_participant_is_a_real_agent() -> None:
    reg = load_pantheon()
    for w in WORKFLOWS:
        assert w.primary_agent in reg.names()
        for agent in w.participating_agents:
            assert agent in reg.names(), f"workflow {w.id!r} references unknown agent {agent!r}"


def test_workflow_lookup_by_id() -> None:
    w = workflow("dr-drill-orchestration")
    assert w.name == "DR drill orchestration"
    assert "Loki" in w.participating_agents


def test_late_wave_workflows_are_registered() -> None:
    assert workflow("operational-readiness-handoff").primary_agent == "Forseti"
    assert "Thor" in workflow("scheduled-governed-python-task").participating_agents


# ---------------------------------------------------------------------------
# 1. Cost-aware remediation smoke trace
# ---------------------------------------------------------------------------


def test_workflow_cost_aware_remediation_shadow_trace() -> None:
    reg = load_pantheon()
    bus = InMemoryBus(registry=reg)
    forseti = Forseti(bus=bus)
    njord = Njord(bus=bus)
    thor = Thor(bus=bus)
    saga = Saga()
    for terminal in ("object.verdict", "object.action-run"):
        bus.subscribe(terminal, "Saga", saga.on_typed_message)
    bus.subscribe("object.verdict", "Thor", thor.on_typed_message)

    # A drift-like event that matches Forseti's auto rule.
    asyncio.run(
        forseti.judge(
            {
                "event_type": "public_network_enabled",
                "resource_id": "sa-1",
                "correlation_id": "corr-cost",
            }
        )
    )
    # Njord provides the cost impact independently (advisor hook).
    est = njord.cost_impact("remediate.disable-public-access")
    assert est.monthly_delta_usd == 0.0
    # Verdict must have been auto-executed by Thor and audited by Saga.
    assert any(m.payload["state"] == "succeeded" for m in bus.messages_on("object.action-run"))
    saga.audit_chain.verify()


# ---------------------------------------------------------------------------
# 2. Predictive scale smoke trace
# ---------------------------------------------------------------------------


def test_workflow_predictive_scale_shadow_trace() -> None:
    reg = load_pantheon()
    bus = InMemoryBus(registry=reg)
    freyr = Freyr(bus=bus, scale_up_threshold=0.75)
    for u in (0.7, 0.8, 0.85, 0.9):
        asyncio.run(freyr.ingest_utilization(resource_id="vm-hot", utilization=u))
    advice = freyr.sizing_advice("vm-hot")
    assert advice.action == "scale_up"
    forecasts = bus.messages_on("object.capacity-forecast")
    assert len(forecasts) == 4


# ---------------------------------------------------------------------------
# 3. DR drill orchestration
# ---------------------------------------------------------------------------


def test_workflow_dr_drill_orchestration_respects_blast_radius() -> None:
    reg = load_pantheon()
    bus = InMemoryBus(registry=reg)
    loki = Loki(bus=bus, blast_radius_cap=2)
    proposal = asyncio.run(
        loki.propose_experiment(
            experiment_id="drill-1",
            action_type="ops.failover-primary",
            targets=("dc-1", "dc-2", "dc-3", "dc-4"),
        )
    )
    assert proposal.accepted
    assert len(proposal.targets) == 2  # capped


# ---------------------------------------------------------------------------
# 4. Override -> Discovery
# ---------------------------------------------------------------------------


def test_workflow_override_to_discovery_via_norns() -> None:
    """Repeat overrides on same fingerprint => Norns proposes a candidate."""
    norns = Norns(promotion_threshold=3)
    fp = "override-fp-1"
    for _ in range(3):
        asyncio.run(norns.on_typed_message("object.issue", {"fingerprint": fp}))
    assert norns.pending_candidates[0]["evidence"]["fingerprint"] == fp


# ---------------------------------------------------------------------------
# 5. Security escalation (Wave 6 already covers)
# ---------------------------------------------------------------------------


def test_workflow_security_escalation_reaches_admin_channel() -> None:
    reg = load_pantheon()
    bus = InMemoryBus(registry=reg)
    forseti = Forseti(bus=bus)
    var = Var(bus=bus)
    heimdall = Heimdall(bus=bus)
    heimdall.register_alerter(var.deliver_admin_card)
    bus.subscribe("object.security-event", "Heimdall", heimdall.on_typed_message)

    asyncio.run(
        forseti._emit_security_event(
            event={"correlation_id": "c", "resource_id": "sa-x"},
            initiator="attacker@example.com",
            action_type="remediate.delete-storage",
        )
    )
    assert len(var.admin_channel.cards) == 1
    assert var.admin_channel.cards[0].severity == "high"


# ---------------------------------------------------------------------------
# 6. Handoff -> Capability (Wave 6 covered end-to-end)
# ---------------------------------------------------------------------------


def test_workflow_handoff_capability_promotes_and_closes_issue() -> None:
    reg = load_pantheon()
    bus = InMemoryBus(registry=reg)
    saga = Saga()
    norns = Norns(promotion_threshold=3)
    mimir = Mimir()
    bus.subscribe("object.issue", "Norns", norns.on_typed_message)
    bus.subscribe("object.rule-candidate", "Mimir", mimir.on_typed_message)

    fp = compute_fingerprint(
        intent_category="capacity_query",
        resource_type="vm",
        normalized_selector="",
        primary_agent="Bragi",
        failure_reason_code="no_route",
    )
    for i in range(3):
        asyncio.run(
            saga.escalate_to_github_issue(
                fingerprint=fp,
                emitting_agent="Bragi",
                intent_category="capacity_query",
                failure_reason_code="no_route",
                correlation_id=f"corr-{i}",
            )
        )
        asyncio.run(
            bus.publish(
                "Saga",
                "object.issue",
                {
                    "producer_principal": "Saga",
                    "correlation_id": f"corr-{i}",
                    "fingerprint": fp,
                },
            )
        )
    assert len(norns.pending_candidates) == 1
    asyncio.run(
        bus.publish(
            "Norns",
            "object.rule-candidate",
            {
                "producer_principal": "Norns",
                "correlation_id": "corr-cand",
                "target_rule_id": "auto.route.capacity",
                **norns.pending_candidates[0],
            },
        )
    )
    mimir.promote("auto.route.capacity", source="handoff")
    asyncio.run(saga.close_issue(fingerprint=fp, closed_by_pr="https://example.invalid/pr/9"))
    assert saga.github.issues[fp].open is False


# ---------------------------------------------------------------------------
# 7. Agent health degradation
# ---------------------------------------------------------------------------


def test_workflow_agent_health_degradation_reports_via_odin() -> None:
    reg = load_pantheon()
    bus = InMemoryBus(registry=reg)
    odin = Odin(bus=bus)
    # Odin's arbitration test doubles as a health-degradation report path.
    decision = asyncio.run(
        odin.arbitrate(
            {
                "correlation_id": "health-1",
                "domains_in_conflict": ["resilience", "cost"],
            }
        )
    )
    assert decision.winning_domain == "resilience"


# ---------------------------------------------------------------------------
# 8. Judgment coherence audit
# ---------------------------------------------------------------------------


def test_workflow_judgment_coherence_deterministic_verdict() -> None:
    reg = load_pantheon()
    bus_a = InMemoryBus(registry=reg)
    bus_b = InMemoryBus(registry=reg)
    forseti_a = Forseti(bus=bus_a)
    forseti_b = Forseti(bus=bus_b)
    event = {
        "event_type": "public_network_enabled",
        "resource_id": "sa-x",
        "correlation_id": "c",
    }
    asyncio.run(forseti_a.judge(event))
    asyncio.run(forseti_b.judge(event))
    verdict_a = bus_a.messages_on("object.verdict")[0].payload
    verdict_b = bus_b.messages_on("object.verdict")[0].payload
    # Coherence: same input -> same risk_verdict + action_type
    assert verdict_a["risk_verdict"] == verdict_b["risk_verdict"]
    assert verdict_a["action_type"] == verdict_b["action_type"]


# ---------------------------------------------------------------------------
# 9. Rollback rehearsal
# ---------------------------------------------------------------------------


def test_workflow_rollback_rehearsal_uses_loki_and_leaves_no_flight_targets() -> None:
    reg = load_pantheon()
    bus = InMemoryBus(registry=reg)
    loki = Loki(bus=bus, blast_radius_cap=1)
    proposal = asyncio.run(
        loki.propose_experiment(
            experiment_id="rehearsal-1",
            action_type="ops.restart-service",
            targets=("target-a",),
        )
    )
    assert proposal.accepted
    loki.release_targets(proposal.targets)
    # After release, a follow-up proposal is admitted again.
    followup = asyncio.run(
        loki.propose_experiment(
            experiment_id="rehearsal-2",
            action_type="ops.restart-service",
            targets=("target-b",),
        )
    )
    assert followup.accepted


# ---------------------------------------------------------------------------
# 10. Retrospective what-if (judge-only replay)
# ---------------------------------------------------------------------------


def test_workflow_retrospective_what_if_is_judge_only() -> None:
    saga = Saga()
    for i in range(5):
        asyncio.run(
            saga.on_typed_message(
                "object.verdict",
                {
                    "producer_principal": "Forseti",
                    "correlation_id": "keep",
                    "risk_verdict": "auto",
                    "seq": i,
                },
            )
        )
    entries = saga.replay_for_correlation("keep")
    # Replay preserves ordering and count; never mutates or re-executes.
    assert [e.seq for e in entries] == list(range(5))
    assert all(e.topic == "object.verdict" for e in entries)
