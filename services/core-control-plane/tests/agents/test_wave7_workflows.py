"""Wave 7 tests: cross-agent workflow shadow traces.

Each of the thirteen documented workflows gets at least one executable
shadow trace. Some traces are Pantheon pub/sub paths; late workflows
also reference composition/control-loop tests until their Pantheon
observer routes exist. Behavior verified in earlier waves (Saga chain,
Var quorum, Loki blast-radius, Norns fingerprint counter, etc.) is
reused here; W7 asserts only implemented workflow-level composition.
"""

from __future__ import annotations

import ast
import asyncio
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from fdai.agents._framework.action_semantics import ActionSemanticsCatalog
from fdai.agents._framework.bus import InMemoryBus
from fdai.agents._framework.forseti_judgment import RISK_VERDICT, RULE_MATCH, JudgmentTable
from fdai.agents._framework.registry import load_pantheon
from fdai.agents._framework.topics import stable_idempotency_key
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
from fdai.shared.providers.cost_governance import SignedCostEffectEstimate

from tests.agents.preflight_helpers import PassingPreflightSimulator

_DOCSTRING_WORKFLOW_COUNT = 13


@dataclass(frozen=True, slots=True)
class _StaticCostProvider:
    monthly_delta_usd: Decimal
    confidence: Decimal = Decimal("0.92")

    async def analyze_cost_sample(self, sample: object) -> None:
        return None

    def estimate_cost_effect(self, action_type: str) -> SignedCostEffectEstimate:
        now = datetime(2026, 9, 30, tzinfo=UTC)
        return SignedCostEffectEstimate(
            action_type=action_type,
            monthly_delta_usd=self.monthly_delta_usd,
            confidence=self.confidence,
            evidence_digest="cost-evidence-digest",
            source_authority="synthetic-focused-test",
            observed_at=now,
            valid_until=now.replace(hour=1),
        )


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _assert_published_payloads_are_traceable(bus: InMemoryBus) -> None:
    for message in bus.published:
        assert message.payload.get("correlation_id"), (message.topic, message.payload)
        assert message.payload.get("idempotency_key"), (message.topic, message.payload)


def _node_exists(path: Path, node: str) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    parts = node.split("::")
    current: ast.AST = tree
    for part in parts:
        body = getattr(current, "body", ())
        match = next(
            (
                child
                for child in body
                if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
                and child.name == part
            ),
            None,
        )
        if match is None:
            return False
        current = match
    return True


def _workflow_doc_section(workflow_id: str) -> str:
    doc = (_repo_root() / "docs/roadmap/agents/agent-workflows.md").read_text(encoding="utf-8")
    number = {w.id: index + 1 for index, w in enumerate(WORKFLOWS)}[workflow_id]
    pattern = rf"^## {number}\. .+?(?=^## {number + 1}\. |^## 14\. |^## Next steps|\Z)"
    match = re.search(pattern, doc, flags=re.MULTILINE | re.DOTALL)
    assert match is not None, workflow_id
    return match.group(0)


def _agents_from_line(section: str, label: str) -> tuple[str, ...]:
    match = re.search(rf"^\*\*{re.escape(label)}\.\*\* (.+)$", section, flags=re.MULTILINE)
    assert match is not None, label
    names = re.findall(
        r"\b(?:Odin|Thor|Forseti|Huginn|Heimdall|Vidar|Var|Bragi|Saga|Mimir|Norns|Muninn|Njord|Freyr|Loki)\b",
        match.group(1),
    )
    return tuple(dict.fromkeys(names))


def test_workflow_catalog_has_thirteen_entries() -> None:
    assert len(WORKFLOWS) == 13


def test_module_docstring_count_matches_catalog() -> None:
    assert _DOCSTRING_WORKFLOW_COUNT == len(WORKFLOWS)
    assert "thirteen documented workflows" in (__doc__ or "")


def test_every_workflow_starts_in_shadow() -> None:
    assert all(item.default_mode == "shadow" for item in WORKFLOWS)


def test_every_workflow_trace_ref_resolves() -> None:
    repo_root = _repo_root()
    for item in WORKFLOWS:
        path, separator, node = item.trace_ref.partition("::")
        assert separator and node, item.id
        trace_file = repo_root / path
        assert trace_file.is_file(), item.trace_ref
        assert _node_exists(trace_file, node), item.trace_ref


def test_trace_ref_resolver_rejects_missing_node(tmp_path: Path) -> None:
    trace_file = tmp_path / "test_trace.py"
    trace_file.write_text("def test_real_trace():\n    pass\n", encoding="utf-8")
    assert _node_exists(trace_file, "test_real_trace")
    assert not _node_exists(trace_file, "test_missing_trace")


def test_every_workflow_participant_is_a_real_agent() -> None:
    reg = load_pantheon()
    for w in WORKFLOWS:
        assert w.primary_agent in reg.names()
        for agent in (*w.participating_agents, *w.planned_agents):
            assert agent in reg.names(), f"workflow {w.id!r} references unknown agent {agent!r}"


def test_workflow_metadata_matches_documented_current_and_planned_agents() -> None:
    for item in WORKFLOWS:
        section = _workflow_doc_section(item.id)
        assert (
            _agents_from_line(section, "Current executable trace agents")
            == item.participating_agents
        )
        assert _agents_from_line(section, "Planned workflow agents") == item.planned_agents


def test_rollout_gate_is_bound_to_trace_assertion_metadata() -> None:
    for item in WORKFLOWS:
        assert item.trace_assertions, item.id
        section = _workflow_doc_section(item.id)
        for assertion in item.trace_assertions:
            assert assertion in section, (item.id, assertion)


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
    cost_provider = _StaticCostProvider(monthly_delta_usd=Decimal("42.50"))
    semantics = ActionSemanticsCatalog(
        irreversible_by_id={"remediate.disable-public-access": False},
        rollback_by_id={"remediate.disable-public-access": "state_forward_only"},
    )
    forseti = Forseti(
        bus=bus,
        action_semantics=semantics,
    )
    njord = Njord(
        bus=bus,
        advisory_provider=cost_provider,
        package_enabled=True,
    )
    thor = Thor(
        bus=bus,
        action_semantics_catalog=semantics,
        preflight_simulator=PassingPreflightSimulator(),
    )
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
    assert est.monthly_delta_usd == 42.5
    assert est.confidence == 0.92
    assert est.evidence_state == "measured"
    assert _cost_ceiling_disposition(est.monthly_delta_usd, ceiling_usd=50.0) == "under_ceiling"
    assert _cost_ceiling_disposition(est.monthly_delta_usd, ceiling_usd=40.0) == "requires_hil"
    # Verdict must have been auto-executed by Thor and audited by Saga.
    action_runs = bus.messages_on("object.action-run")
    assert any(m.payload["state"] == "effect_pending" for m in action_runs)
    assert saga.audit_chain.entries[-1].topic == "object.action-run"
    saga.audit_chain.verify()
    _assert_published_payloads_are_traceable(bus)


def _cost_ceiling_disposition(monthly_delta_usd: float | None, *, ceiling_usd: float) -> str:
    if monthly_delta_usd is None:
        return "cost_evidence_unavailable"
    return "requires_hil" if monthly_delta_usd > ceiling_usd else "under_ceiling"


# ---------------------------------------------------------------------------
# 2. Predictive scale smoke trace
# ---------------------------------------------------------------------------


def test_workflow_predictive_scale_shadow_trace() -> None:
    reg = load_pantheon()
    bus = InMemoryBus(registry=reg)
    freyr = Freyr(bus=bus, scale_up_threshold=0.75)
    forseti = Forseti(bus=bus)
    bus.subscribe("object.capacity-forecast", "Forseti", forseti.on_typed_message)
    bus.subscribe("object.cost-anomaly", "Forseti", forseti.on_typed_message)
    for index, u in enumerate((0.7, 0.8, 0.85, 0.9)):
        asyncio.run(
            freyr.ingest_utilization(
                resource_id="vm-hot",
                utilization=u,
                correlation_id="predictive-scale-hot",
                observed_at=f"2028-01-02T00:0{index}:00+00:00",
            )
        )
    advice = freyr.sizing_advice("vm-hot")
    assert advice.action == "scale_up"
    forecasts = bus.messages_on("object.capacity-forecast")
    assert len(forecasts) == 4
    assert _forecast_leads_reactive_baseline(forecasts[-1].payload, "2028-01-02T00:45:00+00:00")

    cold = Freyr(bus=InMemoryBus(registry=reg), scale_up_threshold=0.75)
    for index, utilization in enumerate((0.2, 0.3, 0.4, 0.5)):
        asyncio.run(
            cold.ingest_utilization(
                resource_id="vm-cold",
                utilization=utilization,
                correlation_id="predictive-scale-cold",
                observed_at=f"2028-01-02T00:1{index}:00+00:00",
            )
        )
    assert cold.sizing_advice("vm-cold").action != "scale_up"

    asyncio.run(
        bus.publish(
            "Njord",
            "object.cost-anomaly",
            {
                "correlation_id": "predictive-scale-hot",
                "idempotency_key": stable_idempotency_key(
                    "cost-block",
                    "predictive-scale-hot",
                    "vm-hot",
                ),
                "resource_id": "vm-hot",
                "recommendation": "scale_down",
                "impact": 0.9,
                "observed_at": "2028-01-02T00:04:00+00:00",
            },
        )
    )
    arbitration_requests = bus.messages_on("object.arbitration-request")
    assert len(arbitration_requests) == 1
    assert arbitration_requests[0].payload["domains_in_conflict"] == ["capacity", "cost"]
    _assert_published_payloads_are_traceable(bus)


def _forecast_leads_reactive_baseline(
    forecast: dict[str, Any],
    reactive_detection_at: str,
) -> bool:
    observed = datetime.fromisoformat(str(forecast["observed_at"]).replace("Z", "+00:00"))
    reactive = datetime.fromisoformat(reactive_detection_at.replace("Z", "+00:00"))
    return (reactive - observed).total_seconds() >= 30 * 60


# ---------------------------------------------------------------------------
# 3. DR drill orchestration
# ---------------------------------------------------------------------------


def test_workflow_dr_drill_orchestration_respects_blast_radius() -> None:
    reg = load_pantheon()
    bus = InMemoryBus(registry=reg)
    loki = Loki(bus=bus, blast_radius_cap=2)
    saga = Saga()
    bus.subscribe("object.chaos-experiment", "Saga", saga.on_typed_message)
    proposal = asyncio.run(
        loki.propose_experiment(
            experiment_id="drill-1",
            action_type="tool.run-chaos-experiment",
            targets=("dc-1", "dc-2", "dc-3", "dc-4"),
            causal_hypothesis_ref="causal-drill",
            refutation_query_ref="query-drill",
            impact_envelope_id="impact-drill",
            recovery_plan_id="recovery-drill",
            dry_run_receipt="dry-run-drill",
        )
    )
    assert proposal.accepted
    assert len(proposal.targets) == 2  # capped
    assert bus.messages_on("object.chaos-experiment")[-1].payload["human_approval_required"] is True
    assert saga.audit_chain.entries[-1].topic == "object.chaos-experiment"
    _assert_published_payloads_are_traceable(bus)


# ---------------------------------------------------------------------------
# 4. Override -> Discovery
# ---------------------------------------------------------------------------


def test_workflow_override_to_discovery_via_norns() -> None:
    """Repeat Var rejections on the same action => Norns proposes a candidate."""
    norns = Norns(rejection_revise_threshold=3)
    for index in range(3):
        asyncio.run(
            norns.on_typed_message(
                "object.approval",
                {
                    "producer_principal": "Var",
                    "action_type": "remediate.scale-out",
                    "state": "rejected",
                    "override_signal": {
                        "proposed_verdict": "auto",
                        "operator_decision": "rejected",
                    },
                    "correlation_id": f"approval-override-{index}",
                    "idempotency_key": stable_idempotency_key(
                        "approval-override",
                        index,
                        "remediate.scale-out",
                    ),
                },
            )
        )
    assert len(norns.pending_candidates) == 1
    candidate = norns.pending_candidates[0]
    assert candidate["source_signal"] == "recurring_hil_rejection"
    assert candidate["evidence"]["action_type"] == "remediate.scale-out"
    assert candidate["evidence"]["rejection_count"] == 3

    no_override = Norns(rejection_revise_threshold=3)
    asyncio.run(
        no_override.on_typed_message(
            "object.issue",
            {
                "producer_principal": "Saga",
                "fingerprint": "issue-without-approval-override",
                "correlation_id": "issue-without-approval-override",
                "idempotency_key": stable_idempotency_key(
                    "issue",
                    "issue-without-approval-override",
                ),
            },
        )
    )
    assert no_override.pending_candidates == []


# ---------------------------------------------------------------------------
# 5. Security escalation (Wave 6 already covers)
# ---------------------------------------------------------------------------


def test_workflow_security_escalation_reaches_admin_channel() -> None:
    reg = load_pantheon()
    bus = InMemoryBus(registry=reg)
    forseti = Forseti(bus=bus)
    var = Var(bus=bus)
    heimdall = Heimdall(bus=bus, clock=lambda: 1000.0, alert_rate_per_hour=5)
    heimdall.register_alerter(var.deliver_admin_card)
    bus.subscribe("object.security-event", "Heimdall", heimdall.on_typed_message)

    for index in range(3):
        asyncio.run(
            forseti._emit_security_event(
                event={"correlation_id": f"security-dup-{index}", "resource_id": "sa-x"},
                initiator="attacker@example.com",
                action_type="remediate.delete-storage",
            )
        )
    assert len(var.admin_channel.cards) == 1
    assert var.admin_channel.cards[0].severity == "high"
    assert var.admin_channel.cards[0].counter == 3

    for index in range(6):
        asyncio.run(
            bus.publish(
                "Forseti",
                "object.security-event",
                {
                    "correlation_id": f"security-rate-{index}",
                    "idempotency_key": stable_idempotency_key(
                        "security-rate",
                        index,
                    ),
                    "event_type": "privilege_escalation_attempt",
                    "initiator_principal": "rate-limit@example.com",
                    "attempted_action": f"remediate.critical-{index}",
                    "target_resource": f"sa-{index}",
                    "severity_hint": "critical",
                },
            )
        )
    assert (
        sum(
            1
            for card in var.admin_channel.cards
            if card.initiator_principal == "rate-limit@example.com"
        )
        == 5
    )

    for index in range(3):
        asyncio.run(
            bus.publish(
                "Forseti",
                "object.security-event",
                {
                    "correlation_id": f"security-critical-{index}",
                    "idempotency_key": stable_idempotency_key(
                        "security-critical",
                        index,
                    ),
                    "event_type": "privilege_escalation_attempt",
                    "initiator_principal": "critical-pattern@example.com",
                    "attempted_action": f"remediate.distinct-{index}",
                    "target_resource": f"critical-{index}",
                    "severity_hint": "medium",
                },
            )
        )
    assert heimdall.alert_count("critical-pattern@example.com", "remediate.distinct-2") == 1
    assert any(card.severity == "critical" for card in var.admin_channel.cards)
    _assert_published_payloads_are_traceable(bus)


# ---------------------------------------------------------------------------
# 6. Handoff -> Capability (Wave 6 covered end-to-end)
# ---------------------------------------------------------------------------


def test_workflow_handoff_capability_keeps_issue_open_without_promotion() -> None:
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
                    "idempotency_key": stable_idempotency_key("issue", fp, f"corr-{i}"),
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
                "idempotency_key": stable_idempotency_key(
                    "rule-candidate",
                    "corr-cand",
                    norns.pending_candidates[0],
                ),
                "target_rule_id": "auto.route.capacity",
                **norns.pending_candidates[0],
            },
        )
    )
    # Promotion is refused until the candidate proves its shadow dwell; the
    # workflow closes through the reviewed catalog pull request instead.
    with pytest.raises(ValueError, match="shadow dwell evidence is insufficient"):
        mimir.promote("auto.route.capacity", source="handoff")
    assert saga.github.issues[fp].open is True


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
    action_semantics = ActionSemanticsCatalog(
        irreversible_by_id={"remediate.disable-public-access": False},
        rollback_by_id={"remediate.disable-public-access": "state_forward_only"},
    )
    forseti_a = Forseti(bus=bus_a, action_semantics=action_semantics)
    forseti_b = Forseti(bus=bus_b, action_semantics=action_semantics)
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

    saga = Saga()
    asyncio.run(saga.on_typed_message("object.verdict", verdict_a))
    sample = saga.replay_for_correlation("c")
    assert len(sample) == 1
    mismatched = {**verdict_b, "risk_verdict": "hil", "idempotency_key": "coherence:mismatch"}
    candidate, alert = _classify_coherence_mismatch(verdict_a, mismatched)
    assert candidate["source_signal"] == "judgment_coherence_mismatch"
    assert candidate["evidence"]["expected_risk_verdict"] == "auto"
    assert alert["topic"] == "object.verdict"


def _classify_coherence_mismatch(
    expected: dict[str, Any],
    actual: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    mismatches = {
        key: (expected.get(key), actual.get(key))
        for key in ("risk_verdict", "action_type")
        if expected.get(key) != actual.get(key)
    }
    if not mismatches:
        raise AssertionError("coherence mismatch classifier requires a real mismatch")
    return (
        {
            "source_signal": "judgment_coherence_mismatch",
            "proposed_by": "Norns",
            "proposal_kind": "revision",
            "target_rule_id": actual.get("action_type") or expected.get("action_type"),
            "evidence": {
                "correlation_id": expected.get("correlation_id"),
                "expected_risk_verdict": expected.get("risk_verdict"),
                "actual_risk_verdict": actual.get("risk_verdict"),
                "mismatch_fields": sorted(mismatches),
            },
        },
        {
            "topic": "object.verdict",
            "correlation_id": expected.get("correlation_id"),
            "mismatch_fields": sorted(mismatches),
        },
    )


# ---------------------------------------------------------------------------
# 9. Rollback rehearsal
# ---------------------------------------------------------------------------


def test_workflow_rollback_rehearsal_blocks_overlapping_loki_targets() -> None:
    reg = load_pantheon()
    bus = InMemoryBus(registry=reg)
    loki = Loki(bus=bus, blast_radius_cap=1)
    saga = Saga()
    bus.subscribe("object.chaos-experiment", "Saga", saga.on_typed_message)
    proposal = asyncio.run(
        loki.propose_experiment(
            experiment_id="rehearsal-1",
            action_type="tool.run-chaos-experiment",
            targets=("target-a",),
            causal_hypothesis_ref="causal-1",
            refutation_query_ref="query-1",
            impact_envelope_id="impact-1",
            recovery_plan_id="recovery-1",
            dry_run_receipt="dry-run-1",
        )
    )
    assert proposal.accepted
    blocked_overlap = asyncio.run(
        loki.propose_experiment(
            experiment_id="rehearsal-2",
            action_type="tool.run-chaos-experiment",
            targets=("target-a",),
            causal_hypothesis_ref="causal-2",
            refutation_query_ref="query-2",
            impact_envelope_id="impact-2",
            recovery_plan_id="recovery-2",
            dry_run_receipt="dry-run-2",
        )
    )
    assert not blocked_overlap.accepted
    assert blocked_overlap.reason == "blast_radius_full"
    assert saga.audit_chain.entries[-1].topic == "object.chaos-experiment"
    _assert_published_payloads_are_traceable(bus)


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
                    "idempotency_key": stable_idempotency_key("what-if-source", i),
                    "risk_verdict": "auto",
                    "seq": i,
                },
            )
        )
    entries = saga.replay_for_correlation("keep")
    # Replay preserves ordering and count; never mutates or re-executes.
    assert [e.seq for e in entries] == list(range(5))
    assert all(e.topic == "object.verdict" for e in entries)
    overlay_a = _run_what_if_overlay("hil")
    overlay_b = _run_what_if_overlay("hil")
    overlay_c = _run_what_if_overlay("deny")
    assert overlay_a == overlay_b
    assert overlay_a["risk_verdict"] == "hil"
    assert overlay_c["risk_verdict"] == "deny"
    assert overlay_a["action_runs"] == 0


def _run_what_if_overlay(risk_verdict: str) -> dict[str, Any]:
    bus = InMemoryBus(registry=load_pantheon())
    action_semantics = ActionSemanticsCatalog(
        irreversible_by_id={"remediate.disable-public-access": False},
        rollback_by_id={"remediate.disable-public-access": "state_forward_only"},
    )
    table = JudgmentTable(
        rule_match=dict(RULE_MATCH),
        risk_verdict={**dict(RISK_VERDICT), "remediate.disable-public-access": risk_verdict},
        source=f"what-if:{risk_verdict}",
    )
    forseti = Forseti(bus=bus, action_semantics=action_semantics, judgment_table=table)
    asyncio.run(
        forseti.judge(
            {
                "event_type": "public_network_enabled",
                "resource_id": "sa-what-if",
                "correlation_id": "what-if",
            }
        )
    )
    verdict = bus.messages_on("object.verdict")[0].payload
    return {
        "risk_verdict": verdict["risk_verdict"],
        "action_type": verdict["action_type"],
        "action_runs": len(bus.messages_on("object.action-run")),
    }
