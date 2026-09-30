from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from fdai.agents._framework.bus import InMemoryBus
from fdai.agents._framework.loki_reservations import LokiReservationJournal
from fdai.agents._framework.registry import load_pantheon
from fdai.agents._framework.runtime_subscriptions import build_ingress_handler
from fdai.agents.forseti import Forseti
from fdai.agents.freyr import Freyr
from fdai.agents.heimdall import Heimdall
from fdai.agents.huginn import Huginn, HuginnIngressRejected
from fdai.agents.loki import Loki
from fdai.agents.njord import Njord
from fdai.core.capacity import CapacityGraduationController
from fdai.rule_catalog.schema.capacity_graduation_policy import load_capacity_graduation_policy
from fdai.shared.providers.cost_governance import CostAnalysisSample, CostAnomalyAdvisory
from fdai.shared.providers.testing.state_store import InMemoryStateStore

NOW = datetime(2028, 1, 2, tzinfo=UTC)
CHAOS_ACTION = "tool.run-chaos-experiment"
RELEASE_DIGEST = "sha256:" + "3" * 64


class CountingCostProvider:
    def __init__(self) -> None:
        self.calls = 0

    async def analyze_cost_sample(
        self,
        sample: CostAnalysisSample,
    ) -> CostAnomalyAdvisory | None:
        self.calls += 1
        return CostAnomalyAdvisory(
            scope_id=sample.scope_id,
            resource_id=sample.resource_id,
            amount_usd=sample.amount_usd,
            baseline_usd=Decimal("100"),
            ratio=sample.amount_usd / Decimal("100"),
            impact=Decimal("1"),
            recommendation="scale_down",
            correlation_id=sample.correlation_id,
            observed_at=sample.observed_at,
        )

    def estimate_cost_effect(self, action_type: str) -> None:
        return None


def _bus() -> InMemoryBus:
    return InMemoryBus(registry=load_pantheon())


def _controller() -> CapacityGraduationController:
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[4]
    return CapacityGraduationController(
        load_capacity_graduation_policy(repo_root / "rule-catalog/capacity-graduation-policy.yaml")
    )


def _raw_event(**overrides: Any) -> dict[str, Any]:
    event = {
        "idempotency_key": "raw-event-key",
        "event_id": "event:raw",
        "correlation_id": "corr:raw",
        "event_type": "generic.event",
        "source": "synthetic.source",
        "resource_id": "resource:one",
        "occurred_at": NOW.isoformat(),
        "attributes": {"kind": "test"},
    }
    event.update(overrides)
    return event


def _cost_sample(**overrides: Any) -> dict[str, Any]:
    event = {
        "producer_principal": "Huginn",
        "correlation_id": "cost:corr",
        "idempotency_key": "cost:key",
        "event_id": "event:cost",
        "event_type": "specialist.cost_sample",
        "occurred_at": NOW.isoformat(),
        "ingested_at": (NOW + timedelta(seconds=1)).isoformat(),
        "resource_id": "resource:cost",
        "attributes": {
            "scope": "scope:cost",
            "resource_id": "resource:cost",
            "amount_usd": 200.0,
            "source_authority": "test-cost-source",
            "completeness": 1.0,
            "ontology_release_digest": RELEASE_DIGEST,
        },
    }
    event.update(overrides)
    return event


def _capacity_sample(**overrides: Any) -> dict[str, Any]:
    event = {
        "producer_principal": "Huginn",
        "correlation_id": "capacity:corr",
        "idempotency_key": "capacity:key",
        "event_id": "event:capacity",
        "event_type": "specialist.capacity_sample",
        "occurred_at": NOW.isoformat(),
        "ingested_at": (NOW + timedelta(seconds=1)).isoformat(),
        "resource_id": "resource:capacity",
        "attributes": {"utilization": 0.9},
    }
    event.update(overrides)
    return event


def _graduation_event(**overrides: Any) -> dict[str, Any]:
    event = {
        "producer_principal": "Huginn",
        "correlation_id": "graduation:corr",
        "idempotency_key": "graduation:key",
        "event_id": "event:graduation",
        "event_type": "specialist.capacity_graduation_evidence",
        "occurred_at": NOW.isoformat(),
        "ingested_at": NOW.isoformat(),
        "resource_id": "resource:capacity",
        "attributes": {
            "transition": "dedicated_vector_store",
            "target_ref": "resource:capacity",
            "source_authority_ref": "measurement:capacity",
            "measurement_ref": "measurement:capacity:1",
            "observed_utilization": 0.9,
            "forecast_utilization": 0.9,
            "forecast_horizon_minutes": 30,
            "cost_evidence_ref": "cost:evidence",
            "complete": True,
            "synthetic": False,
            "projected_cost_ratio": 1.0,
            "capacity_ratio": 0.8,
        },
    }
    event.update(overrides)
    return event


def _chaos_schedule(**overrides: Any) -> dict[str, Any]:
    attributes = {
        "experiment_id": "experiment:one",
        "action_type": CHAOS_ACTION,
        "targets": ["target:one"],
    }
    attributes.update(overrides.pop("attributes", {}))
    event = {
        "producer_principal": "Huginn",
        "correlation_id": "chaos:corr",
        "idempotency_key": "chaos:key",
        "event_id": "event:chaos",
        "event_type": "specialist.chaos_schedule",
        "occurred_at": NOW.isoformat(),
        "ingested_at": (NOW + timedelta(seconds=1)).isoformat(),
        "resource_id": "target:one",
        "attributes": attributes,
    }
    event.update(overrides)
    return event


def _chaos_proposal(**overrides: Any) -> dict[str, Any]:
    proposal = {
        "producer_principal": "Loki",
        "correlation_id": "chaos:corr",
        "idempotency_key": "chaos:key",
        "experiment_id": "experiment:one",
        "action_type": CHAOS_ACTION,
        "targets": ["target:one"],
        "causal_hypothesis_ref": "causal:one",
        "refutation_query_ref": "query:one",
        "impact_envelope_id": "impact:one",
        "recovery_plan_id": "recovery:one",
        "dry_run_receipt": "dry-run:one",
    }
    proposal.update(overrides)
    return proposal


async def test_huginn_keeps_validated_raw_operator_authority_fields_and_params() -> None:
    payload = await Huginn(clock=lambda: NOW).ingest(
        _raw_event(
            event_type="operator_request",
            source="operator-console",
            initiator_principal="operator@example.com",
            action_type="ops.restart-service",
            operator_initiated=True,
            human_approval_required=False,
            operator_request_channel="forged-client-value",
            resolved_autonomy_ceiling="enforce_auto",
            risk_verdict="auto",
            quorum_required=0,
            params={"nested": ["safe-value"]},
        )
    )

    assert payload is not None
    assert payload["initiator_principal"] == "operator@example.com"
    assert payload["action_type"] == "ops.restart-service"
    assert payload["operator_initiated"] is True
    assert payload["human_approval_required"] is False
    assert payload["operator_request_channel"] == "ingress"
    assert payload["params"] == {"nested": ["safe-value"]}
    assert "resolved_autonomy_ceiling" not in payload
    assert "risk_verdict" not in payload
    assert "quorum_required" not in payload


async def test_raw_ingress_keeps_operator_confirmation_shape_and_stamps_ingress_channel() -> None:
    bus = _bus()
    huginn = Huginn(bus=bus, clock=lambda: NOW)
    handler = build_ingress_handler(agent=huginn, on_unkeyed=lambda _exc: None)

    await handler(
        "raw",
        _raw_event(
            idempotency_key="operator-confirmation-1",
            event_id="event:operator-confirmation-1",
            correlation_id="session:operator-confirmation-1",
            event_type="operator_request",
            source="operator-console",
            initiator_principal="operator-one",
            action_type="ops.restart-service",
            operator_initiated=True,
            params={"target_resource_ref": "resource:service/api"},
            ontology_intent={"intent_id": "intent:operator-confirmation-1"},
        ),
    )

    (published,) = bus.messages_on("object.event")
    assert published.payload["initiator_principal"] == "operator-one"
    assert published.payload["action_type"] == "ops.restart-service"
    assert published.payload["params"] == {"target_resource_ref": "resource:service/api"}
    assert published.payload["operator_request_channel"] == "ingress"


async def test_raw_ingress_keeps_workflow_step_shape_and_stamps_ingress_channel() -> None:
    bus = _bus()
    huginn = Huginn(bus=bus, clock=lambda: NOW)
    handler = build_ingress_handler(agent=huginn, on_unkeyed=lambda _exc: None)

    await handler(
        "raw",
        _raw_event(
            idempotency_key="process-1:step:restart:attempt:1",
            event_id="event:workflow-step-1",
            correlation_id="workflow:corr",
            event_type="operator_request",
            source="workflow-dispatch",
            initiator_principal="fdai.workflow",
            action_type="ops.restart-service",
            operator_initiated=True,
            params={"target_resource_ref": "resource:service/api"},
            workflow_action={
                "process_id": "process-1",
                "step_id": "restart",
                "proposal_ref": "process-1:step:restart:attempt:1",
                "attempt": 1,
            },
        ),
    )

    (published,) = bus.messages_on("object.event")
    assert published.payload["initiator_principal"] == "fdai.workflow"
    assert published.payload["action_type"] == "ops.restart-service"
    assert published.payload["operator_request_channel"] == "ingress"
    assert published.payload["workflow_action"]["attempt"] == 1


async def test_unknown_raw_operator_request_reaches_forseti_and_is_rbac_denied() -> None:
    bus = _bus()
    huginn = Huginn(bus=bus, clock=lambda: NOW)
    forseti = Forseti(
        bus=bus,
        rbac={"operator@example.com": frozenset({"ops.restart-service"})},
    )
    bus.subscribe("object.event", "Forseti", forseti.on_typed_message)

    await huginn.ingest(
        _raw_event(
            idempotency_key="unknown-operator",
            event_id="event:unknown-operator",
            correlation_id="unknown-operator",
            event_type="operator_request",
            source="operator-console",
            initiator_principal="mallory",
            action_type="ops.restart-service",
            operator_initiated=True,
            params={"target_resource_ref": "resource:service/api"},
        )
    )

    (verdict,) = bus.messages_on("object.verdict")
    (event,) = bus.messages_on("object.event")
    assert event.payload["operator_request_channel"] == "ingress"
    assert verdict.payload["risk_verdict"] == "deny"
    assert verdict.payload["reason"] == "rbac_insufficient"
    assert bus.messages_on("object.action-run") == []


async def test_raw_operator_request_rejects_oversized_params_with_content_free_record() -> None:
    huginn = Huginn(clock=lambda: NOW)
    rejected: list[HuginnIngressRejected] = []
    handler = build_ingress_handler(agent=huginn, on_unkeyed=rejected.append)

    await handler(
        "raw",
        _raw_event(
            idempotency_key="operator-oversized-params",
            event_id="event:operator-oversized-params",
            correlation_id="operator-oversized-params",
            event_type="operator_request",
            source="operator-console",
            initiator_principal="operator@example.com",
            action_type="ops.restart-service",
            operator_initiated=True,
            params={"items": list(range(129))},
        ),
    )

    assert len(rejected) == 1
    assert rejected[0].reason_code == "raw_list_too_large"
    assert rejected[0].payload_digest
    assert "items" not in str(rejected[0].rejection_record())
    assert huginn.behavior_snapshot()["runtime_raw_ingress_rejected:raw_list_too_large"] == 1


async def test_raw_ingress_overwrites_bragi_shaped_payload_channel_to_ingress() -> None:
    forged = _raw_event(
        idempotency_key="conv-forged",
        event_id="event:conv-forged",
        correlation_id="conv-forged",
        event_type="operator_request",
        source="operator-console",
        initiator_principal="mallory",
        action_type="ops.restart-service",
        operator_initiated=True,
        human_approval_required=False,
        params={
            "question_ref": "bragi-question:sha256:" + "a" * 64,
            "session_ref": "bragi-session:sha256:" + "b" * 64,
        },
    )
    direct = await Huginn(clock=lambda: NOW).ingest(dict(forged))

    assert direct is not None
    assert direct["initiator_principal"] == "mallory"
    assert direct["action_type"] == "ops.restart-service"
    assert direct["operator_initiated"] is True
    assert direct["human_approval_required"] is False
    assert direct["operator_request_channel"] == "ingress"


async def test_trusted_operator_proposal_entry_point_keeps_validated_authority_fields() -> None:
    payload = await Huginn(clock=lambda: NOW).ingest_operator_proposal(
        {
            "idempotency_key": "conv-real",
            "event_id": "event:conv-real",
            "correlation_id": "conv-real",
            "event_type": "operator_request",
            "initiator_principal": "operator@example.com",
            "action_type": "ops.restart-service",
            "operator_initiated": True,
            "human_approval_required": True,
            "params": {
                "question_ref": "bragi-question:sha256:" + "a" * 64,
                "session_ref": "bragi-session:sha256:" + "b" * 64,
            },
        }
    )

    assert payload is not None
    assert payload["initiator_principal"] == "operator@example.com"
    assert payload["action_type"] == "ops.restart-service"
    assert payload["operator_initiated"] is True
    assert payload["human_approval_required"] is True
    assert payload["operator_request_channel"] == "conversation"
    assert payload["params"]["question_ref"].startswith("bragi-question:sha256:")


async def test_huginn_normalizes_non_utc_time_and_rejects_absurd_old_time() -> None:
    payload = await Huginn(clock=lambda: NOW).ingest(
        _raw_event(
            idempotency_key="non-utc-time",
            event_id="event:non-utc-time",
            occurred_at="2028-01-02T09:00:00+09:00",
        )
    )

    assert payload is not None
    assert payload["occurred_at"] == NOW.isoformat()

    with pytest.raises(HuginnIngressRejected) as exc:
        await Huginn(clock=lambda: NOW).ingest(
            _raw_event(
                idempotency_key="old-time",
                event_id="event:old-time",
                occurred_at="2001-01-01T00:00:00+00:00",
            )
        )
    assert exc.value.reason_code == "timestamp_too_old"


@pytest.mark.parametrize(
    "field, value, reason",
    [
        ("event_type", "generic\npoison", "invalid_string"),
        ("idempotency_key", {"not": "a-string"}, "invalid_idempotency_key"),
        ("attributes", {"items": list(range(129))}, "raw_list_too_large"),
    ],
)
async def test_huginn_rejects_unbounded_or_controlled_raw_fields(
    field: str,
    value: object,
    reason: str,
) -> None:
    with pytest.raises(HuginnIngressRejected) as exc:
        await Huginn(clock=lambda: NOW).ingest(_raw_event(**{field: value}))

    assert exc.value.reason_code == reason
    assert exc.value.payload_digest


async def test_huginn_change_actor_ignores_raw_initiator_principal() -> None:
    bus = _bus()
    payload = await Huginn(bus=bus, clock=lambda: NOW).ingest(
        _raw_event(
            idempotency_key="change-actor",
            event_id="event:change-actor",
            event_type="change.requested",
            source="azure.activity_log",
            initiator_principal="mallory",
        )
    )

    assert payload is not None
    (change,) = bus.messages_on("object.change")
    assert change.payload["actor_ref"] == "azure.activity_log"


async def test_runtime_ingress_rejection_records_content_free_reason() -> None:
    huginn = Huginn(clock=lambda: NOW)
    rejected: list[HuginnIngressRejected] = []
    handler = build_ingress_handler(agent=huginn, on_unkeyed=rejected.append)

    await handler("raw", _raw_event(event_type="bad\nidentity"))

    assert len(rejected) == 1
    record = rejected[0].rejection_record()
    assert record["reason_code"] == "invalid_string"
    assert record["payload_digest"]
    assert "bad\nidentity" not in str(record)
    assert huginn.behavior_snapshot()["runtime_raw_ingress_rejected:invalid_string"] == 1


@pytest.mark.parametrize(
    "payload",
    [
        _chaos_proposal(producer_principal="Mallory"),
        _chaos_proposal(targets=[f"target:{idx}" for idx in range(33)]),
        _chaos_proposal(action_type="ops.restart-service"),
    ],
)
async def test_heimdall_rejects_forged_or_unbounded_chaos_proposals(
    payload: dict[str, Any],
) -> None:
    bus = _bus()
    heimdall = Heimdall(bus=bus)

    await heimdall.on_typed_message("object.chaos-experiment", payload)

    assert bus.messages_on("object.anomaly") == []


async def test_njord_rejects_forged_or_non_utc_cost_samples() -> None:
    bus = _bus()
    provider = CountingCostProvider()
    njord = Njord(
        bus=bus,
        advisory_provider=provider,
        package_enabled=True,
        allow_unbound_activation_reader=True,
    )

    forged = _cost_sample(producer_principal="Mallory")
    non_utc = _cost_sample(
        idempotency_key="cost:non-utc",
        event_id="event:cost:non-utc",
        occurred_at="2028-01-02T09:00:00+09:00",
    )
    await njord.on_typed_message("object.event", forged)
    await njord.on_typed_message("object.event", non_utc)

    assert provider.calls == 0
    assert bus.messages_on("object.cost-anomaly") == []
    behavior = njord.behavior_snapshot()
    assert behavior["cost_sample:invalid_producer"] == 1
    assert behavior["cost_sample:disabled"] == 1


async def test_freyr_rejects_forged_event_inputs_and_digests_unsafe_cost_evidence() -> None:
    bus = _bus()
    store = InMemoryStateStore()
    freyr = Freyr(
        bus=bus,
        state_store=store,
        graduation_controller=_controller(),
        clock=lambda: NOW,
    )

    await freyr.on_typed_message("object.event", _capacity_sample(producer_principal="Mallory"))
    await freyr.on_typed_message("object.event", _graduation_event(producer_principal="Mallory"))
    await freyr.on_typed_message(
        "object.cost-anomaly",
        {
            "producer_principal": "Njord",
            "correlation_id": "graduation:corr",
            "idempotency_key": "cost:unsafe",
            "resource_id": "resource:capacity",
            "evidence_ref": "https://example.com/private/evidence",
            "observed_at": NOW.isoformat(),
        },
    )

    assert bus.messages_on("object.capacity-forecast") == []
    assert bus.messages_on("object.capacity-graduation-recommendation") == []
    records = await store.read_states("pantheon/freyr/cost-evidence/", limit=10)
    assert records[0]["evidence_ref"].startswith("sha256:")
    assert freyr.behavior_snapshot()["capacity_sample:invalid_producer"] == 2


async def test_freyr_rejects_forged_cost_anomaly_owner() -> None:
    freyr = Freyr(clock=lambda: NOW)

    await freyr.on_typed_message(
        "object.cost-anomaly",
        {
            "producer_principal": "Mallory",
            "correlation_id": "graduation:corr",
            "idempotency_key": "cost:forged",
            "resource_id": "resource:capacity",
            "evidence_ref": "evidence:cost",
            "observed_at": NOW.isoformat(),
        },
    )

    assert freyr.behavior_snapshot()["capacity_graduation:invalid_cost_owner"] == 1


@pytest.mark.parametrize(
    "event",
    [
        _chaos_schedule(producer_principal="Mallory"),
        _chaos_schedule(attributes={"action_type": "ops.restart-service"}),
        _chaos_schedule(attributes={"targets": [f"target:{idx}" for idx in range(33)]}),
    ],
)
async def test_loki_rejects_forged_or_invalid_chaos_schedules(event: dict[str, Any]) -> None:
    bus = _bus()
    loki = Loki(bus=bus)

    await loki.on_typed_message("object.event", event)

    assert bus.messages_on("object.chaos-experiment") == []


async def test_loki_reservation_journal_rejects_unsafe_target_identifiers() -> None:
    journal = LokiReservationJournal(InMemoryStateStore(), blast_radius_cap=3)

    with pytest.raises(ValueError, match="targets are malformed"):
        await journal.reserve(
            experiment_id="experiment:bad",
            action_type=CHAOS_ACTION,
            targets=("target:one\npoison",),
            reserved_at=NOW.isoformat(),
        )

    with pytest.raises(ValueError, match="targets are malformed"):
        await journal.reserve(
            experiment_id="experiment:long",
            action_type=CHAOS_ACTION,
            targets=("x" * 513,),
            reserved_at=NOW.isoformat(),
        )
