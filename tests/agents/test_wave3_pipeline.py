"""Wave 3 pipeline behavior tests."""

from __future__ import annotations

import asyncio
from uuid import UUID

import pytest

from fdai.agents._framework.bus import InMemoryBus
from fdai.agents._framework.registry import load_pantheon
from fdai.agents.forseti import Forseti
from fdai.agents.heimdall import Heimdall
from fdai.agents.huginn import Huginn
from fdai.agents.saga import Saga
from fdai.agents.thor import ActionRunState, Thor
from fdai.agents.var import Var
from fdai.agents.vidar import Vidar
from fdai.shared.contracts.models import IncidentSeverity

# ---------------------------------------------------------------------------
# Huginn
# ---------------------------------------------------------------------------


def test_huginn_normalizes_and_dedups() -> None:
    huginn = Huginn()
    raw = {
        "id": "evt-1",
        "correlation_id": "corr-1",
        "resource_id": "vm-1",
        "resource_type": "compute",
        "event_type": "restart_needed",
        "attributes": {"reason": "healthcheck"},
    }
    first = asyncio.run(huginn.ingest(raw))
    second = asyncio.run(huginn.ingest(raw))
    assert first is not None
    assert first["event_type"] == "restart_needed"
    assert second is None  # dedup


def test_huginn_bounds_pathological_attributes() -> None:
    # attributes is attacker-controlled free-form metadata; the ingress
    # boundary must cap the key count and truncate oversized string values so
    # one signal cannot bloat the pipeline / audit / bus partition.
    from fdai.agents.huginn import _MAX_ATTR_KEYS, _MAX_FIELD_CHARS

    huginn = Huginn()
    payload = asyncio.run(
        huginn.ingest(
            {
                "id": "evt-huge",
                "event_type": "generic",
                "attributes": {
                    **{f"k{i}": "v" for i in range(_MAX_ATTR_KEYS + 100)},
                    "big": "x" * (_MAX_FIELD_CHARS + 1000),
                },
            }
        )
    )
    assert payload is not None
    attrs = payload["attributes"]
    assert len(attrs) == _MAX_ATTR_KEYS
    # Any surviving string value is truncated to the field cap.
    assert all(len(v) <= _MAX_FIELD_CHARS for v in attrs.values() if isinstance(v, str))


def test_huginn_publishes_on_bound_bus() -> None:
    reg = load_pantheon()
    bus = InMemoryBus(registry=reg)
    huginn = Huginn(bus=bus)
    asyncio.run(
        huginn.ingest(
            {
                "id": "evt-x",
                "correlation_id": "c",
                "resource_id": "r",
                "event_type": "public_network_enabled",
            }
        )
    )
    events = bus.messages_on("object.event")
    assert len(events) == 1
    assert events[0].principal == "Huginn"


def test_huginn_requires_stable_key() -> None:
    huginn = Huginn()
    with pytest.raises(ValueError, match="missing idempotency_key"):
        asyncio.run(huginn.ingest({"resource_id": "r"}))


# ---------------------------------------------------------------------------
# Heimdall
# ---------------------------------------------------------------------------


def test_heimdall_emits_anomaly_on_threshold_burst() -> None:
    reg = load_pantheon()
    bus = InMemoryBus(registry=reg)
    heimdall = Heimdall(bus=bus, rate_threshold=3)
    for _ in range(3):
        asyncio.run(
            heimdall.on_typed_message(
                "object.event",
                {"resource_id": "vm-1", "event_type": "cpu_spike", "correlation_id": "c"},
            )
        )
    anomalies = bus.messages_on("object.anomaly")
    assert len(anomalies) == 1
    assert anomalies[0].payload["count_in_window"] == 3


def test_heimdall_no_anomaly_on_mixed_event_types() -> None:
    reg = load_pantheon()
    bus = InMemoryBus(registry=reg)
    heimdall = Heimdall(bus=bus, rate_threshold=3)
    for et in ("a", "b", "c"):
        asyncio.run(
            heimdall.on_typed_message(
                "object.event",
                {"resource_id": "vm-1", "event_type": et, "correlation_id": "c"},
            )
        )
    assert bus.messages_on("object.anomaly") == []


def test_heimdall_does_not_open_anomaly_for_sparse_monitoring_events() -> None:
    reg = load_pantheon()
    bus = InMemoryBus(registry=reg)
    clock = {"now": 0.0}
    candidates: list[dict[str, object]] = []

    async def capture(candidate: dict[str, object]) -> None:
        candidates.append(candidate)

    heimdall = Heimdall(
        bus=bus,
        rate_threshold=3,
        rate_window=60,
        incident_candidate_hook=capture,
        clock=lambda: clock["now"],
    )
    for index in range(3):
        asyncio.run(
            heimdall.on_typed_message(
                "object.event",
                {
                    "resource_id": "vm-1",
                    "event_type": "health_probe_ok",
                    "correlation_id": "monitoring",
                    "idempotency_key": f"event-{index}",
                },
            )
        )
        clock["now"] += 61

    assert bus.messages_on("object.anomaly") == []
    assert candidates == []


def test_heimdall_does_not_handoff_incident_without_event_evidence() -> None:
    reg = load_pantheon()
    bus = InMemoryBus(registry=reg)
    candidates: list[dict[str, object]] = []

    async def capture(candidate: dict[str, object]) -> None:
        candidates.append(candidate)

    heimdall = Heimdall(bus=bus, rate_threshold=2, incident_candidate_hook=capture)
    for _ in range(2):
        asyncio.run(
            heimdall.on_typed_message(
                "object.event",
                {
                    "resource_id": "vm-1",
                    "event_type": "cpu_spike",
                    "correlation_id": "corr-1",
                },
            )
        )

    assert len(bus.messages_on("object.anomaly")) == 1
    assert candidates == []
    assert heimdall.behavior_snapshot()["incident_candidate_missing_evidence"] == 1


def test_heimdall_threshold_candidate_can_open_incident() -> None:
    from fdai.core.incident import IncidentLifecycleWorkflow, IncidentRegistry
    from fdai.shared.providers.testing.state_store import InMemoryStateStore

    registry = IncidentRegistry(state_store=InMemoryStateStore())
    workflow = IncidentLifecycleWorkflow(
        registry=registry,
        allowed_agent_principals={"Heimdall"},
    )

    async def open_candidate(candidate: dict[str, object]) -> None:
        await workflow.open_from_agent(
            producer_principal=str(candidate["producer_principal"]),
            correlation_keys=(f"resource:{candidate['resource_id']}",),
            severity=IncidentSeverity.SEV3,
            member_event_ids=(UUID("00000000-0000-0000-0000-000000000001"),),
            reason=str(candidate["reason_code"]),
        )

    heimdall = Heimdall(rate_threshold=2, incident_candidate_hook=open_candidate)
    for index in range(2):
        asyncio.run(
            heimdall.on_typed_message(
                "object.event",
                {
                    "resource_id": "vm-1",
                    "event_type": "cpu_spike",
                    "correlation_id": "c",
                    "idempotency_key": f"event-{index}",
                },
            )
        )

    incidents = tuple(registry.snapshot().values())
    assert len(incidents) == 1
    assert incidents[0].severity is IncidentSeverity.SEV3
    assert heimdall.behavior_snapshot()["incident_candidate"] == 1


def test_heimdall_security_severity_high_on_irreversible() -> None:
    heimdall = Heimdall()
    asyncio.run(
        heimdall.on_typed_message(
            "object.security-event",
            {
                "initiator_principal": "guest@example.com",
                "attempted_action": "remediate.delete-storage",
                "severity_hint": "medium",
            },
        )
    )
    # on_typed_message returns None, so use direct call
    sev = asyncio.run(
        heimdall._maybe_classify_severity(
            {
                "initiator_principal": "guest@example.com",
                "attempted_action": "remediate.delete-storage",
                "severity_hint": "medium",
            }
        )
    )
    assert sev == "high"


def test_heimdall_security_severity_critical_on_pattern() -> None:
    heimdall = Heimdall()
    # Same user attempting 3 distinct actions => critical
    for action in ("a.b", "c.d", "e.f"):
        asyncio.run(
            heimdall._maybe_classify_severity(
                {
                    "initiator_principal": "attacker@example.com",
                    "attempted_action": action,
                    "severity_hint": "low",
                }
            )
        )
    # A follow-up attempt on any action should classify critical.
    final = asyncio.run(
        heimdall._maybe_classify_severity(
            {
                "initiator_principal": "attacker@example.com",
                "attempted_action": "a.b",
                "severity_hint": "low",
            }
        )
    )
    assert final == "critical"


# ---------------------------------------------------------------------------
# Forseti
# ---------------------------------------------------------------------------


def test_forseti_emits_verdict_auto_on_rule_match() -> None:
    reg = load_pantheon()
    bus = InMemoryBus(registry=reg)
    f = Forseti(bus=bus)
    asyncio.run(
        f.on_typed_message(
            "object.event",
            {
                "event_type": "public_network_enabled",
                "resource_id": "sa-1",
                "correlation_id": "c",
            },
        )
    )
    verdicts = bus.messages_on("object.verdict")
    assert len(verdicts) == 1
    assert verdicts[0].payload["risk_verdict"] == "auto"
    assert verdicts[0].payload["action_type"] == "remediate.disable-public-access"


def test_forseti_emits_document_admission_without_action_type() -> None:
    reg = load_pantheon()
    bus = InMemoryBus(registry=reg)
    f = Forseti(bus=bus)
    asyncio.run(
        f.on_typed_message(
            "object.event",
            {
                "producer_principal": "Huginn",
                "kind": "document_ingestion",
                "event_type": "document.received",
                "correlation_id": "upload-1",
                "idempotency_key": "document.received:version-1",
                "resource_id": "doc-1",
                "document_id": "doc-1",
                "record": {"upload_id": "upload-1"},
            },
        )
    )

    verdict = bus.messages_on("object.verdict")[0].payload
    assert verdict["producer_principal"] == "Forseti"
    assert verdict["kind"] == "document_ingestion"
    assert verdict["stage"] == "received"
    assert verdict["decision"] == "admit"
    assert "action_type" not in verdict


def test_forseti_holds_malformed_document_ingress() -> None:
    f = Forseti(bus=None)

    verdict = asyncio.run(
        f.judge_document_ingestion(
            {"kind": "document_ingestion", "document_id": "doc-1", "record": {}}
        )
    )

    assert verdict["decision"] == "hold"
    assert verdict["reason"] == "invalid_ingress_envelope"


def test_heimdall_emits_content_free_document_safety_signal() -> None:
    reg = load_pantheon()
    bus = InMemoryBus(registry=reg)
    heimdall = Heimdall(bus=bus)
    asyncio.run(
        heimdall.on_typed_message(
            "object.event",
            {
                "producer_principal": "Huginn",
                "kind": "document_ingestion",
                "event_type": "document.inspected",
                "correlation_id": "upload-1",
                "idempotency_key": "document.inspected:version-1",
                "resource_id": "doc-1",
                "document_id": "doc-1",
                "record": {
                    "upload_id": "upload-1",
                    "malware_verdict": "clean",
                    "protection_state": "none",
                    "failure_code": "",
                },
            },
        )
    )

    signal = bus.messages_on("object.anomaly")[0].payload
    assert signal["producer_principal"] == "Heimdall"
    assert signal["kind"] == "document_ingestion"
    assert signal["stage"] == "protection_check"
    assert signal["safety_status"] == "clear"
    assert "record" not in signal


def test_forseti_admits_clear_document_safety_signal() -> None:
    reg = load_pantheon()
    bus = InMemoryBus(registry=reg)
    forseti = Forseti(bus=bus)
    asyncio.run(
        forseti.on_typed_message(
            "object.anomaly",
            {
                "producer_principal": "Heimdall",
                "kind": "document_ingestion",
                "stage": "protection_check",
                "correlation_id": "upload-1",
                "idempotency_key": "document.inspected:version-1",
                "resource_id": "doc-1",
                "document_id": "doc-1",
                "upload_id": "upload-1",
                "safety_status": "clear",
                "protection_state": "none",
            },
        )
    )

    verdict = bus.messages_on("object.verdict")[0].payload
    assert verdict["stage"] == "protection_check"
    assert verdict["decision"] == "admit"
    assert verdict["reason"] == "safety_checks_passed"


def test_forseti_holds_blocked_document_safety_signal() -> None:
    forseti = Forseti(bus=None)

    verdict = asyncio.run(
        forseti.judge_document_safety(
            {
                "kind": "document_ingestion",
                "stage": "protection_check",
                "correlation_id": "upload-1",
                "document_id": "doc-1",
                "upload_id": "upload-1",
                "safety_status": "blocked",
                "failure_code": "malware_detected",
            }
        )
    )

    assert verdict["decision"] == "hold"
    assert verdict["reason"] == "malware_detected"


def test_forseti_routes_authoritative_document_to_hil() -> None:
    forseti = Forseti(bus=None)

    verdict = asyncio.run(
        forseti.judge_document_safety(
            {
                "kind": "document_ingestion",
                "stage": "protection_check",
                "correlation_id": "upload-hil",
                "document_id": "doc-hil",
                "upload_id": "upload-hil",
                "safety_status": "clear",
                "protection_state": "none",
                "purposes": ["handover_bootstrap"],
                "initiator_principal": "uploader@example.com",
            }
        )
    )

    assert verdict["decision"] == "hil"
    assert verdict["reason"] == "sensitive_or_authoritative_document"
    assert verdict["initiator_principal"] == "uploader@example.com"


def test_var_document_hil_blocks_uploader_and_emits_reviewer_approval() -> None:
    reg = load_pantheon()
    bus = InMemoryBus(registry=reg)
    var = Var(bus=bus)
    asyncio.run(
        var.on_typed_message(
            "object.audit-entry",
            {
                "producer_principal": "Saga",
                "kind": "document_ingestion",
                "audited_topic": "object.verdict",
                "stage": "protection_check",
                "decision": "hil",
                "correlation_id": "upload-hil",
                "document_id": "doc-hil",
                "upload_id": "upload-hil",
                "initiator_principal": "uploader@example.com",
            },
        )
    )

    assert var.pending_tickets()[0].kind == "document_ingestion"
    with pytest.raises(ValueError, match="no self-approval"):
        asyncio.run(
            var.decide(
                "upload-hil",
                approver="uploader@example.com",
                decision="approve",
            )
        )
    approval = asyncio.run(
        var.decide(
            "upload-hil",
            approver="reviewer@example.com",
            decision="approve",
        )
    )

    assert approval is not None
    assert approval["kind"] == "document_ingestion"
    assert approval["state"] == "approved"
    assert approval["document_id"] == "doc-hil"


def test_thor_ignores_document_approval() -> None:
    reg = load_pantheon()
    bus = InMemoryBus(registry=reg)
    thor = Thor(bus=bus)

    asyncio.run(
        thor.on_typed_message(
            "object.approval",
            {
                "producer_principal": "Var",
                "kind": "document_ingestion",
                "correlation_id": "upload-hil",
                "state": "approved",
            },
        )
    )

    assert thor.action_runs == {}
    assert thor.behavior_snapshot()["document_approval_ignored"] == 1


def test_forseti_rbac_deny_emits_security_event() -> None:
    reg = load_pantheon()
    bus = InMemoryBus(registry=reg)
    f = Forseti(bus=bus)
    # guest@example.com is not allowed to run remediate.disable-public-access
    asyncio.run(
        f.on_typed_message(
            "object.event",
            {
                "event_type": "public_network_enabled",
                "resource_id": "sa-1",
                "correlation_id": "c",
                "initiator_principal": "guest@example.com",
            },
        )
    )
    verdicts = bus.messages_on("object.verdict")
    security = bus.messages_on("object.security-event")
    assert verdicts[0].payload["risk_verdict"] == "deny"
    assert verdicts[0].payload["reason"] == "rbac_insufficient"
    assert len(security) == 1
    assert security[0].payload["event_type"] == "privilege_escalation_attempt"


def test_forseti_abstains_on_no_rule_match() -> None:
    reg = load_pantheon()
    bus = InMemoryBus(registry=reg)
    f = Forseti(bus=bus)
    result = asyncio.run(
        f.on_typed_message(
            "object.event",
            {"event_type": "unknown_thing", "correlation_id": "c"},
        )
    )
    assert result is None
    assert bus.messages_on("object.verdict") == []


def test_forseti_routes_no_rule_match_with_resource_to_hil() -> None:
    # Rule 4.7 (fail toward safety): an identifiable incident with a concrete
    # resource target but no matching rule MUST NOT vanish - it routes to HIL
    # for human triage instead of returning None.
    reg = load_pantheon()
    bus = InMemoryBus(registry=reg)
    f = Forseti(bus=bus)
    verdict = asyncio.run(
        f.judge({"event_type": "unknown_thing", "correlation_id": "c-triage", "resource_id": "r-1"})
    )
    assert verdict is not None
    assert verdict["risk_verdict"] == "hil"
    assert verdict["reason"] == "no_rule_match"
    # No concrete ActionType maps; empty (never the literal "None") so the
    # downstream dispatcher's str() coercion stays clean.
    assert verdict["action_type"] == ""
    published = bus.messages_on("object.verdict")
    assert len(published) == 1
    assert published[0].payload["risk_verdict"] == "hil"


def test_forseti_cost_spike_has_no_placeholder_remediation() -> None:
    f = Forseti(bus=None)

    verdict = asyncio.run(
        f.judge(
            {
                "event_type": "cost_spike",
                "resource_id": "subscription-cost",
                "correlation_id": "corr-cost-spike",
            }
        )
    )

    assert verdict is not None
    assert verdict["risk_verdict"] == "hil"
    assert verdict["action_type"] == ""
    assert verdict["reason"] == "no_rule_match"


def test_forseti_operator_initiated_unknown_principal_fails_closed_to_deny() -> None:
    # An operator-initiated proposal whose initiator is unknown to the RBAC
    # seam MUST deny (never silently widen privilege via the chat port).
    reg = load_pantheon()
    bus = InMemoryBus(registry=reg)
    f = Forseti(bus=bus)
    verdict = asyncio.run(
        f.judge(
            {
                "action_type": "remediate.delete-storage",
                "resource_id": "sa-9",
                "correlation_id": "c-op",
                "initiator_principal": "stranger@example.com",
                "operator_initiated": True,
            }
        )
    )
    assert verdict is not None
    assert verdict["risk_verdict"] == "deny"
    assert verdict["reason"] == "rbac_insufficient"
    sec = bus.messages_on("object.security-event")
    assert len(sec) == 1
    # delete-storage is irreversible -> high severity hint.
    assert sec[0].payload["severity_hint"] == "high"


def test_forseti_judge_without_bus_returns_verdict_and_no_publish() -> None:
    f = Forseti(bus=None)
    verdict = asyncio.run(f.judge({"action_type": "ops.restart-service", "correlation_id": "c-nb"}))
    # No bus wired: the verdict is still computed and returned (reason
    # rule_match, risk auto) even though nothing is published.
    assert verdict is not None
    assert verdict["risk_verdict"] == "auto"
    assert verdict["reason"] == "rule_match"


def test_forseti_denies_rbac_violation_even_without_a_bus() -> None:
    # Safety: the deny verdict does not depend on a bus. A bus-less judge
    # still fails an unknown operator initiator closed to deny; the
    # security-event emit simply short-circuits (nothing to publish to).
    f = Forseti(bus=None)
    verdict = asyncio.run(
        f.judge(
            {
                "action_type": "remediate.delete-storage",
                "resource_id": "sa-x",
                "correlation_id": "c-nobus-deny",
                "initiator_principal": "stranger@example.com",
                "operator_initiated": True,
            }
        )
    )
    assert verdict is not None
    assert verdict["risk_verdict"] == "deny"
    assert verdict["reason"] == "rbac_insufficient"


def test_forseti_unknown_topic_is_ignored() -> None:
    reg = load_pantheon()
    bus = InMemoryBus(registry=reg)
    f = Forseti(bus=bus)
    asyncio.run(f.on_typed_message("object.unrelated", {"correlation_id": "c"}))
    assert bus.messages_on("object.verdict") == []


def test_forseti_domain_signal_ignores_incomplete_payload() -> None:
    f = Forseti(bus=None)
    # No resource id -> ignored (no arbitration, no accumulated advice).
    assert asyncio.run(f._ingest_domain_signal("cost", {"recommendation": "scale_down"})) is None
    # No recommendation -> ignored.
    assert asyncio.run(f._ingest_domain_signal("cost", {"resource_id": "vm-1"})) is None


def test_forseti_conflicting_domain_signals_raise_weighted_arbitration() -> None:
    reg = load_pantheon()
    bus = InMemoryBus(registry=reg)
    f = Forseti(bus=bus)
    # Cost says scale_down (legacy 'ratio' impact), capacity says scale_up
    # (legacy 'forecast_util' impact) on the same resource -> conflict.
    asyncio.run(
        f.on_typed_message(
            "object.cost-anomaly",
            {"resource_id": "vm-7", "recommendation": "scale_down", "ratio": 1.5},
        )
    )
    asyncio.run(
        f.on_typed_message(
            "object.capacity-forecast",
            {"resource_id": "vm-7", "recommendation": "scale_up", "forecast_util": 0.9},
        )
    )
    requests = bus.messages_on("object.arbitration-request")
    assert len(requests) == 1
    payload = requests[0].payload
    assert set(payload["domains_in_conflict"]) == {"cost", "capacity"}
    # Legacy impact fallbacks were read: cost ratio 1.5 -> 0.5, capacity 0.9.
    assert payload["impacts"]["cost"] == pytest.approx(0.5)
    assert payload["impacts"]["capacity"] == pytest.approx(0.9)


def test_forseti_records_arbitration_decision() -> None:
    f = Forseti(bus=None)
    asyncio.run(
        f.on_typed_message(
            "object.arbitration-decision",
            {"correlation_id": "c-arb", "winning_domain": "capacity"},
        )
    )
    assert f.arbitrations["c-arb"] == "capacity"


def test_forseti_introspect_reports_verdict_tables() -> None:
    f = Forseti(bus=None)
    result = asyncio.run(f.introspect("what verdicts do you know?", {}))
    assert result.facts["known_action_verdicts"]
    assert result.facts["rule_matches"]
    assert "auto/hil/deny" in result.answer


def test_forseti_signal_impact_falls_back_on_non_numeric_fields() -> None:
    reg = load_pantheon()
    bus = InMemoryBus(registry=reg)
    f = Forseti(bus=bus)
    # Non-numeric explicit 'impact' and non-numeric legacy fields both trip
    # the guarded conversions; impact then defaults to 1.0 rather than raising.
    asyncio.run(
        f.on_typed_message(
            "object.cost-anomaly",
            {"resource_id": "vm-8", "recommendation": "scale_down", "impact": "x", "ratio": "y"},
        )
    )
    asyncio.run(
        f.on_typed_message(
            "object.capacity-forecast",
            {
                "resource_id": "vm-8",
                "recommendation": "scale_up",
                "impact": "x",
                "forecast_util": "z",
            },
        )
    )
    requests = bus.messages_on("object.arbitration-request")
    assert len(requests) == 1
    impacts = requests[0].payload["impacts"]
    assert impacts["cost"] == pytest.approx(1.0)
    assert impacts["capacity"] == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Thor / Var / Vidar
# ---------------------------------------------------------------------------


def test_thor_auto_verdict_executes_and_publishes_action_runs() -> None:
    reg = load_pantheon()
    bus = InMemoryBus(registry=reg)
    thor = Thor(bus=bus)
    run = asyncio.run(
        thor.dispatch_verdict(
            {
                "correlation_id": "c",
                "action_type": "ops.restart-service",
                "risk_verdict": "auto",
                "resource_id": "vm-1",
            }
        )
    )
    assert run.state == ActionRunState.SUCCEEDED
    action_runs = bus.messages_on("object.action-run")
    states_seen = [m.payload["state"] for m in action_runs]
    assert "verdicted" in states_seen
    assert "executing" in states_seen
    assert "succeeded" in states_seen
    assert [m.payload["idempotency_key"] for m in action_runs] == [
        f"c:{state}" for state in states_seen
    ]


def test_thor_ignores_document_admission_verdict() -> None:
    reg = load_pantheon()
    bus = InMemoryBus(registry=reg)
    thor = Thor(bus=bus)

    asyncio.run(
        thor.on_typed_message(
            "object.verdict",
            {
                "producer_principal": "Forseti",
                "kind": "document_ingestion",
                "stage": "received",
                "decision": "admit",
                "correlation_id": "upload-1",
                "document_id": "doc-1",
            },
        )
    )

    assert thor.action_runs == {}
    assert bus.messages_on("object.action-run") == []
    assert thor.behavior_snapshot()["document_verdict_ignored"] == 1


def test_thor_hil_verdict_waits_for_approval_then_executes() -> None:
    reg = load_pantheon()
    bus = InMemoryBus(registry=reg)
    thor = Thor(bus=bus)
    var = Var(bus=bus)
    bus.subscribe("object.action-run", "Var", var.on_typed_message)
    bus.subscribe("object.approval", "Thor", thor.on_typed_message)

    asyncio.run(
        thor.dispatch_verdict(
            {
                "correlation_id": "c-hil",
                "action_type": "remediate.enable-encryption",
                "risk_verdict": "hil",
                "resource_id": "disk-1",
            }
        )
    )
    assert thor.action_runs["c-hil"].state == ActionRunState.HIL_PENDING
    # Operator approves
    asyncio.run(var.decide("c-hil", approver="operator@example.com", decision="approve"))
    assert thor.action_runs["c-hil"].state == ActionRunState.SUCCEEDED


def test_thor_duplicate_approval_does_not_re_execute() -> None:
    # At-least-once delivery can redeliver object.approval. A duplicate
    # approval for an already-executed run MUST NOT re-run the privileged
    # executor (double execution of a completed mutation).
    reg = load_pantheon()
    bus = InMemoryBus(registry=reg)
    calls = {"n": 0}

    async def counting(_ctx: object) -> bool:
        calls["n"] += 1
        return True

    thor = Thor(bus=bus, executor=counting)
    asyncio.run(
        thor.dispatch_verdict(
            {
                "correlation_id": "c-dup-appr",
                "action_type": "remediate.enable-encryption",
                "risk_verdict": "hil",
                "resource_id": "disk-9",
            }
        )
    )
    approval = {"correlation_id": "c-dup-appr", "state": "approved"}
    asyncio.run(thor._handle_approval(dict(approval)))  # noqa: SLF001
    assert thor.action_runs["c-dup-appr"].state == ActionRunState.SUCCEEDED
    assert calls["n"] == 1
    # Redeliver the same approval -> idempotent no-op, executor not called again.
    asyncio.run(thor._handle_approval(dict(approval)))  # noqa: SLF001
    assert calls["n"] == 1
    assert thor.action_runs["c-dup-appr"].state == ActionRunState.SUCCEEDED


def test_thor_rejects_deny_verdict_without_execution() -> None:
    reg = load_pantheon()
    bus = InMemoryBus(registry=reg)
    thor = Thor(bus=bus)
    run = asyncio.run(
        thor.dispatch_verdict(
            {
                "correlation_id": "c-deny",
                "action_type": "remediate.delete-storage",
                "risk_verdict": "deny",
                "resource_id": "sa-x",
            }
        )
    )
    assert run.state == ActionRunState.DENY_DROPPED
    # No executing transition
    states = [m.payload["state"] for m in bus.messages_on("object.action-run")]
    assert "executing" not in states


class _RaisingBus:
    """Bus stub whose publish always raises, to prove the per-resource lock
    is released even when a lifecycle emit fails."""

    def __init__(self) -> None:
        self.registry = load_pantheon()

    def subscribe(self, *args: object, **kwargs: object) -> None:
        return None

    async def publish(self, *args: object, **kwargs: object) -> None:
        raise RuntimeError("bus down")


def test_thor_releases_lock_when_lifecycle_emit_fails() -> None:
    # A bus hiccup during the VERDICTED emit must not leave the resource
    # locked forever - that would deadlock every future action on it. dispatch
    # is fail-safe: it releases the lock and re-raises.
    thor = Thor(bus=_RaisingBus())
    with pytest.raises(RuntimeError, match="bus down"):
        asyncio.run(
            thor.dispatch_verdict(
                {
                    "correlation_id": "c-boom",
                    "action_type": "ops.restart-service",
                    "risk_verdict": "auto",
                    "resource_id": "vm-boom",
                }
            )
        )
    # Lock released despite the failure -> the resource is not deadlocked.
    assert thor.health()["locked_resources"] == 0
    assert "vm-boom" not in thor._resource_locks  # noqa: SLF001


def test_thor_degrades_to_shadow_when_saga_absent() -> None:
    reg = load_pantheon()
    bus = InMemoryBus(registry=reg)
    thor = Thor(bus=bus, saga_available=False)
    run = asyncio.run(
        thor.dispatch_verdict(
            {
                "correlation_id": "c",
                "action_type": "ops.restart-service",
                "risk_verdict": "auto",
                "resource_id": "vm-2",
            }
        )
    )
    assert run.shadow_mode is True
    assert run.state == ActionRunState.SUCCEEDED
    assert run.outcome == "shadow_success"


def test_thor_triggers_vidar_rollback_on_failure() -> None:
    reg = load_pantheon()
    bus = InMemoryBus(registry=reg)

    async def failing(_ctx):
        return False

    async def rollback_executor(action_run):
        return f"rollback:{action_run['correlation_id']}"

    thor = Thor(bus=bus, executor=failing)
    vidar = Vidar(bus=bus, executors={"state_forward_only": rollback_executor})
    bus.subscribe("object.action-run", "Vidar", vidar.on_typed_message)
    bus.subscribe("object.rollback", "Thor", thor.on_typed_message)

    asyncio.run(
        thor.dispatch_verdict(
            {
                "correlation_id": "c-fail",
                "action_type": "ops.restart-service",
                "risk_verdict": "auto",
                "resource_id": "vm-3",
            }
        )
    )
    assert thor.action_runs["c-fail"].state == ActionRunState.ROLLED_BACK
    assert thor.action_runs["c-fail"].rollback_ref == "rollback:c-fail"
    assert "vm-3" not in thor._resource_locks
    rollbacks = bus.messages_on("object.rollback")
    assert len(rollbacks) == 1
    assert rollbacks[0].payload["state"] == "succeeded"


def test_vidar_missing_executor_fails_closed_and_releases_thor_lock() -> None:
    reg = load_pantheon()
    bus = InMemoryBus(registry=reg)

    async def failing(_ctx):
        return False

    thor = Thor(bus=bus, executor=failing)
    vidar = Vidar(bus=bus)
    bus.subscribe("object.action-run", "Vidar", vidar.on_typed_message)
    bus.subscribe("object.rollback", "Thor", thor.on_typed_message)

    run = asyncio.run(
        thor.dispatch_verdict(
            {
                "correlation_id": "c-no-rollback",
                "action_type": "ops.failover-primary",
                "risk_verdict": "auto",
                "resource_id": "db-1",
                "rollback_contract": "scripted",
            }
        )
    )

    assert run.state == ActionRunState.ROLLBACK_FAILED
    assert run.rollback_ref is None
    assert "db-1" not in thor._resource_locks
    rollback = bus.messages_on("object.rollback")[0].payload
    assert rollback["state"] == "failed"
    assert rollback["contract"] == "scripted"


def test_vidar_rollback_is_idempotent_per_correlation() -> None:
    # At-least-once delivery can redeliver the same failed ActionRun. A real
    # rollback contract (PITR restore, revert) is not a no-op if applied
    # twice, so Vidar rolls a correlation back at most once.
    reg = load_pantheon()
    bus = InMemoryBus(registry=reg)
    vidar = Vidar(bus=bus)
    failed = {
        "correlation_id": "c-dup",
        "action_type": "remediate.delete-storage",
        "resource_id": "sa-1",
        "state": "failed",
    }
    asyncio.run(vidar.on_typed_message("object.action-run", dict(failed)))
    second = asyncio.run(vidar.rollback(dict(failed)))
    assert second is None  # duplicate rollback refused
    assert len(vidar.records) == 1
    assert len(bus.messages_on("object.rollback")) == 1


def test_thor_per_resource_mutex_prevents_concurrent_runs() -> None:
    reg = load_pantheon()
    bus = InMemoryBus(registry=reg)
    thor = Thor(bus=bus)
    # First dispatch: HIL, so it stays pending
    asyncio.run(
        thor.dispatch_verdict(
            {
                "correlation_id": "c1",
                "action_type": "remediate.enable-encryption",
                "risk_verdict": "hil",
                "resource_id": "vm-lock",
            }
        )
    )
    # Second dispatch on same resource returns the existing (pending) run
    run2 = asyncio.run(
        thor.dispatch_verdict(
            {
                "correlation_id": "c2",
                "action_type": "ops.restart-service",
                "risk_verdict": "auto",
                "resource_id": "vm-lock",
            }
        )
    )
    # It should be the same object (existing pending), not a new one
    assert run2.correlation_id == "c1"


def test_var_quorum_two_approvers_required() -> None:
    reg = load_pantheon()
    bus = InMemoryBus(registry=reg)
    var = Var(bus=bus)
    # Simulate Thor emitting a hil_pending action_run with quorum_required=2
    asyncio.run(
        var.on_typed_message(
            "object.action-run",
            {
                "correlation_id": "c",
                "action_type": "remediate.delete-storage",
                "resource_id": "sa-1",
                "state": "hil_pending",
                "quorum_required": 2,
            },
        )
    )
    # First approver: no approval yet
    result1 = asyncio.run(var.decide("c", approver="a@example.com", decision="approve"))
    assert result1 is None
    # Second approver reaches quorum
    result2 = asyncio.run(var.decide("c", approver="b@example.com", decision="approve"))
    assert result2 is not None
    assert result2["state"] == "approved"


def test_var_rejects_self_approval_twice() -> None:
    reg = load_pantheon()
    bus = InMemoryBus(registry=reg)
    var = Var(bus=bus)
    asyncio.run(
        var.on_typed_message(
            "object.action-run",
            {
                "correlation_id": "c",
                "action_type": "x",
                "state": "hil_pending",
                "quorum_required": 2,
            },
        )
    )
    asyncio.run(var.decide("c", approver="a@example.com", decision="approve"))
    with pytest.raises(ValueError, match="self-approve"):
        asyncio.run(var.decide("c", approver="a@example.com", decision="approve"))


def _var_with_pending(
    correlation: str = "c-hil",
    *,
    quorum: int = 1,
    initiator: str | None = None,
) -> Var:
    reg = load_pantheon()
    var = Var(bus=InMemoryBus(registry=reg))
    payload: dict[str, object] = {
        "correlation_id": correlation,
        "action_type": "remediate.delete-storage",
        "state": "hil_pending",
        "quorum_required": quorum,
    }
    if initiator is not None:
        payload["initiator_principal"] = initiator
    asyncio.run(var.on_typed_message("object.action-run", payload))
    return var


def test_var_rejects_initiator_self_approval() -> None:
    # The principal that initiated the action can never approve it -
    # approval and initiation are distinct principals (pantheon invariant).
    var = _var_with_pending(quorum=2, initiator="op@example.com")
    with pytest.raises(ValueError, match="no self-approval"):
        asyncio.run(var.decide("c-hil", approver="op@example.com", decision="approve"))
    # A padded variant must not slip past the trimmed comparison.
    with pytest.raises(ValueError, match="no self-approval"):
        asyncio.run(var.decide("c-hil", approver="  op@example.com  ", decision="approve"))


def test_var_rejects_blank_approver() -> None:
    var = _var_with_pending()
    with pytest.raises(ValueError, match="non-empty principal"):
        asyncio.run(var.decide("c-hil", approver="   ", decision="approve"))


def test_var_unknown_decision_raises() -> None:
    var = _var_with_pending()
    with pytest.raises(ValueError, match="unknown decision"):
        asyncio.run(var.decide("c-hil", approver="a@example.com", decision="maybe"))


def test_var_reject_flow_emits_rejected_approval() -> None:
    var = _var_with_pending(quorum=2)
    result = asyncio.run(var.decide("c-hil", approver="a@example.com", decision="reject"))
    assert result is not None
    assert result["state"] == "rejected"
    # The ticket is consumed, so a second decide finds nothing.
    assert asyncio.run(var.decide("c-hil", approver="b@example.com", decision="approve")) is None


def test_var_decide_unknown_correlation_returns_none() -> None:
    var = _var_with_pending()
    assert (
        asyncio.run(var.decide("does-not-exist", approver="a@example.com", decision="approve"))
        is None
    )


def test_var_ingest_ignores_non_hil_and_duplicate_runs() -> None:
    var = _var_with_pending("c-dup")
    # Wrong topic is ignored.
    asyncio.run(
        var.on_typed_message("object.verdict", {"correlation_id": "z", "state": "hil_pending"})
    )
    # Right topic but not hil_pending is ignored.
    asyncio.run(var.on_typed_message("object.action-run", {"correlation_id": "z", "state": "auto"}))
    # Empty correlation is ignored.
    asyncio.run(
        var.on_typed_message("object.action-run", {"correlation_id": "", "state": "hil_pending"})
    )
    # A duplicate of an already-pending correlation does not overwrite it.
    asyncio.run(
        var.on_typed_message(
            "object.action-run",
            {"correlation_id": "c-dup", "action_type": "other", "state": "hil_pending"},
        )
    )
    tickets = {t.correlation_id for t in var.pending_tickets()}
    assert tickets == {"c-dup"}
    assert var.pending_tickets()[0].action_type == "remediate.delete-storage"


def test_var_quorum_met_without_bus_still_consumes_ticket() -> None:
    # bus=None: the approval is not published but the ticket still
    # resolves and is removed from the pending queue.
    var = _var_with_pending("c-nobus", quorum=1)
    var.bus = None
    result = asyncio.run(var.decide("c-nobus", approver="a@example.com", decision="approve"))
    assert result is not None
    assert result["state"] == "approved"
    assert var.pending_tickets() == ()


def test_var_bind_bus_late_binds_the_publisher() -> None:
    # A composition root may construct Var before the bus exists and bind
    # it afterwards; the setter must take effect.
    reg = load_pantheon()
    bus = InMemoryBus(registry=reg)
    var = Var(bus=None)
    assert var.bus is None
    var.bind_bus(bus)
    assert var.bus is bus


def test_var_introspect_scoped_general_and_empty() -> None:
    var = _var_with_pending("c-one", quorum=2)
    # Naming a pending correlation scopes the answer to that ticket.
    scoped = asyncio.run(var.introspect("what is the status of c-one?", {}))
    assert scoped.facts["correlation_id"] == "c-one"
    assert scoped.facts["quorum_required"] == 2
    assert "c-one" in scoped.answer
    # No correlation named -> a general pending summary.
    general = asyncio.run(var.introspect("what is pending?", {}))
    assert general.facts["pending_hil"] == 1
    assert "pending" in general.answer
    # A fresh approver with no queue -> the empty-queue answer.
    empty = Var(bus=None)
    empty_result = asyncio.run(empty.introspect("anything to approve?", {}))
    assert empty_result.facts["pending_hil"] == 0
    assert "No HIL approvals pending" in empty_result.answer


def test_var_admin_card_dedup_updates_counter_in_place() -> None:
    var = Var(bus=None)
    payload = {
        "initiator_principal": "svc@example.com",
        "attempted_action": "delete-role-assignment",
        "severity": "high",
        "counter": 1,
    }
    first = asyncio.run(var.deliver_admin_card(payload))
    assert first.counter == 1
    assert len(var.admin_channel.cards) == 1
    # A repeat for the same (initiator, action) updates the counter in
    # place rather than posting a second card.
    second = asyncio.run(var.deliver_admin_card({**payload, "counter": 4}))
    assert second.counter == 4
    assert len(var.admin_channel.cards) == 1
    assert var.admin_channel.cards[-1].counter == 4


# ---------------------------------------------------------------------------
# End-to-end pipeline: Huginn -> Heimdall -> Forseti -> Thor -> Vidar -> Saga
# ---------------------------------------------------------------------------


def test_end_to_end_shadow_verdict_loop() -> None:
    reg = load_pantheon()
    bus = InMemoryBus(registry=reg)
    huginn = Huginn(bus=bus)
    heimdall = Heimdall(bus=bus, rate_threshold=3)
    forseti = Forseti(bus=bus)
    thor = Thor(bus=bus)
    vidar = Vidar(bus=bus)
    saga = Saga()

    bus.subscribe("object.event", "Heimdall", heimdall.on_typed_message)
    bus.subscribe("object.anomaly", "Forseti", forseti.on_typed_message)
    bus.subscribe("object.event", "Forseti", forseti.on_typed_message)
    bus.subscribe("object.verdict", "Thor", thor.on_typed_message)
    bus.subscribe("object.action-run", "Vidar", vidar.on_typed_message)
    for terminal in (
        "object.verdict",
        "object.action-run",
        "object.rollback",
        "object.approval",
        "object.security-event",
    ):
        bus.subscribe(terminal, "Saga", saga.on_typed_message)

    # Fire 10 restart_needed events - each matches Forseti's auto rule
    for i in range(10):
        asyncio.run(
            huginn.ingest(
                {
                    "id": f"evt-{i}",
                    "correlation_id": f"corr-{i}",
                    "resource_id": f"vm-{i}",
                    "event_type": "restart_needed",
                }
            )
        )

    verdicts = bus.messages_on("object.verdict")
    action_runs = bus.messages_on("object.action-run")

    # Every event that has a rule match must yield exactly one verdict.
    assert len(verdicts) == 10
    # Every verdict must produce (at least) verdicted/executing/succeeded states.
    assert len(action_runs) >= 30
    # Zero policy escapes: no state == 'failed' or 'deny_dropped'
    escaped = [a for a in action_runs if a.payload["state"] in ("failed", "deny_dropped")]
    assert escaped == []
    # Saga captured every terminal state
    saga.audit_chain.verify()
    assert len(saga.audit_chain.entries) >= len(verdicts) + len(action_runs)
