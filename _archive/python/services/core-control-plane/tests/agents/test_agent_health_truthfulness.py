"""Round 8 H2 health and KPI truthfulness regressions."""

from __future__ import annotations

from datetime import UTC, datetime

from fdai.agents._framework.action_run_state import ActionRunState
from fdai.agents._framework.bus import InMemoryBus
from fdai.agents._framework.kpi import KpiCollector, KpiEvidenceState
from fdai.agents._framework.registry import load_pantheon
from fdai.agents._framework.runtime_health import report_agent_kpis
from fdai.agents._framework.thor_action_run import ActionRun
from fdai.agents.bragi import Bragi
from fdai.agents.forseti import Forseti
from fdai.agents.odin import Odin
from fdai.agents.saga import Saga
from fdai.agents.thor import Thor
from fdai.agents.var import Var
from fdai.agents.vidar import RollbackRecord, Vidar
from fdai.shared.providers.testing.state_store import InMemoryStateStore


def test_thor_health_reports_live_hard_dependency_degradation_and_kpi_denominator() -> None:
    thor = Thor()
    thor.bind_agent_availability(lambda: ("Saga",))
    thor.action_runs["success"] = ActionRun(
        correlation_id="success",
        action_type="ops.restart-service",
        resource_id="vm-1",
        state=ActionRunState.SUCCEEDED,
        verdict="auto",
    )
    thor.action_runs["rolled-back"] = ActionRun(
        correlation_id="rolled-back",
        action_type="ops.restart-service",
        resource_id="vm-2",
        state=ActionRunState.ROLLED_BACK,
        verdict="auto",
    )

    health = thor.health()

    assert health["status"] == "degraded"
    assert health["shadow_forced"] is True
    assert health["saga_available"] is False
    assert health["kpis"]["execution_success_rate"]["value"] == 0.5
    assert health["kpis"]["execution_success_rate"]["denominator"] == 2

    collector = KpiCollector()
    report_agent_kpis(collector, {"Thor": health})
    sample = collector.latest(agent="Thor", metric="execution_success_rate")
    assert sample is not None
    assert sample.evidence_state is KpiEvidenceState.MEASURED
    assert sample.value == 0.5


def test_odin_health_maps_observed_portfolio_kpis() -> None:
    odin = Odin()
    odin._observe_verdict({"risk_verdict": "auto"})  # noqa: SLF001 - observed counter seam
    odin._observe_verdict({"risk_verdict": "hil"})  # noqa: SLF001 - observed counter seam

    health = odin.health()

    assert health["arbitration_durability"] == "process_local"
    assert health["kpis"]["portfolio_target_attainment_ratio"]["value"] == 0.5
    assert health["kpis"]["tie_break_recurrence_rate"]["denominator"] == 2

    collector = KpiCollector()
    report_agent_kpis(collector, {"Odin": health})
    assert collector.latest(agent="Odin", metric="portfolio_target_attainment_ratio").value == 0.5


def test_forseti_health_exposes_odin_unavailable_fallback_state() -> None:
    forseti = Forseti(agent_availability=lambda: ("Odin",))

    health = forseti.health()

    assert health["unavailable_required_peers"] == ["Odin"]
    assert health["operator_alert"]["required"] is True
    assert health["fallback_terminal_hil_closures"] == 0
    assert health["kpis"]["grounding_missing_rate"]["evidence_state"] == "insufficient_sample"


def test_vidar_health_degrades_without_durable_store_or_executor_and_maps_rollback_kpis() -> None:
    vidar = Vidar()
    vidar.records.append(
        RollbackRecord(
            correlation_id="corr-1",
            action_run_identity="action-run:1",
            action_type="ops.restart-service",
            resource_id="vm-1",
            contract="state_forward_only",
            state="succeeded",
        )
    )
    vidar.records.append(
        RollbackRecord(
            correlation_id="corr-2",
            action_run_identity="action-run:2",
            action_type="ops.restart-service",
            resource_id="vm-2",
            contract="state_forward_only",
            state="failed",
            notes="validation failed",
        )
    )

    health = vidar.health()

    assert health["status"] == "degraded"
    assert health["rollback_executor_bound"] is False
    assert health["kpis"]["rollback_success_rate"]["value"] == 0.5
    assert health["kpis"]["rollback_path_validation_failure_rate"]["value"] == 0.5


async def test_var_health_reports_pending_queues_admin_alerts_and_bounded_keys() -> None:
    var = Var(clock=lambda: datetime(2030, 1, 1, tzinfo=UTC))
    for state in ("weird-1", "weird-2", "approved", "succeeded"):
        await var.on_typed_message(
            "object.action-run", {"producer_principal": "Thor", "state": state}
        )
    await var.deliver_admin_card(
        {
            "initiator_principal": "operator@example.com",
            "attempted_action": "ops.restart-service",
            "severity": "high",
        }
    )

    behavior = var.behavior_snapshot()
    assert behavior["action_run:ignored_non_hil"] == 4
    assert "behavior:overflow" not in behavior
    assert all(not key.startswith("action_run:ignored_state:") for key in behavior)

    health = var.health()
    assert health["admin_alert"]["last_status"] == "delivered"
    assert health["pending_tickets"] == 0
    assert health["kpis"]["hil_sla_compliance_rate"]["evidence_state"] == "insufficient_sample"


async def test_var_health_reports_pending_final_approval_backlog() -> None:
    var = Var(state_store=InMemoryStateStore())
    await var._checkpoint_final_approval(  # noqa: SLF001 - pending durable final seam
        {
            "producer_principal": "Var",
            "kind": "action",
            "correlation_id": "corr-final",
            "idempotency_key": "approval:corr-final",
            "action_idempotency_key": "action:corr-final",
            "state": "approved",
            "action_run_identity": f"sha256:{'a' * 64}",
            "rollback_contract": "state_forward_only",
            "approvers": ["reviewer@example.com"],
        }
    )

    health = var.health()

    assert health["status"] == "degraded"
    assert health["pending_final_approvals"] == 1


async def test_bragi_handoff_kpi_counts_success_and_publication_failures() -> None:
    bragi = Bragi()
    assert (
        await bragi._publish_handoff(  # noqa: SLF001 - health evidence seam
            session_id="s1",
            question="unknown",
            turn_index=0,
            intent_category="unknown",
            resource_type="Resource",
            primary_agent="Bragi",
            failure_reason_code="no_route",
        )
        == "transport_unavailable"
    )
    bragi.bind_bus(InMemoryBus(registry=load_pantheon()))
    assert (
        await bragi._publish_handoff(  # noqa: SLF001 - health evidence seam
            session_id="s1",
            question="unknown",
            turn_index=1,
            intent_category="unknown",
            resource_type="Resource",
            primary_agent="Bragi",
            failure_reason_code="no_route",
        )
        == "requested"
    )

    health = bragi.health()

    assert health["session_durability"] == "process_local"
    assert health["handoff_publication"]["denominator"] == 2
    assert health["kpis"]["handoff_rate"]["value"] == 0.5
    assert bragi.behavior_snapshot()["publication:unavailable"] == 1
    assert bragi.behavior_snapshot()["handoff:materialized"] == 1


async def test_saga_health_reports_audit_backlog_without_false_integrity() -> None:
    saga = Saga(durable_state_store=InMemoryStateStore())
    await saga._checkpoint_audit_outbox(  # noqa: SLF001 - pending audit outbox seam
        {
            "producer_principal": "Saga",
            "correlation_id": "corr-audit",
            "idempotency_key": "audit:corr-audit",
        }
    )
    await saga.maintenance_tick()

    health = saga.health()

    assert health["status"] == "degraded"
    assert health["audit_durability"] == "process_local"
    assert health["pending_audit_outbox"] == 1
    assert health["kpis"]["audit_chain_integrity_rate"]["value"] is None
    assert health["kpis"]["audit_chain_integrity_rate"]["evidence_state"] == "insufficient_sample"


def test_publication_unavailable_behavior_vocabulary_is_shared() -> None:
    scoped_files = {
        "thor.py": Thor,
        "var.py": Var,
        "bragi.py": Bragi,
    }
    del scoped_files
    paths = (
        "services/core-control-plane/src/fdai/agents/thor.py",
        "services/core-control-plane/src/fdai/agents/var.py",
        "services/core-control-plane/src/fdai/agents/bragi.py",
    )
    root = __import__("pathlib").Path(__file__).parents[4]
    combined = "\n".join((root / path).read_text(encoding="utf-8") for path in paths)

    assert 'record_behavior("publication:unavailable")' in combined
    assert 'record_behavior("handoff:publish_failed")' not in combined
    assert 'record_behavior("approval:transport_unavailable")' not in combined
    assert 'record_behavior("dispatch:publication_failed")' not in combined
