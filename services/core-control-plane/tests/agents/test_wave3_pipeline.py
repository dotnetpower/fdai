"""Wave 3 pipeline behavior tests."""

from __future__ import annotations

import asyncio
import hashlib
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from fdai.agents._framework.action_run_identity import action_run_identity_digest
from fdai.agents._framework.bus import InMemoryBus
from fdai.agents._framework.registry import load_pantheon
from fdai.agents.forseti import Forseti
from fdai.agents.heimdall import Heimdall
from fdai.agents.huginn import Huginn
from fdai.agents.saga import Saga
from fdai.agents.thor import ActionRun, ActionRunState, Thor
from fdai.agents.var import Var
from fdai.agents.vidar import RollbackClaimInProgressError, Vidar
from fdai.shared.contracts.models import IncidentSeverity


def _approval_for_run(run, *, state: str = "approved") -> dict[str, object]:  # noqa: ANN001
    return {
        "producer_principal": "Var",
        "kind": "action",
        "correlation_id": run.correlation_id,
        "idempotency_key": run.idempotency_key,
        "action_id": run.action_id,
        "action_type": run.action_type,
        "action_run_identity": action_run_identity_digest(run.to_dict()),
        "action_idempotency_key": run.idempotency_key,
        "resource_id": run.resource_id,
        "rollback_contract": run.rollback_contract,
        "state": state,
    }


def _rollback_for_run(
    run,  # noqa: ANN001
    *,
    state: str = "succeeded",
    rollback_ref: str | None = "rollback:test",
) -> dict[str, object]:
    return {
        "producer_principal": "Vidar",
        "kind": "action",
        "correlation_id": run.correlation_id,
        "action_run_identity": action_run_identity_digest(run.to_dict()),
        "action_type": run.action_type,
        "resource_id": run.resource_id,
        "contract": run.rollback_contract,
        "state": state,
        "rollback_ref": rollback_ref,
    }


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


def test_huginn_preserves_a_valid_source_event_time() -> None:
    huginn = Huginn(clock=lambda: datetime(2026, 9, 14, 2, 0, 1, tzinfo=UTC))

    event = asyncio.run(
        huginn.ingest(
            {
                "id": "evt-time-1",
                "resource_id": "vm-1",
                "event_type": "cpu_spike",
                "detected_at": "2026-09-14T02:00:00Z",
            }
        )
    )

    assert event is not None
    assert event["occurred_at"] == "2026-09-14T02:00:00+00:00"
    assert event["ingested_at"] == "2026-09-14T02:00:01+00:00"


def test_huginn_rejects_a_malformed_source_event_time() -> None:
    huginn = Huginn()

    with pytest.raises(ValueError, match="detected_at MUST be RFC 3339"):
        asyncio.run(
            huginn.ingest(
                {
                    "id": "evt-time-1",
                    "resource_id": "vm-1",
                    "event_type": "cpu_spike",
                    "detected_at": "not-a-timestamp",
                }
            )
        )


def test_huginn_rejects_a_source_time_after_ingestion() -> None:
    huginn = Huginn(clock=lambda: datetime(2026, 9, 14, 2, 0, tzinfo=UTC))

    with pytest.raises(ValueError, match="after trusted ingestion time"):
        asyncio.run(
            huginn.ingest(
                {
                    "id": "evt-time-1",
                    "resource_id": "vm-1",
                    "event_type": "cpu_spike",
                    "detected_at": "2026-09-14T02:00:01Z",
                    "ingested_at": "2099-01-01T00:00:00Z",
                }
            )
        )


def test_huginn_rejects_a_naive_ingestion_clock() -> None:
    huginn = Huginn(clock=lambda: datetime(2026, 9, 14, 2, 0))

    with pytest.raises(ValueError, match="clock MUST return a timezone-aware"):
        asyncio.run(
            huginn.ingest(
                {
                    "id": "evt-time-1",
                    "resource_id": "vm-1",
                    "event_type": "cpu_spike",
                }
            )
        )


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


def test_heimdall_attaches_bounded_operational_evidence() -> None:
    reg = load_pantheon()
    bus = InMemoryBus(registry=reg)

    async def collect(event: dict[str, object]) -> dict[str, object]:
        assert event["resource_id"] == "kubernetes.namespace/example-app"
        return {
            "observe.kubernetes.capacity": {
                "status": "available",
                "payload": {"findings": [{"decision": "hold"}]},
            }
        }

    heimdall = Heimdall(bus=bus, rate_threshold=2, operational_evidence_hook=collect)
    for index in range(2):
        asyncio.run(
            heimdall.on_typed_message(
                "object.event",
                {
                    "resource_id": "kubernetes.namespace/example-app",
                    "resource_type": "kubernetes.namespace",
                    "event_type": "scheduling.failure",
                    "correlation_id": "capacity-episode",
                    "idempotency_key": f"capacity-{index}",
                },
            )
        )

    anomaly = bus.messages_on("object.anomaly")[0].payload
    assert anomaly["operational_evidence"] == {
        "observe.kubernetes.capacity": {
            "status": "available",
            "payload": {"findings": [{"decision": "hold"}]},
        }
    }


def test_heimdall_preserves_anomaly_when_operational_evidence_fails() -> None:
    reg = load_pantheon()
    bus = InMemoryBus(registry=reg)

    async def fail(event: dict[str, object]) -> dict[str, object]:
        raise RuntimeError(event["resource_id"])

    heimdall = Heimdall(bus=bus, rate_threshold=1, operational_evidence_hook=fail)
    asyncio.run(
        heimdall.on_typed_message(
            "object.event",
            {
                "resource_id": "kubernetes.namespace/example-app",
                "resource_type": "kubernetes.namespace",
                "event_type": "scheduling.failure",
                "correlation_id": "capacity-episode",
                "idempotency_key": "capacity-1",
            },
        )
    )

    anomaly = bus.messages_on("object.anomaly")[0].payload
    assert anomaly["operational_evidence"] == {
        "observe.kubernetes.capacity": {
            "status": "unavailable",
            "reason": "provider_error",
        }
    }


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


def test_heimdall_records_burst_without_incident_candidate_when_correlation_disabled() -> None:
    reg = load_pantheon()
    bus = InMemoryBus(registry=reg)
    candidates: list[dict[str, object]] = []

    async def capture(candidate: dict[str, object]) -> bool:
        candidates.append(candidate)
        return True

    heimdall = Heimdall(bus=bus, rate_threshold=2, incident_candidate_hook=capture)
    for index in range(2):
        asyncio.run(
            heimdall.on_typed_message(
                "object.event",
                {
                    "resource_id": "storage-example",
                    "event_type": "inventory.resource_changed",
                    "incident_correlation": "none",
                    "correlation_id": "inventory:storage-example",
                    "idempotency_key": f"inventory-{index}",
                },
            )
        )

    assert len(bus.messages_on("object.anomaly")) == 1
    assert candidates == []


def test_heimdall_preserves_high_severity_on_incident_candidate() -> None:
    candidates: list[dict[str, object]] = []

    async def capture(candidate: dict[str, object]) -> bool:
        candidates.append(candidate)
        return True

    heimdall = Heimdall(rate_threshold=2, incident_candidate_hook=capture)
    for index in range(2):
        asyncio.run(
            heimdall.on_typed_message(
                "object.event",
                {
                    "resource_id": "api-example",
                    "event_type": "availability.probe_failed",
                    "incident_correlation": "correlate",
                    "correlation_id": "episode-1",
                    "idempotency_key": f"failure-{index}",
                    "severity": "high",
                },
            )
        )

    assert candidates[0]["severity"] == "high"
    assert candidates[0]["incident_correlation"] == "correlate"


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"rate_threshold": 0}, "rate_threshold"),
        ({"rate_window": 0}, "rate_window"),
    ],
)
def test_heimdall_rejects_non_positive_repeat_config(kwargs: dict[str, int], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        Heimdall(**kwargs)


def test_heimdall_does_not_open_anomaly_for_sparse_monitoring_events() -> None:
    reg = load_pantheon()
    bus = InMemoryBus(registry=reg)
    clock = {"now": 0.0}
    candidates: list[dict[str, object]] = []

    async def capture(candidate: dict[str, object]) -> bool:
        candidates.append(candidate)
        return True

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

    async def capture(candidate: dict[str, object]) -> bool:
        candidates.append(candidate)
        return True

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

    async def open_candidate(candidate: dict[str, object]) -> bool:
        await workflow.open_from_agent(
            producer_principal=str(candidate["producer_principal"]),
            correlation_keys=(f"resource:{candidate['resource_id']}",),
            severity=IncidentSeverity.SEV3,
            member_event_ids=(UUID("00000000-0000-0000-0000-000000000001"),),
            reason=str(candidate["reason_code"]),
        )
        return True

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
                "idempotency_key": "event-1",
            },
        )
    )
    verdicts = bus.messages_on("object.verdict")
    assert len(verdicts) == 1
    assert verdicts[0].payload["risk_verdict"] == "auto"
    assert verdicts[0].payload["action_type"] == "remediate.disable-public-access"
    assert verdicts[0].payload["idempotency_key"] == "event-1"


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
                "idempotency_key": "document.inspected:version-hil",
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
    assert approval["idempotency_key"] == "document.inspected:version-hil"


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
            {
                "correlation_id": "weighted-arbitration",
                "resource_id": "vm-7",
                "recommendation": "scale_down",
                "ratio": 1.5,
            },
        )
    )
    asyncio.run(
        f.on_typed_message(
            "object.capacity-forecast",
            {
                "correlation_id": "weighted-arbitration",
                "resource_id": "vm-7",
                "recommendation": "scale_up",
                "forecast_util": 0.9,
            },
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
            {
                "correlation_id": "fallback-impact",
                "resource_id": "vm-8",
                "recommendation": "scale_down",
                "impact": "x",
                "ratio": "y",
            },
        )
    )
    asyncio.run(
        f.on_typed_message(
            "object.capacity-forecast",
            {
                "resource_id": "vm-8",
                "correlation_id": "fallback-impact",
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
                "idempotency_key": "action-1",
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
    assert {m.payload["action_idempotency_key"] for m in action_runs} == {"action-1"}


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
                "resolved_autonomy_ceiling": "enforce_hil",
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
    run = asyncio.run(
        thor.dispatch_verdict(
            {
                "correlation_id": "c-dup-appr",
                "action_type": "remediate.enable-encryption",
                "risk_verdict": "hil",
                "resolved_autonomy_ceiling": "enforce_hil",
                "resource_id": "disk-9",
            }
        )
    )
    approval = _approval_for_run(run)
    asyncio.run(thor._handle_approval(dict(approval)))  # noqa: SLF001
    assert thor.action_runs["c-dup-appr"].state == ActionRunState.SUCCEEDED
    assert calls["n"] == 1
    # Redeliver the same approval -> idempotent no-op, executor not called again.
    asyncio.run(thor._handle_approval(dict(approval)))  # noqa: SLF001
    assert calls["n"] == 1
    assert thor.action_runs["c-dup-appr"].state == ActionRunState.SUCCEEDED


def test_thor_rejects_stale_approval_for_reused_correlation() -> None:
    calls: list[str] = []

    async def execute(context):
        calls.append(context["run"].action_type)
        return True

    correlation = "c-reused-approval"
    old_run = asyncio.run(
        Thor().dispatch_verdict(
            {
                "correlation_id": correlation,
                "action_type": "ops.restart-service",
                "risk_verdict": "hil",
                "resource_id": "vm-old",
            }
        )
    )
    stale_approval = _approval_for_run(old_run)
    thor = Thor(executor=execute)
    current = asyncio.run(
        thor.dispatch_verdict(
            {
                "correlation_id": correlation,
                "action_type": "remediate.delete-storage",
                "risk_verdict": "hil",
                "resource_id": "storage-current",
            }
        )
    )

    with pytest.raises(ValueError, match="identity does not match"):
        asyncio.run(thor.on_typed_message("object.approval", stale_approval))

    assert current.state is ActionRunState.HIL_PENDING
    assert calls == []
    assert thor.behavior_snapshot()["approval:identity_mismatch"] == 1


def test_thor_rejects_live_correlation_reuse() -> None:
    thor = Thor()
    previous = asyncio.run(
        thor.dispatch_verdict(
            {
                "correlation_id": "c-live-correlation-reuse",
                "idempotency_key": "generation-old",
                "action_type": "ops.restart-service",
                "risk_verdict": "deny",
                "resource_id": "vm-old",
            }
        )
    )

    with pytest.raises(ValueError, match="correlation cannot be reused"):
        asyncio.run(
            thor.dispatch_verdict(
                {
                    "correlation_id": previous.correlation_id,
                    "idempotency_key": "generation-current",
                    "action_type": "remediate.delete-storage",
                    "risk_verdict": "hil",
                    "resource_id": "storage-current",
                }
            )
        )

    assert thor.action_runs[previous.correlation_id] is previous
    assert thor.behavior_snapshot()["dispatch:correlation_reuse_rejected"] == 1


def test_thor_ignores_stale_rollback_for_reused_correlation() -> None:
    correlation = "c-reused-rollback"
    old_run = ActionRun(
        correlation_id=correlation,
        action_type="ops.restart-service",
        resource_id="vm-old",
        state=ActionRunState.FAILED,
        verdict="auto",
    )
    stale_rollback = _rollback_for_run(old_run, rollback_ref="rollback:old")
    current = ActionRun(
        correlation_id=correlation,
        action_type="remediate.delete-storage",
        resource_id="storage-current",
        state=ActionRunState.FAILED,
        verdict="auto",
    )
    thor = Thor()
    thor.action_runs[correlation] = current
    thor._resource_locks.add("storage-current")

    asyncio.run(thor.on_typed_message("object.rollback", stale_rollback))

    assert current.state is ActionRunState.FAILED
    assert current.rollback_ref is None
    assert "storage-current" in thor._resource_locks
    assert thor.behavior_snapshot()["rollback:identity_mismatch"] == 1


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
                    "resolved_autonomy_ceiling": "enforce_auto",
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
                "resolved_autonomy_ceiling": "enforce_auto",
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
                "resolved_autonomy_ceiling": "enforce_auto",
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


def test_vidar_missing_executor_fails_closed_and_retains_thor_lock() -> None:
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
                "resolved_autonomy_ceiling": "enforce_auto",
                "resource_id": "db-1",
                "rollback_contract": "scripted",
            }
        )
    )

    assert run.state == ActionRunState.ROLLBACK_FAILED
    assert run.rollback_ref is None
    assert "db-1" in thor._resource_locks
    rollback = bus.messages_on("object.rollback")[0].payload
    assert rollback["state"] == "failed"
    assert rollback["contract"] == "scripted"


def test_vidar_blank_receipt_fails_closed_and_retains_thor_lock() -> None:
    bus = InMemoryBus(registry=load_pantheon())

    async def failing(_ctx):
        return False

    async def blank_rollback_receipt(_action_run):
        return "   "

    thor = Thor(bus=bus, executor=failing)
    vidar = Vidar(
        bus=bus,
        executors={"state_forward_only": blank_rollback_receipt},
    )
    bus.subscribe("object.action-run", "Vidar", vidar.on_typed_message)
    bus.subscribe("object.rollback", "Thor", thor.on_typed_message)

    run = asyncio.run(
        thor.dispatch_verdict(
            {
                "correlation_id": "c-blank-rollback",
                "action_type": "ops.restart-service",
                "risk_verdict": "auto",
                "resolved_autonomy_ceiling": "enforce_auto",
                "resource_id": "vm-blank-rollback",
            }
        )
    )

    assert run.state == ActionRunState.ROLLBACK_FAILED
    assert run.rollback_ref is None
    assert "vm-blank-rollback" in thor._resource_locks
    rollback = bus.messages_on("object.rollback")[0].payload
    assert rollback["state"] == "failed"
    assert rollback["rollback_ref"] is None


def test_thor_rejects_blank_succeeded_rollback_receipt() -> None:
    bus = InMemoryBus(registry=load_pantheon())

    async def failing(_ctx):
        return False

    thor = Thor(bus=bus, executor=failing)
    run = asyncio.run(
        thor.dispatch_verdict(
            {
                "correlation_id": "c-forged-blank-rollback",
                "action_type": "ops.restart-service",
                "risk_verdict": "auto",
                "resolved_autonomy_ceiling": "enforce_auto",
                "resource_id": "vm-forged-blank-rollback",
            }
        )
    )
    assert run.state == ActionRunState.FAILED

    asyncio.run(
        thor.on_typed_message(
            "object.rollback",
            _rollback_for_run(run, rollback_ref="   "),
        )
    )

    assert run.state == ActionRunState.ROLLBACK_FAILED
    assert run.outcome == "rollback_failed"
    assert run.rollback_ref is None
    assert "vm-forged-blank-rollback" in thor._resource_locks


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


def test_vidar_retries_publication_without_repeating_rollback() -> None:
    class _FlakyRollbackBus:
        def __init__(self) -> None:
            self.publish_calls = 0
            self.payloads: list[dict[str, object]] = []

        def subscribe(self, topic, agent_name, handler):  # noqa: ANN001, ANN201
            del topic, agent_name, handler

        async def publish(self, principal, topic, payload):  # noqa: ANN001, ANN201
            self.publish_calls += 1
            if self.publish_calls == 1:
                raise RuntimeError("broker unavailable")
            assert principal == "Vidar"
            assert topic == "object.rollback"
            self.payloads.append(dict(payload))

    rollback_calls: list[str] = []

    async def rollback_executor(action_run):
        rollback_calls.append(action_run["correlation_id"])
        return "rollback:c-publish-retry"

    bus = _FlakyRollbackBus()
    vidar = Vidar(bus=bus, executors={"state_forward_only": rollback_executor})
    failed = {
        "correlation_id": "c-publish-retry",
        "action_type": "ops.restart-service",
        "resource_id": "vm-3",
        "state": "failed",
    }

    with pytest.raises(RuntimeError, match="broker unavailable"):
        asyncio.run(vidar.rollback(dict(failed)))

    retried = asyncio.run(vidar.rollback(dict(failed)))
    duplicate = asyncio.run(vidar.rollback(dict(failed)))

    assert rollback_calls == ["c-publish-retry"]
    assert len(vidar.records) == 1
    assert retried is vidar.records[0]
    assert duplicate is None
    assert bus.publish_calls == 2
    assert bus.payloads[0]["rollback_ref"] == "rollback:c-publish-retry"


def test_vidar_replays_durable_terminal_result_after_restart() -> None:
    from fdai.shared.providers.testing.state_store import InMemoryStateStore

    calls: list[str] = []

    async def rollback_executor(action_run):
        calls.append(action_run["correlation_id"])
        return "rollback:c-durable-restart"

    store = InMemoryStateStore()
    failed = {
        "correlation_id": "c-durable-restart",
        "action_type": "ops.restart-service",
        "resource_id": "vm-3",
        "state": "failed",
    }
    first = Vidar(
        bus=None,
        executors={"state_forward_only": rollback_executor},
        state_store=store,
    )
    completed = asyncio.run(first.rollback(dict(failed)))

    bus = InMemoryBus(registry=load_pantheon())
    restarted = Vidar(
        bus=bus,
        executors={"state_forward_only": rollback_executor},
        state_store=store,
    )
    replayed = asyncio.run(restarted.rollback(dict(failed)))

    assert completed is not None and replayed == completed
    assert calls == ["c-durable-restart"]
    assert len(bus.messages_on("object.rollback")) == 1


def test_vidar_isolates_changed_rollback_command_inputs() -> None:
    from fdai.shared.providers.testing.state_store import InMemoryStateStore

    calls: list[str] = []

    async def rollback_executor(action_run):
        restore_point = action_run["params"]["restore_point"]
        calls.append(restore_point)
        return f"restore:{restore_point}"

    store = InMemoryStateStore()
    original = {
        "correlation_id": "c-command-identity",
        "action_type": "ops.restore-database",
        "action_id": "action-1",
        "resource_id": "db-1",
        "state": "failed",
        "rollback_contract": "pitr",
        "params": {"restore_point": "A"},
        "workflow_action": {
            "workflow_id": "recovery",
            "workflow_version": "1.0.0",
            "step_id": "restore",
            "attempt": 1,
        },
    }
    first = Vidar(executors={"pitr": rollback_executor}, state_store=store)
    completed = asyncio.run(first.rollback(dict(original)))
    assert completed is not None
    assert completed.rollback_ref == "restore:A"

    changed = {
        **original,
        "params": {"restore_point": "B"},
    }
    changed_result = asyncio.run(first.rollback(dict(changed)))

    assert changed_result is not None
    assert changed_result.rollback_ref == "restore:B"
    assert changed_result.action_run_identity != completed.action_run_identity
    assert calls == ["A", "B"]


def test_vidar_ignores_regenerated_terminal_delivery_metadata() -> None:
    from fdai.shared.providers.testing.state_store import InMemoryStateStore

    calls: list[dict[str, object]] = []

    async def rollback_executor(action_run):
        calls.append(dict(action_run))
        return "rollback:c-terminal-replay"

    store = InMemoryStateStore()
    failed = {
        "producer_principal": "Thor",
        "schema_version": "1.0.0",
        "envelope_schema_version": "1.0.0",
        "correlation_id": "c-terminal-replay",
        "idempotency_key": "c-terminal-replay:failed",
        "action_idempotency_key": "action-terminal-replay",
        "action_type": "ops.restart-service",
        "resource_id": "vm-3",
        "state": "failed",
        "rollback_contract": "state_forward_only",
        "params": {"reason": "healthcheck"},
        "terminal_at": "2026-09-15T00:00:00Z",
    }
    first = Vidar(
        executors={"state_forward_only": rollback_executor},
        state_store=store,
    )
    completed = asyncio.run(first.rollback(dict(failed)))
    assert completed is not None

    restarted = Vidar(
        executors={"state_forward_only": rollback_executor},
        state_store=store,
    )
    replayed = asyncio.run(
        restarted.rollback(
            {
                **failed,
                "terminal_at": "2026-09-15T00:05:00Z",
            }
        )
    )

    assert replayed == completed
    assert len(calls) == 1
    assert "terminal_at" not in calls[0]
    assert "schema_version" not in calls[0]
    assert calls[0]["params"] == {"reason": "healthcheck"}


@pytest.mark.parametrize(
    "corruption",
    ["missing_schema", "missing_success_receipt", "blank_success_receipt"],
)
def test_vidar_rejects_noncanonical_durable_terminal_state(
    corruption: str,
) -> None:
    from fdai.shared.providers.testing.state_store import InMemoryStateStore

    calls: list[str] = []

    async def rollback_executor(action_run):
        calls.append(action_run["correlation_id"])
        return "rollback:c-malformed-terminal"

    store = InMemoryStateStore()
    failed = {
        "correlation_id": "c-malformed-terminal",
        "action_type": "ops.restart-service",
        "resource_id": "vm-3",
        "state": "failed",
    }
    first = Vidar(
        executors={"state_forward_only": rollback_executor},
        state_store=store,
    )
    completed = asyncio.run(first.rollback(dict(failed)))
    assert completed is not None

    correlation_digest = hashlib.sha256(b"c-malformed-terminal").hexdigest()
    identity_digest = completed.action_run_identity.removeprefix("sha256:")
    state_key = f"pantheon/vidar/rollback/{correlation_digest}/{identity_digest}/state"
    terminal = asyncio.run(store.read_state(state_key))
    assert terminal is not None
    corrupted = dict(terminal)
    if corruption == "missing_schema":
        for field in (
            "schema_version",
            "revision",
            "claim_owner_token",
            "lease_expires_at",
            "completed_by_owner_token",
        ):
            corrupted.pop(field)
    elif corruption == "missing_success_receipt":
        corrupted["rollback_ref"] = None
    else:
        corrupted["rollback_ref"] = "   "
    asyncio.run(store.write_state(state_key, corrupted))

    restarted = Vidar(
        executors={"state_forward_only": rollback_executor},
        state_store=store,
    )
    with pytest.raises(RuntimeError, match="terminal record is malformed"):
        asyncio.run(restarted.rollback(dict(failed)))

    assert calls == ["c-malformed-terminal"]


def test_vidar_marks_interrupted_durable_claim_execution_unknown() -> None:
    from fdai.shared.providers.testing.state_store import InMemoryStateStore

    calls: list[str] = []

    async def interrupted_executor(action_run):
        calls.append(action_run["correlation_id"])
        raise asyncio.CancelledError

    store = InMemoryStateStore()
    failed = {
        "correlation_id": "c-interrupted-claim",
        "action_type": "ops.failover-primary",
        "resource_id": "db-1",
        "state": "failed",
        "rollback_contract": "pitr",
    }
    first = Vidar(
        bus=None,
        executors={"pitr": interrupted_executor},
        state_store=store,
        clock=lambda: datetime(2026, 9, 15, tzinfo=UTC),
        claim_lease=timedelta(seconds=30),
    )
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(first.rollback(dict(failed)))

    bus = InMemoryBus(registry=load_pantheon())
    restarted = Vidar(
        bus=bus,
        executors={"pitr": interrupted_executor},
        state_store=store,
        clock=lambda: datetime(2026, 9, 15, 0, 0, 31, tzinfo=UTC),
        claim_lease=timedelta(seconds=30),
    )
    recovered = asyncio.run(restarted.rollback(dict(failed)))

    assert recovered is not None
    assert recovered.state == "execution_unknown"
    assert calls == ["c-interrupted-claim"]
    published = bus.messages_on("object.rollback")
    assert len(published) == 1
    assert published[0].payload["state"] == "execution_unknown"


def test_vidar_keeps_another_live_replica_claim_retryable() -> None:
    from fdai.shared.providers.testing.state_store import InMemoryStateStore

    async def _run() -> tuple[object, list[str]]:
        entered = asyncio.Event()
        release = asyncio.Event()
        calls: list[str] = []

        async def rollback_executor(action_run):
            calls.append(action_run["correlation_id"])
            entered.set()
            await release.wait()
            return "rollback:c-live-claim"

        store = InMemoryStateStore()
        now = datetime(2026, 9, 15, tzinfo=UTC)
        first = Vidar(
            executors={"state_forward_only": rollback_executor},
            state_store=store,
            clock=lambda: now,
            claim_lease=timedelta(minutes=1),
        )
        second = Vidar(
            executors={"state_forward_only": rollback_executor},
            state_store=store,
            clock=lambda: now + timedelta(seconds=30),
            claim_lease=timedelta(minutes=1),
        )
        failed = {
            "correlation_id": "c-live-claim",
            "action_type": "ops.restart-service",
            "resource_id": "vm-3",
            "state": "failed",
        }
        owner_task = asyncio.create_task(first.rollback(dict(failed)))
        await entered.wait()
        with pytest.raises(
            RollbackClaimInProgressError,
            match="rollback claim remains active until",
        ):
            await second.rollback(dict(failed))
        release.set()
        owner_result = await owner_task
        return owner_result, calls

    owner_result, calls = asyncio.run(_run())

    assert owner_result is not None
    assert owner_result.state == "succeeded"
    assert calls == ["c-live-claim"]


def test_vidar_serializes_concurrent_rollback_delivery() -> None:
    from fdai.shared.providers.testing.state_store import InMemoryStateStore

    calls: list[str] = []

    async def rollback_executor(action_run):
        calls.append(action_run["correlation_id"])
        await asyncio.sleep(0)
        return "rollback:c-concurrent"

    bus = InMemoryBus(registry=load_pantheon())
    vidar = Vidar(
        bus=bus,
        executors={"state_forward_only": rollback_executor},
        state_store=InMemoryStateStore(),
    )
    failed = {
        "correlation_id": "c-concurrent",
        "action_type": "ops.restart-service",
        "resource_id": "vm-3",
        "state": "failed",
    }

    async def _deliver_twice():
        return await asyncio.gather(
            vidar.rollback(dict(failed)),
            vidar.rollback(dict(failed)),
        )

    first, second = asyncio.run(_deliver_twice())

    assert first is not None
    assert second is None
    assert calls == ["c-concurrent"]
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
    # A distinct action is not acknowledged or discarded while the resource is held.
    with pytest.raises(RuntimeError, match="active ActionRun"):
        asyncio.run(
            thor.dispatch_verdict(
                {
                    "correlation_id": "c2",
                    "action_type": "ops.restart-service",
                    "risk_verdict": "auto",
                    "resource_id": "vm-lock",
                }
            )
        )


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
    idempotency_key: str = "action-run:hil-pending",
    state_store=None,  # noqa: ANN001
) -> Var:
    reg = load_pantheon()
    var = Var(bus=InMemoryBus(registry=reg), state_store=state_store)
    payload: dict[str, object] = {
        "correlation_id": correlation,
        "action_type": "remediate.delete-storage",
        "state": "hil_pending",
        "quorum_required": quorum,
        "idempotency_key": idempotency_key,
    }
    if initiator is not None:
        payload["initiator_principal"] = initiator
    asyncio.run(var.on_typed_message("object.action-run", payload))
    return var


def test_var_preserves_action_run_idempotency_key_on_approval() -> None:
    var = _var_with_pending(
        "c-idempotency",
        idempotency_key="c-idempotency:hil_pending",
    )

    approval = asyncio.run(
        var.decide(
            "c-idempotency",
            approver="reviewer@example.com",
            decision="approve",
        )
    )

    assert approval is not None
    assert approval["idempotency_key"] == "c-idempotency:hil_pending"
    assert var.bus is not None
    published = var.bus.messages_on("object.approval")  # type: ignore[union-attr]
    assert published[0].payload["idempotency_key"] == "c-idempotency:hil_pending"


def test_var_retries_stored_final_approval_after_publication_failure() -> None:
    from fdai.shared.providers.testing.state_store import InMemoryStateStore

    class _FailOnceApprovalBus:
        def __init__(self) -> None:
            self.calls = 0
            self.payloads: list[dict[str, object]] = []

        def subscribe(self, topic, agent_name, handler):  # noqa: ANN001, ANN201
            del topic, agent_name, handler

        async def publish(self, principal, topic, payload):  # noqa: ANN001, ANN201
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("approval bus unavailable")
            assert principal == "Var"
            assert topic == "object.approval"
            self.payloads.append(dict(payload))

    store = InMemoryStateStore()
    bus = _FailOnceApprovalBus()
    var = Var(bus=bus, state_store=store)
    asyncio.run(
        var.on_typed_message(
            "object.action-run",
            {
                "correlation_id": "c-approval-retry",
                "idempotency_key": "c-approval-retry:hil_pending",
                "action_type": "ops.restart-service",
                "state": "hil_pending",
            },
        )
    )

    with pytest.raises(RuntimeError, match="approval bus unavailable"):
        asyncio.run(
            var.decide(
                "c-approval-retry",
                approver="reviewer@example.com",
                decision="approve",
            )
        )
    approval = asyncio.run(
        var.decide(
            "c-approval-retry",
            approver="reviewer@example.com",
            decision="approve",
        )
    )

    assert approval is not None
    assert approval["approvers"] == ["reviewer@example.com"]
    assert bus.calls == 2
    assert len(bus.payloads) == 1
    assert var.pending_tickets() == ()


def test_var_replays_final_approval_after_restart() -> None:
    from fdai.shared.providers.testing.state_store import InMemoryStateStore

    store = InMemoryStateStore()
    first = _var_with_pending(
        "c-approval-restart",
        idempotency_key="c-approval-restart:hil_pending",
        state_store=store,
    )
    first.bus = None
    finalized = asyncio.run(
        first.decide(
            "c-approval-restart",
            approver="reviewer@example.com",
            decision="approve",
        )
    )
    assert finalized is not None

    bus = InMemoryBus(registry=load_pantheon())
    restarted = Var(bus=bus, state_store=store)
    assert asyncio.run(restarted.recover_approvals()) == (0, 1)
    assert len(bus.messages_on("object.approval")) == 1


def test_var_rejects_durable_correlation_reuse() -> None:
    from fdai.shared.providers.testing.state_store import InMemoryStateStore

    store = InMemoryStateStore()
    correlation = "c-var-reused-correlation"
    first = Var(state_store=store)
    asyncio.run(
        first.on_typed_message(
            "object.action-run",
            {
                "correlation_id": correlation,
                "action_type": "ops.restart-service",
                "resource_id": "vm-old",
                "state": "hil_pending",
            },
        )
    )
    old_approval = asyncio.run(
        first.decide(
            correlation,
            approver="reviewer-a@example.com",
            decision="approve",
        )
    )
    assert old_approval is not None

    restarted = Var(state_store=store)
    asyncio.run(
        restarted.on_typed_message(
            "object.action-run",
            {
                "correlation_id": correlation,
                "action_type": "remediate.delete-storage",
                "resource_id": "storage-current",
                "state": "hil_pending",
            },
        )
    )
    assert restarted.pending_tickets() == ()
    assert (
        asyncio.run(
            restarted.decide(
                correlation,
                approver="reviewer-b@example.com",
                decision="approve",
            )
        )
        is None
    )
    assert restarted.behavior_snapshot()["ticket_identity_conflict"] == 1


def test_shadow_hil_partial_quorum_survives_restart() -> None:
    from fdai.agents._framework.provider_adapters import StateStoreActionRunStore
    from fdai.shared.providers.testing.state_store import InMemoryStateStore

    store = InMemoryStateStore()
    first_bus = InMemoryBus(registry=load_pantheon())
    first_thor = Thor(bus=first_bus, state_store=StateStoreActionRunStore(store))
    first_var = Var(bus=first_bus, state_store=store)
    first_bus.subscribe("object.action-run", "Var", first_var.on_typed_message)
    asyncio.run(
        first_thor.dispatch_verdict(
            {
                "correlation_id": "c-shadow-quorum-restart",
                "idempotency_key": "shadow-quorum-generation",
                "action_type": "remediate.delete-storage",
                "risk_verdict": "hil",
                "resolved_autonomy_ceiling": "shadow_only",
                "resource_id": "storage-shadow",
                "quorum_required": 2,
            }
        )
    )
    assert (
        asyncio.run(
            first_var.decide(
                "c-shadow-quorum-restart",
                approver="reviewer-a@example.com",
                decision="approve",
            )
        )
        is None
    )

    restarted_bus = InMemoryBus(registry=load_pantheon())
    restarted_thor = Thor(
        bus=restarted_bus,
        state_store=StateStoreActionRunStore(store),
    )
    restarted_var = Var(bus=restarted_bus, state_store=store)
    restarted_bus.subscribe("object.action-run", "Var", restarted_var.on_typed_message)
    restarted_bus.subscribe("object.approval", "Thor", restarted_thor.on_typed_message)

    assert asyncio.run(restarted_thor.rehydrate()) == 1
    assert asyncio.run(restarted_var.recover_approvals()) == (0, 0)
    approval = asyncio.run(
        restarted_var.decide(
            "c-shadow-quorum-restart",
            approver="reviewer-b@example.com",
            decision="approve",
        )
    )

    assert approval is not None
    assert restarted_thor.action_runs["c-shadow-quorum-restart"].state is ActionRunState.SUCCEEDED


def test_var_recovers_unpublished_final_without_repeated_human_decision() -> None:
    from fdai.shared.providers.testing.state_store import InMemoryStateStore

    store = InMemoryStateStore()
    first = _var_with_pending(
        "c-approval-outbox",
        state_store=store,
    )
    first.bus = None
    finalized = asyncio.run(
        first.decide(
            "c-approval-outbox",
            approver="reviewer@example.com",
            decision="approve",
        )
    )
    assert finalized is not None

    bus = InMemoryBus(registry=load_pantheon())
    restarted = Var(bus=bus, state_store=store)
    recovered = asyncio.run(restarted.recover_approvals())

    assert recovered == (0, 1)
    published = bus.messages_on("object.approval")
    assert len(published) == 1
    assert published[0].payload["correlation_id"] == "c-approval-outbox"
    assert published[0].payload["approvers"] == ["reviewer@example.com"]


def test_var_recovers_terminal_decision_before_final_checkpoint() -> None:
    from fdai.shared.providers.testing.state_store import InMemoryStateStore

    class _FailFirstFinalCheckpoint(InMemoryStateStore):
        def __init__(self) -> None:
            super().__init__()
            self.failed = False

        async def write_state_if_absent(self, key, value):  # noqa: ANN001, ANN201
            if key.endswith("/final") and not self.failed:
                self.failed = True
                raise RuntimeError("final checkpoint interrupted")
            return await super().write_state_if_absent(key, value)

    store = _FailFirstFinalCheckpoint()
    first = _var_with_pending(
        "c-decision-finalization",
        state_store=store,
    )
    first.bus = None
    with pytest.raises(RuntimeError, match="final checkpoint interrupted"):
        asyncio.run(
            first.decide(
                "c-decision-finalization",
                approver="reviewer@example.com",
                decision="approve",
            )
        )

    bus = InMemoryBus(registry=load_pantheon())
    restarted = Var(bus=bus, state_store=store)
    recovered = asyncio.run(restarted.recover_approvals())

    assert recovered == (1, 1)
    published = bus.messages_on("object.approval")
    assert len(published) == 1
    assert published[0].payload["correlation_id"] == "c-decision-finalization"
    assert published[0].payload["approvers"] == ["reviewer@example.com"]


def test_var_combines_pre_final_quorum_across_restart() -> None:
    from fdai.shared.providers.testing.state_store import InMemoryStateStore

    store = InMemoryStateStore()
    first = _var_with_pending(
        "c-quorum-restart",
        quorum=2,
        idempotency_key="c-quorum-restart:hil_pending",
        state_store=store,
    )
    first.bus = None

    first_vote = asyncio.run(
        first.decide(
            "c-quorum-restart",
            approver="alice@example.com",
            decision="approve",
        )
    )
    assert first_vote is None

    restarted = _var_with_pending(
        "c-quorum-restart",
        quorum=2,
        idempotency_key="c-quorum-restart:hil_pending",
        state_store=store,
    )
    restarted.bus = None
    final = asyncio.run(
        restarted.decide(
            "c-quorum-restart",
            approver="bob@example.com",
            decision="approve",
        )
    )

    assert final is not None
    assert final["state"] == "approved"
    assert final["approvers"] == ["alice@example.com", "bob@example.com"]


def test_var_combines_quorum_across_replicas() -> None:
    from fdai.shared.providers.testing.state_store import InMemoryStateStore

    async def _decide() -> tuple[dict[str, object] | None, dict[str, object] | None]:
        store = InMemoryStateStore()
        first = Var(state_store=store)
        second = Var(state_store=store)
        ticket = {
            "correlation_id": "c-quorum-replicas",
            "action_type": "remediate.delete-storage",
            "state": "hil_pending",
            "quorum_required": 2,
            "idempotency_key": "action-run:hil-pending",
        }
        await asyncio.gather(
            first.on_typed_message("object.action-run", dict(ticket)),
            second.on_typed_message("object.action-run", dict(ticket)),
        )
        first.bus = None
        second.bus = None
        return await asyncio.gather(
            first.decide(
                "c-quorum-replicas",
                approver="alice@example.com",
                decision="approve",
            ),
            second.decide(
                "c-quorum-replicas",
                approver="bob@example.com",
                decision="approve",
            ),
        )

    first_result, second_result = asyncio.run(_decide())

    final = first_result or second_result
    assert final is not None
    assert final["state"] == "approved"
    assert final["approvers"] == ["alice@example.com", "bob@example.com"]


def test_var_rejects_durable_principal_decision_replacement() -> None:
    from fdai.shared.providers.testing.state_store import InMemoryStateStore

    store = InMemoryStateStore()
    first = _var_with_pending(
        "c-vote-collision",
        quorum=2,
        state_store=store,
    )
    first.bus = None
    assert (
        asyncio.run(
            first.decide(
                "c-vote-collision",
                approver="alice@example.com",
                decision="approve",
            )
        )
        is None
    )
    restarted = _var_with_pending(
        "c-vote-collision",
        quorum=2,
        state_store=store,
    )
    restarted.bus = None

    with pytest.raises(ValueError, match="cannot replace an existing decision"):
        asyncio.run(
            restarted.decide(
                "c-vote-collision",
                approver="alice@example.com",
                decision="reject",
            )
        )


def test_var_serializes_concurrent_final_approvals() -> None:
    var = _var_with_pending(
        "c-approval-concurrent",
        idempotency_key="c-approval-concurrent:hil_pending",
    )

    async def _decide_concurrently() -> tuple[dict[str, object] | None, dict[str, object] | None]:
        first, second = await asyncio.gather(
            var.decide(
                "c-approval-concurrent",
                approver="first@example.com",
                decision="approve",
            ),
            var.decide(
                "c-approval-concurrent",
                approver="second@example.com",
                decision="approve",
            ),
        )
        return first, second

    first, second = asyncio.run(_decide_concurrently())

    finalized = first or second
    assert finalized is not None
    assert (first is None) is not (second is None)
    assert finalized["approvers"] == ["first@example.com"]
    assert var.bus is not None
    assert len(var.bus.messages_on("object.approval")) == 1  # type: ignore[union-attr]


@pytest.mark.parametrize("idempotency_key", [" ", 7])
def test_var_rejects_invalid_action_run_idempotency_key(idempotency_key: object) -> None:
    var = Var(bus=None)

    asyncio.run(
        var.on_typed_message(
            "object.action-run",
            {
                "correlation_id": "c-invalid-idempotency",
                "action_type": "ops.restart-service",
                "state": "hil_pending",
                "idempotency_key": idempotency_key,
            },
        )
    )

    assert var.pending_tickets() == ()
    assert var.behavior_snapshot()["ticket_invalid_idempotency_key"] == 1


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


def test_var_ingest_rejects_a_reused_correlation_with_new_identity() -> None:
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
    # A different ActionRun cannot reuse an already claimed correlation.
    asyncio.run(
        var.on_typed_message(
            "object.action-run",
            {"correlation_id": "c-dup", "action_type": "other", "state": "hil_pending"},
        )
    )
    tickets = {t.correlation_id for t in var.pending_tickets()}
    assert tickets == {"c-dup"}
    assert var.pending_tickets()[0].action_type == "remediate.delete-storage"
    assert var.behavior_snapshot()["ticket_identity_conflict"] == 1


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

    # Fire 100 restart_needed events - each matches Forseti's auto rule.
    for i in range(100):
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
    assert len(verdicts) == 100
    # Every verdict must produce (at least) verdicted/executing/succeeded states.
    assert len(action_runs) >= 300
    # Zero policy escapes: no state == 'failed' or 'deny_dropped'
    escaped = [a for a in action_runs if a.payload["state"] in ("failed", "deny_dropped")]
    assert escaped == []
    # Saga captured every terminal state
    saga.audit_chain.verify()
    assert len(saga.audit_chain.entries) >= len(verdicts) + len(action_runs)


def test_heimdall_does_not_merge_independent_correlation_episodes() -> None:
    reg = load_pantheon()
    bus = InMemoryBus(registry=reg)
    candidates: list[dict[str, object]] = []

    async def capture(candidate: dict[str, object]) -> bool:
        candidates.append(candidate)
        return True

    heimdall = Heimdall(bus=bus, rate_threshold=2, incident_candidate_hook=capture)
    for index in range(2):
        asyncio.run(
            heimdall.on_typed_message(
                "object.event",
                {
                    "resource_id": "api-example",
                    "event_type": "availability.probe_failed",
                    "incident_correlation": "correlate",
                    "correlation_id": f"episode-{index}",
                    "idempotency_key": f"failure-{index}",
                    "severity": "high",
                },
            )
        )

    assert bus.messages_on("object.anomaly") == []
    assert candidates == []


def test_heimdall_uses_worst_severity_in_burst_window() -> None:
    reg = load_pantheon()
    bus = InMemoryBus(registry=reg)
    candidates: list[dict[str, object]] = []

    async def capture(candidate: dict[str, object]) -> bool:
        candidates.append(candidate)
        return True

    heimdall = Heimdall(bus=bus, rate_threshold=2, incident_candidate_hook=capture)
    for index, severity in enumerate(("critical", "info")):
        asyncio.run(
            heimdall.on_typed_message(
                "object.event",
                {
                    "resource_id": "api-example",
                    "event_type": "availability.probe_failed",
                    "incident_correlation": "correlate",
                    "correlation_id": "episode-1",
                    "idempotency_key": f"failure-{index}",
                    "severity": severity,
                },
            )
        )

    anomaly = bus.messages_on("object.anomaly")[0].payload
    assert anomaly["severity"] == "critical"
    assert str(anomaly["idempotency_key"]).startswith("anomaly:")
    assert candidates[0]["severity"] == "critical"


def test_heimdall_preserves_all_burst_evidence_keys() -> None:
    candidates: list[dict[str, object]] = []

    async def capture(candidate: dict[str, object]) -> bool:
        candidates.append(candidate)
        return True

    heimdall = Heimdall(rate_threshold=2, incident_candidate_hook=capture)
    for index in range(2):
        asyncio.run(
            heimdall.on_typed_message(
                "object.event",
                {
                    "resource_id": "api-example",
                    "event_type": "availability.probe_failed",
                    "incident_correlation": "correlate",
                    "correlation_id": "episode-1",
                    "idempotency_key": f"failure-{index}",
                    "severity": "high",
                },
            )
        )

    assert candidates[0]["evidence_keys"] == ("failure-0", "failure-1")


def test_heimdall_does_not_count_duplicate_event_evidence_toward_threshold() -> None:
    reg = load_pantheon()
    bus = InMemoryBus(registry=reg)
    candidates: list[dict[str, object]] = []

    async def capture(candidate: dict[str, object]) -> bool:
        candidates.append(candidate)
        return True

    heimdall = Heimdall(bus=bus, rate_threshold=2, incident_candidate_hook=capture)
    repeated = {
        "resource_id": "api-example",
        "event_type": "availability.probe_failed",
        "incident_correlation": "correlate",
        "correlation_id": "episode-1",
        "idempotency_key": "failure-1",
        "severity": "high",
    }

    asyncio.run(heimdall.on_typed_message("object.event", repeated))
    asyncio.run(heimdall.on_typed_message("object.event", repeated))

    assert bus.messages_on("object.anomaly") == []
    assert candidates == []
    assert heimdall.behavior_snapshot()["repeated_event_duplicate"] == 1

    asyncio.run(
        heimdall.on_typed_message(
            "object.event",
            {**repeated, "idempotency_key": "failure-2"},
        )
    )

    assert len(bus.messages_on("object.anomaly")) == 1
    assert candidates[0]["evidence_keys"] == ("failure-1", "failure-2")


def test_heimdall_uses_one_candidate_per_bounded_episode() -> None:
    reg = load_pantheon()
    bus = InMemoryBus(registry=reg)
    candidates: list[dict[str, object]] = []
    clock = {"now": 0.0}

    async def capture(candidate: dict[str, object]) -> bool:
        candidates.append(candidate)
        return True

    heimdall = Heimdall(
        bus=bus,
        rate_threshold=2,
        rate_window=60,
        incident_candidate_hook=capture,
        clock=lambda: clock["now"],
    )

    def send(index: int, *, severity: str = "high") -> None:
        asyncio.run(
            heimdall.on_typed_message(
                "object.event",
                {
                    "resource_id": "api-example",
                    "event_type": "availability.probe_failed",
                    "incident_correlation": "correlate",
                    "correlation_id": "stable-signal",
                    "idempotency_key": f"failure-{index}",
                    "severity": severity,
                },
            )
        )

    send(0)
    clock["now"] = 1.0
    send(1)
    clock["now"] = 2.0
    send(2)

    assert len(candidates) == 1

    clock["now"] = 63.0
    send(3)
    clock["now"] = 64.0
    send(4)

    assert len(candidates) == 2
    assert candidates[0]["correlation_id"] == candidates[1]["correlation_id"]
    assert candidates[0]["incident_episode_id"] != candidates[1]["incident_episode_id"]


def test_heimdall_uses_event_time_for_replayed_repeat_windows() -> None:
    reg = load_pantheon()
    bus = InMemoryBus(registry=reg)
    candidates: list[dict[str, object]] = []
    observed = datetime(2026, 9, 14, 2, 0, tzinfo=UTC)

    async def capture(candidate: dict[str, object]) -> bool:
        candidates.append(candidate)
        return True

    heimdall = Heimdall(
        bus=bus,
        rate_threshold=2,
        rate_window=300,
        incident_candidate_hook=capture,
        clock=lambda: 0.0,
    )

    def send(index: int, occurred_at: datetime) -> None:
        asyncio.run(
            heimdall.on_typed_message(
                "object.event",
                {
                    "resource_id": "api-example",
                    "event_type": "availability.probe_failed",
                    "incident_correlation": "correlate",
                    "correlation_id": "stable-signal",
                    "idempotency_key": f"failure-{index}",
                    "severity": "high",
                    "occurred_at": occurred_at.isoformat(),
                },
            )
        )

    send(0, observed)
    send(1, observed + timedelta(minutes=10))

    assert candidates == []

    send(2, observed + timedelta(minutes=10, seconds=1))

    assert len(candidates) == 1
    assert candidates[0]["evidence_keys"] == ("failure-1", "failure-2")


def test_heimdall_reuses_episode_identity_for_more_severe_evidence() -> None:
    candidates: list[dict[str, object]] = []
    clock = {"now": 0.0}

    async def capture(candidate: dict[str, object]) -> bool:
        candidates.append(candidate)
        return True

    heimdall = Heimdall(
        rate_threshold=2,
        rate_window=60,
        incident_candidate_hook=capture,
        clock=lambda: clock["now"],
    )
    for index, severity in enumerate(("medium", "medium", "critical")):
        clock["now"] = float(index)
        asyncio.run(
            heimdall.on_typed_message(
                "object.event",
                {
                    "resource_id": "api-example",
                    "event_type": "availability.probe_failed",
                    "incident_correlation": "correlate",
                    "correlation_id": "stable-signal",
                    "idempotency_key": f"failure-{index}",
                    "severity": severity,
                },
            )
        )

    assert [candidate["severity"] for candidate in candidates] == ["medium", "critical"]
    assert candidates[0]["incident_episode_id"] == candidates[1]["incident_episode_id"]


def test_heimdall_accumulates_interleaved_episodes_independently() -> None:
    reg = load_pantheon()
    bus = InMemoryBus(registry=reg)
    candidates: list[dict[str, object]] = []

    async def capture(candidate: dict[str, object]) -> bool:
        candidates.append(candidate)
        return True

    heimdall = Heimdall(bus=bus, rate_threshold=2, incident_candidate_hook=capture)
    for index, correlation_id in enumerate(("episode-a", "episode-b", "episode-a", "episode-b")):
        asyncio.run(
            heimdall.on_typed_message(
                "object.event",
                {
                    "resource_id": "api-example",
                    "event_type": "availability.probe_failed",
                    "incident_correlation": "correlate",
                    "correlation_id": correlation_id,
                    "idempotency_key": f"failure-{index}",
                    "severity": "high",
                },
            )
        )

    assert [message.payload["correlation_id"] for message in bus.messages_on("object.anomaly")] == [
        "episode-a",
        "episode-b",
    ]
    assert [candidate["correlation_id"] for candidate in candidates] == [
        "episode-a",
        "episode-b",
    ]


def test_heimdall_retries_candidate_after_transient_hook_failure() -> None:
    candidates: list[dict[str, object]] = []
    bus = InMemoryBus(registry=load_pantheon())

    async def fail_once(candidate: dict[str, object]) -> bool:
        candidates.append(candidate)
        if len(candidates) == 1:
            raise RuntimeError("transient lifecycle failure")
        return True

    heimdall = Heimdall(
        bus=bus,
        rate_threshold=2,
        incident_candidate_hook=fail_once,
    )
    for index in (0, 1, 1):
        asyncio.run(
            heimdall.on_typed_message(
                "object.event",
                {
                    "resource_id": "api-example",
                    "event_type": "availability.probe_failed",
                    "incident_correlation": "correlate",
                    "correlation_id": "episode-1",
                    "idempotency_key": f"failure-{index}",
                    "severity": "high",
                },
            )
        )

    assert len(candidates) == 2
    assert candidates[0]["evidence_keys"] == candidates[1]["evidence_keys"]
    anomalies = bus.messages_on("object.anomaly")
    assert anomalies[0].payload["idempotency_key"] == anomalies[1].payload["idempotency_key"]
    assert heimdall.behavior_snapshot()["incident_candidate_failed"] == 1
    assert heimdall.behavior_snapshot()["incident_candidate"] == 1
    assert heimdall.behavior_snapshot()["repeated_event_duplicate"] == 1


def test_heimdall_records_policy_held_candidate_separately() -> None:
    async def hold(_candidate: dict[str, object]) -> bool:
        return False

    heimdall = Heimdall(rate_threshold=2, incident_candidate_hook=hold)
    for index in range(2):
        asyncio.run(
            heimdall.on_typed_message(
                "object.event",
                {
                    "resource_id": "api-example",
                    "event_type": "availability.probe_failed",
                    "incident_correlation": "correlate",
                    "correlation_id": "episode-held",
                    "idempotency_key": f"failure-{index}",
                    "severity": "medium",
                },
            )
        )

    snapshot = heimdall.behavior_snapshot()
    assert snapshot["incident_candidate_held"] == 1
    assert snapshot.get("incident_candidate", 0) == 0
