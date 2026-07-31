from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID

from fdai.agents._framework.bus import InMemoryBus
from fdai.agents._framework.registry import load_pantheon
from fdai.agents.huginn import Huginn
from fdai.agents.mimir import Mimir
from fdai.agents.muninn import Muninn
from fdai.agents.norns import Norns
from fdai.core.case_history import (
    CaseHistoryMaterializer,
    OperationalCaseInput,
    OperationalOutcomeClass,
    OperationalReceiptType,
)
from fdai.core.case_history.testing import (
    InMemoryCaseHistoryArtifactStore,
    InMemoryCaseHistoryMetadataStore,
)
from fdai.shared.contracts.models import ResponseOutcome
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from tests.core.case_history.test_operational_case import _case_input, _receipt

_NOW = datetime(2026, 7, 31, tzinfo=UTC)


def _outcome(identifier: int, *, label: str, mode: str) -> ResponseOutcome:
    return ResponseOutcome.model_validate(
        {
            "schema_version": "1.0.0",
            "outcome_id": UUID(int=identifier),
            "idempotency_key": f"response-outcome:{identifier}",
            "action_id": UUID(int=100 + identifier),
            "event_id": UUID(int=200 + identifier),
            "action_type_id": "ops.scale-out",
            "target_digest": "a" * 64,
            "prediction_id": f"prediction-{identifier}",
            "metric": "availability",
            "expected_min": 0.99,
            "expected_max": 1.0,
            "observed_value": 0.995 if label == "verified" else 0.5,
            "predicted_at": _NOW,
            "observation_deadline": _NOW + timedelta(minutes=5),
            "observed_at": _NOW + timedelta(minutes=1),
            "label": label,
            "verification_status": "verified" if label == "verified" else "mismatch",
            "verification_reason": "test-evidence",
            "execution_mode": mode,
            "execution_outcome": "succeeded",
            "decision": "auto",
            "evidence_refs": [f"effect:prediction-{identifier}"],
            "recorded_at": _NOW + timedelta(minutes=2, seconds=identifier),
        }
    )


def _raw(outcome: ResponseOutcome) -> dict[str, Any]:
    return {
        "id": outcome.idempotency_key,
        "event_id": str(outcome.event_id),
        "correlation_id": str(outcome.action_id),
        "idempotency_key": outcome.idempotency_key,
        "source": "fdai.measurement",
        "event_type": "measurement.action_outcome.v1",
        "resource_id": outcome.target_digest,
        "attributes": outcome.model_dump(mode="json", exclude_none=True),
    }


def _operational_input(
    identifier: str,
    outcome_class: OperationalOutcomeClass,
    *,
    different_mechanism: bool = False,
) -> OperationalCaseInput:
    case_input = replace(
        _case_input(outcome_class=outcome_class),
        case_identity_digest=identifier * 64,
        correlation_digest=identifier * 64,
    )
    if outcome_class is OperationalOutcomeClass.SUCCESS:
        receipts = tuple(
            _receipt(
                OperationalReceiptType.AUDIT,
                "1",
                (("event_type", "action.completed"), ("decision", "auto"), ("mode", "enforce")),
            )
            if receipt.receipt_type is OperationalReceiptType.AUDIT
            else receipt
            for receipt in case_input.receipts
        )
        case_input = replace(case_input, receipts=receipts)
    if different_mechanism:
        case_input = replace(
            case_input,
            failure_fingerprint=replace(
                case_input.failure_fingerprint,
                failure_mechanism="readiness_probe_failure",
            ),
        )
    return case_input


def _operational_raw(name: str, case_input: OperationalCaseInput) -> dict[str, Any]:
    return {
        "id": f"operational-case:{name}",
        "event_id": f"operational-case:{name}",
        "correlation_id": case_input.correlation_digest,
        "idempotency_key": f"operational-case:{name}",
        "source": "fdai.case-history",
        "event_type": "case_history.operational_case.v1",
        "resource_id": case_input.failure_fingerprint.digest,
        "attributes": case_input.to_mapping(),
    }


def _learning_chain() -> tuple[InMemoryBus, Huginn, Muninn, Norns, Mimir, InMemoryStateStore]:
    bus = InMemoryBus(registry=load_pantheon(), isolate_handlers=False)
    durable = InMemoryStateStore()
    huginn = Huginn()
    muninn = Muninn(
        case_history=CaseHistoryMaterializer(
            metadata=InMemoryCaseHistoryMetadataStore(),
            artifacts=InMemoryCaseHistoryArtifactStore(),
        ),
        durable_state_store=durable,
    )
    norns = Norns()
    mimir = Mimir()
    for agent in (huginn, muninn, norns, mimir):
        agent.bind_bus(bus)
    bus.subscribe("object.event", "Muninn", muninn.on_typed_message)
    bus.subscribe("object.context-index", "Norns", norns.on_typed_message)
    bus.subscribe("object.rule-candidate", "Mimir", mimir.on_typed_message)
    return bus, huginn, muninn, norns, mimir, durable


async def test_full_bus_groups_by_fingerprint_and_emits_balanced_candidate_once() -> None:
    bus, huginn, muninn, norns, mimir, durable = _learning_chain()
    success_one = _operational_input("a", OperationalOutcomeClass.SUCCESS)
    success_two = _operational_input("b", OperationalOutcomeClass.SUCCESS)
    other_mechanism = _operational_input(
        "c",
        OperationalOutcomeClass.ROLLBACK,
        different_mechanism=True,
    )
    control = _operational_input("d", OperationalOutcomeClass.ROLLBACK)

    await huginn.ingest(_operational_raw("named-alpha", success_one))
    await huginn.ingest(_operational_raw("named-beta", success_two))
    await huginn.ingest(_operational_raw("other-mechanism", other_mechanism))

    assert bus.messages_on("object.rule-candidate") == []
    assert norns.behavior_snapshot()["operational_case_cohort_held"] == 1
    same_cohort = await durable.read_state(
        f"operational-case-fingerprint-cohort:{success_one.failure_fingerprint.digest}"
    )
    other_cohort = await durable.read_state(
        f"operational-case-fingerprint-cohort:{other_mechanism.failure_fingerprint.digest}"
    )
    assert same_cohort is not None and len(cast(list[object], same_cohort["cases"])) == 2
    assert other_cohort is not None and len(cast(list[object], other_cohort["cases"])) == 1

    await huginn.ingest(_operational_raw("balanced-control", control))

    contexts = bus.messages_on("object.context-index")
    candidates = bus.messages_on("object.rule-candidate")
    assert len(candidates) == 1
    assert len(mimir.pending_candidates()) == 1
    assert contexts[-1].payload["failure_fingerprint"] == success_one.failure_fingerprint.digest
    assert contexts[-1].key == success_one.failure_fingerprint.digest
    operational_events = [
        message
        for message in bus.messages_on("object.event")
        if message.payload["event_type"] == "case_history.operational_case.v1"
    ]
    assert all(message.key == message.payload["resource_id"] for message in operational_events)
    assert contexts[-1].payload["negative"] is True
    evidence = cast(dict[str, object], candidates[0].payload["evidence"])
    assert evidence["outcome_counts"] == {"rollback": 1, "success": 2}
    immutable_refs = cast(list[str], evidence["immutable_case_refs"])
    assert len(immutable_refs) == 3
    assert all(ref.startswith("case-history:") and ref.count(":") == 3 for ref in immutable_refs)

    await huginn.ingest(_operational_raw("balanced-control", control))
    assert len(bus.messages_on("object.rule-candidate")) == 1


async def test_raw_response_outcome_cannot_create_candidate() -> None:
    bus, huginn, muninn, _norns, _mimir, _durable = _learning_chain()

    await huginn.ingest(_raw(_outcome(1, label="verified", mode="enforce")))
    await huginn.ingest(_raw(_outcome(2, label="mismatch", mode="shadow")))

    assert bus.messages_on("object.context-index") == []
    assert bus.messages_on("object.rule-candidate") == []
    assert muninn.behavior_snapshot()["operating_pattern:mechanism_evidence_insufficient"] == 2


async def test_invalid_operational_case_producer_and_payload_are_held() -> None:
    bus, huginn, muninn, _norns, _mimir, _durable = _learning_chain()
    case_input = _operational_input("e", OperationalOutcomeClass.SUCCESS)

    await muninn.on_typed_message(
        "object.event",
        {
            "producer_principal": "NotHuginn",
            "event_type": "case_history.operational_case.v1",
            "attributes": case_input.to_mapping(),
        },
    )
    invalid = _operational_raw("invalid-payload", case_input)
    invalid["attributes"] = {"unexpected": "value"}
    await huginn.ingest(invalid)

    assert bus.messages_on("object.context-index") == []
    behavior = muninn.behavior_snapshot()
    assert behavior["operational_case:invalid_producer"] == 1
    assert behavior["operational_case:invalid_payload"] == 1


async def test_operational_case_requires_materializer_and_durable_store() -> None:
    case_input = _operational_input("f", OperationalOutcomeClass.SUCCESS)
    payload = {
        "producer_principal": "Huginn",
        "event_type": "case_history.operational_case.v1",
        "attributes": case_input.to_mapping(),
    }
    without_materializer = Muninn(durable_state_store=InMemoryStateStore())
    without_durable_store = Muninn(
        case_history=CaseHistoryMaterializer(
            metadata=InMemoryCaseHistoryMetadataStore(),
            artifacts=InMemoryCaseHistoryArtifactStore(),
        )
    )

    await without_materializer.on_typed_message("object.event", payload)
    await without_durable_store.on_typed_message("object.event", payload)

    assert (
        without_materializer.behavior_snapshot()["operational_case:materializer_unavailable"] == 1
    )
    assert (
        without_durable_store.behavior_snapshot()["operational_case:durable_store_unavailable"] == 1
    )
