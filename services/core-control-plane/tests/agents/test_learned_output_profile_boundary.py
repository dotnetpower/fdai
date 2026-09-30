"""Learned and predicted input reaches action paths only with the governed add-on (#1541).

Owner decision 2026-09-28: the default observation-first profile blocks every path by which a
learned pattern or prediction becomes an action; only the explicitly selected governed execution
add-on reopens it, and then only through the existing gates. Each case runs the real Forseti,
Odin, Thor, Var, Njord, and Freyr code over the fixed pantheon registry. The privileged executor
is a recording fake, and every clock is pinned.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import pytest
from fdai.agents._framework.action_semantics import ActionSemanticsCatalog
from fdai.agents._framework.bus import InMemoryBus
from fdai.agents._framework.factory import configured_forseti
from fdai.agents._framework.registry import load_pantheon
from fdai.agents._framework.runtime import PantheonRuntime
from fdai.agents.forseti import Forseti
from fdai.agents.freyr import Freyr
from fdai.agents.odin import Odin
from fdai.agents.thor import Thor
from fdai.agents.var import Var
from fdai.core.operational_context import OperationalContextMaterializer
from fdai.shared.providers.testing.event_bus import InMemoryEventBus

from tests.agents.test_decision_case_e2e import AT, _context_store, _source_freshness_payload
from tests.agents.test_wave5_specialists import _ingest, _njord
from tests.product_selection import governed_execution_selection

_NOW = datetime(2026, 9, 28, 1, 0, tzinfo=UTC)
_ADVISORY = "governed_execution_unselected"


def _known_action_semantics() -> ActionSemanticsCatalog:
    return ActionSemanticsCatalog(
        irreversible_by_id={
            "ops.restart-service": False,
            "ops.scale-out": False,
            "remediate.delete-storage": True,
        },
        rollback_by_id={
            "ops.restart-service": "state_forward_only",
            "ops.scale-out": "state_forward_only",
            "remediate.delete-storage": "state_forward_only",
        },
    )


class _RecordingExecutor:
    """Privileged executor fake: the number of calls is the only observable effect."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def __call__(self, run: dict[str, Any]) -> bool:
        self.calls.append(dict(run))
        return True


def _wired(
    *,
    selected: bool,
    with_odin: bool = True,
    **forseti_bindings: Any,
) -> tuple[InMemoryBus, Forseti, Thor, _RecordingExecutor]:
    bus = InMemoryBus(registry=load_pantheon(), isolate_handlers=False)
    forseti = Forseti(
        bus=bus,
        governed_execution_selected=governed_execution_selection(selected),
        action_semantics=_known_action_semantics(),
        **forseti_bindings,
    )
    executor = _RecordingExecutor()
    thor = Thor(
        bus=bus,
        executor=executor,
        clock=lambda: _NOW,
        action_semantics_catalog=_known_action_semantics(),
    )
    bus.subscribe("object.verdict", "Thor", thor.on_typed_message)
    if with_odin:
        odin = Odin(bus=bus, hil_margin=0.0)
        bus.subscribe("object.arbitration-request", "Odin", odin.on_typed_message)
    bus.subscribe("object.arbitration-decision", "Forseti", forseti.on_typed_message)
    return bus, forseti, thor, executor


def _forecast(mode: str | None, **fields: Any) -> dict[str, Any]:
    """Heimdall's forecast shape plus action-like fields a forged or future producer might add."""

    payload: dict[str, Any] = {
        "producer_principal": "Heimdall",
        "correlation_id": "forecast:1541",
        "idempotency_key": "forecast:1541",
        "prediction_id": "00000000-0000-0000-0000-000000001541",
        "detector_id": "capacity-linear",
        "detector_version": "1.0.0",
        "resource_id": "resource-1",
        "metric": "capacity_percent",
        "predicted_value": 109.0,
        "evidence_refs": ["metric-window:1541"],
        **fields,
    }
    if mode is not None:
        payload["mode"] = mode
    return payload


def _only_verdict(bus: InMemoryBus) -> dict[str, Any]:
    (verdict,) = (message.payload for message in bus.messages_on("object.verdict"))
    return verdict


def _assert_no_action(bus: InMemoryBus, thor: Thor, executor: _RecordingExecutor) -> None:
    assert bus.messages_on("object.action-run") == []
    assert bus.messages_on("object.prospective-lineage") == []
    assert thor.action_runs == {}
    assert executor.calls == []


_ACTION_FIELDS = (
    {"event_type": "restart_needed"},
    {"action_type": "ops.restart-service", "params": {"target_resource_ref": "resource-1"}},
    {"event_type": "restart_needed", "domain_advice": {"capacity": "scale_up", "cost": "hold"}},
)


@pytest.mark.parametrize("mode", ["shadow", "enforce"])
@pytest.mark.parametrize("fields", _ACTION_FIELDS)
async def test_default_forecast_yields_only_an_action_free_verdict(
    fields: dict[str, Any],
    mode: str,
) -> None:
    bus, forseti, thor, executor = _wired(selected=False)

    await forseti.on_typed_message("object.forecast", _forecast(mode, **fields))

    verdict = _only_verdict(bus)
    assert verdict["action_type"] == ""
    assert verdict["reason"] == _ADVISORY
    assert verdict["advisory_source"] == "forecast"
    assert verdict["resolved_autonomy_ceiling"] == "shadow_only"
    assert "params" not in verdict and "source_mode" not in verdict
    assert bus.messages_on("object.arbitration-request") == []
    assert thor.behavior_snapshot()["non_action_verdict_ignored"] == 1
    _assert_no_action(bus, thor, executor)


@pytest.mark.parametrize(
    ("fields", "action_type", "risk_verdict", "ceiling"),
    [
        ({"event_type": "restart_needed"}, "ops.restart-service", "auto", "enforce_auto"),
        (
            {"event_type": "restart_needed", "human_approval_required": True},
            "ops.restart-service",
            "hil",
            "enforce_hil",
        ),
        ({"action_type": "remediate.delete-storage"}, "remediate.delete-storage", "deny", None),
    ],
)
async def test_selected_enforce_forecast_reaches_only_the_existing_gates(
    fields: dict[str, Any],
    action_type: str,
    risk_verdict: str,
    ceiling: str | None,
) -> None:
    bus, forseti, thor, executor = _wired(selected=True)

    await forseti.on_typed_message("object.forecast", _forecast("enforce", **fields))

    verdict = _only_verdict(bus)
    assert verdict["action_type"] == action_type
    assert verdict["risk_verdict"] == risk_verdict
    assert verdict["source_mode"] == "enforce"
    assert verdict["resolved_autonomy_ceiling"] == (ceiling or "shadow_only")
    run = thor.action_runs["forecast:1541"]
    # The unchanged risk table, approval requirement, and Thor lifecycle decide the outcome.
    assert run.verdict == risk_verdict
    assert len(executor.calls) == (1 if risk_verdict == "auto" else 0)


@pytest.mark.parametrize("mode", ["shadow", None, "Enforce", "unknown"])
async def test_selected_non_enforce_forecast_never_yields_an_enforcing_verdict(
    mode: str | None,
) -> None:
    bus, forseti, thor, executor = _wired(selected=True)

    await forseti.on_typed_message("object.forecast", _forecast(mode, event_type="restart_needed"))

    verdict = _only_verdict(bus)
    assert verdict["action_type"] == "ops.restart-service"
    assert verdict["risk_verdict"] == "auto"
    assert verdict["source_mode"] == "shadow"
    assert verdict["resolved_autonomy_ceiling"] == "shadow_only"
    assert forseti.behavior_snapshot()["source_mode:shadow_ceiling"] == 1
    assert thor.action_runs["forecast:1541"].shadow_mode is True
    assert executor.calls == []


async def test_default_profile_keeps_deterministic_judgment_of_observed_signals() -> None:
    bus, forseti, thor, executor = _wired(selected=False)
    observed = {
        **_forecast(None, event_type="restart_needed"),
        "producer_principal": "Huginn",
        "correlation_id": "observed:1541",
        "idempotency_key": "observed:1541",
    }

    await forseti.on_typed_message("object.event", observed)

    verdict = _only_verdict(bus)
    assert verdict["action_type"] == "ops.restart-service"
    assert verdict["reason"] == "rule_match"
    assert verdict["resolved_autonomy_ceiling"] == "enforce_auto"
    assert len(executor.calls) == 1


async def _capacity_conflict(forseti: Forseti) -> None:
    for topic, recommendation, impact in (
        ("object.cost-anomaly", "scale_down", 0.2),
        ("object.capacity-forecast", "scale_up", 1.0),
    ):
        await forseti.on_typed_message(
            topic,
            {
                "producer_principal": "Njord" if topic == "object.cost-anomaly" else "Freyr",
                "correlation_id": "correlation-example",
                "resource_id": "resource-example",
                "recommendation": recommendation,
                "impact": impact,
                "observed_at": AT,
                "source_freshness": _source_freshness_payload(),
                "action_arguments": {
                    "target_resource_ref": "resource-example",
                    "reason": "Reviewed scaling candidate.",
                },
            },
        )


@pytest.mark.parametrize("selected", [False, True])
async def test_capacity_forecast_arbitration_proposes_an_action_only_when_selected(
    selected: bool,
) -> None:
    store = await _context_store()
    bus, forseti, thor, executor = _wired(
        selected=selected,
        operational_context=OperationalContextMaterializer(store=store),
    )
    var = Var(bus=bus)
    bus.subscribe("object.action-run", "Var", var.on_typed_message)

    await _capacity_conflict(forseti)

    (request,) = (message.payload for message in bus.messages_on("object.arbitration-request"))
    (decision,) = (message.payload for message in bus.messages_on("object.arbitration-decision"))
    assert decision["winning_domain"] == "capacity"
    verdict = _only_verdict(bus)
    if selected:
        # Positive control: the same bindings and signals still reach the existing gates.
        assert request["decision_case"]["selected_option_id"] == "capacity:scale_up"
        assert verdict["action_type"] == "ops.scale-out"
        assert verdict["reason"] == "arbitration_resolved"
        assert thor.action_runs["correlation-example"].state.value == "hil_pending"
        assert len(var.pending_tickets()) == 1
        assert executor.calls == []
        return
    assert "decision_case" not in request
    assert verdict["action_type"] == ""
    assert verdict["reason"] == _ADVISORY
    assert verdict["advisory_source"] == "capacity_forecast"
    assert verdict["arbitration"]["outcome"] == "resolved"
    assert verdict["arbitration"]["winning_domain"] == "capacity"
    assert "decision_case" not in verdict and "kinetic_proposal" not in verdict
    assert var.pending_tickets() == ()
    _assert_no_action(bus, thor, executor)


def test_freyr_prediction_settles_as_advisory_evidence_end_to_end() -> None:
    bus = InMemoryBus(registry=load_pantheon(), isolate_handlers=False)
    njord = _njord(bus=bus, anomaly_ratio=1.5)
    freyr = Freyr(bus=bus, scale_up_threshold=0.5, clock=lambda: _NOW)
    forseti = Forseti(bus=bus, action_semantics=_known_action_semantics())
    odin = Odin(bus=bus)
    executor = _RecordingExecutor()
    thor = Thor(bus=bus, executor=executor, clock=lambda: _NOW)
    bus.subscribe("object.cost-anomaly", "Forseti", forseti.on_typed_message)
    bus.subscribe("object.capacity-forecast", "Forseti", forseti.on_typed_message)
    bus.subscribe("object.arbitration-request", "Odin", odin.on_typed_message)
    bus.subscribe("object.arbitration-decision", "Forseti", forseti.on_typed_message)
    bus.subscribe("object.verdict", "Thor", thor.on_typed_message)

    for amount in (100.0, 100.0, 100.0, 200.0):
        _ingest(
            njord,
            scope="scope-1",
            resource_id="resource-1",
            amount_usd=amount,
            correlation_id="specialist-conflict",
        )
    asyncio.run(
        freyr.ingest_utilization(
            resource_id="resource-1",
            utilization=0.9,
            correlation_id="specialist-conflict",
            observed_at=_NOW.isoformat(),
        )
    )

    (decision,) = (message.payload for message in bus.messages_on("object.arbitration-decision"))
    verdict = _only_verdict(bus)
    assert verdict["action_type"] == ""
    assert verdict["reason"] == _ADVISORY
    assert verdict["arbitration"]["outcome"] == (
        "escalated" if decision.get("escalate_hil") is True else "resolved"
    )
    assert verdict["arbitration"]["winning_domain"] == decision["winning_domain"]
    assert "action_arguments" not in verdict and "params" not in verdict
    assert thor.behavior_snapshot()["non_action_verdict_ignored"] == 1
    _assert_no_action(bus, thor, executor)


async def test_owner_unavailable_closure_and_redelivery_stay_single_advisory_verdict() -> None:
    bus, forseti, thor, executor = _wired(
        selected=False,
        with_odin=False,
        agent_availability=lambda: {"Odin"},
    )

    await _capacity_conflict(forseti)
    late_decision = {
        "producer_principal": "Odin",
        "correlation_id": "correlation-example",
        "winning_domain": "capacity",
        "losing_domains": ["cost"],
        "margin": 0.8,
    }
    await forseti.on_typed_message("object.arbitration-decision", late_decision)
    await forseti.on_typed_message("object.arbitration-decision", late_decision)

    verdict = _only_verdict(bus)
    assert verdict["reason"] == _ADVISORY
    assert verdict["arbitration"]["outcome"] == "arbitration_owner_unavailable"
    assert forseti.behavior_snapshot()["learned_output_advisory:duplicate"] == 2
    _assert_no_action(bus, thor, executor)


async def test_observed_domain_conflict_keeps_the_existing_escalation_path() -> None:
    bus, forseti, thor, executor = _wired(selected=False)

    await forseti.on_typed_message(
        "object.event",
        {
            "producer_principal": "Huginn",
            "correlation_id": "observed-conflict",
            "idempotency_key": "observed-conflict",
            "resource_id": "resource-1",
            "event_type": "observed.conflict",
            "domain_advice": {"cost": "scale_down", "resilience": "scale_up"},
        },
    )

    verdict = _only_verdict(bus)
    assert verdict["reason"] != _ADVISORY
    assert "advisory_source" not in verdict
    assert forseti.behavior_snapshot().get("learned_output_advisory:arbitration_marked") is None


def test_runtime_composition_passes_one_selection_to_forseti() -> None:
    default = PantheonRuntime.build(provider=InMemoryEventBus(), raw_event_topic="fdai.raw")
    selected = PantheonRuntime.build(
        provider=InMemoryEventBus(),
        raw_event_topic="fdai.raw",
        governed_execution_selected=governed_execution_selection(True),
    )

    assert default.agents["Forseti"]._governed_execution_selected is False  # noqa: SLF001
    assert selected.agents["Forseti"]._governed_execution_selected is True  # noqa: SLF001
    unbound: dict[str, Any] = dict.fromkeys(
        (
            "rbac",
            "action_semantics",
            "operational_context",
            "operational_planner",
            "kinetic_proposal_source",
            "change_assessor",
        )
    )
    assert configured_forseti(**unbound) is None
    built = configured_forseti(
        **unbound,
        governed_execution_selected=governed_execution_selection(True),
    )
    assert built is not None
    assert built._governed_execution_selected is True  # noqa: SLF001
