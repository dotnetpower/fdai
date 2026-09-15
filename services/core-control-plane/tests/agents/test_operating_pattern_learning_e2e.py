from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID

import pytest
from fdai.agents._framework.bus import InMemoryBus
from fdai.agents._framework.registry import load_pantheon
from fdai.agents.huginn import Huginn
from fdai.agents.mimir import Mimir
from fdai.agents.muninn import Muninn, _operating_pattern_state_key
from fdai.agents.norns import Norns, NornsCapacityError
from fdai.agents.saga import Saga
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
    mimir.bind_case_history(muninn._case_history)
    saga = Saga()
    for agent in (huginn, muninn, norns, mimir, saga):
        agent.bind_bus(bus)
    bus.subscribe("object.event", "Muninn", muninn.on_typed_message)
    bus.subscribe("object.context-index", "Norns", norns.on_typed_message)
    bus.subscribe("object.rule-candidate", "Mimir", mimir.on_typed_message)
    bus.subscribe("object.pattern", "Muninn", muninn.on_typed_message)
    bus.subscribe("object.state-snapshot", "Saga", saga.on_typed_message)
    return bus, huginn, muninn, norns, mimir, durable


async def test_unpublished_cohort_is_not_acknowledged_and_replays_after_restart() -> None:
    bus, huginn, _muninn, norns, _mimir, _durable = _learning_chain()
    norns.bind_candidate_publication_gate(lambda: False)
    await huginn.ingest(
        _operational_raw("first", _operational_input("a", OperationalOutcomeClass.SUCCESS))
    )
    await huginn.ingest(
        _operational_raw("second", _operational_input("b", OperationalOutcomeClass.SUCCESS))
    )
    with pytest.raises(NornsCapacityError, match="retain for replay"):
        await huginn.ingest(
            _operational_raw("control", _operational_input("c", OperationalOutcomeClass.ROLLBACK))
        )
    payload = bus.messages_on("object.context-index")[-1].payload
    with pytest.raises(NornsCapacityError, match="retain for replay"):
        await norns.on_typed_message("object.context-index", dict(payload))
    assert not bus.messages_on("object.pattern")
    restarted_bus = InMemoryBus(registry=load_pantheon(), isolate_handlers=False)
    restarted = Norns()
    restarted.bind_bus(restarted_bus)
    await restarted.on_typed_message("object.context-index", dict(payload))
    assert len(restarted_bus.messages_on("object.pattern")) == 1
    assert len(restarted_bus.messages_on("object.rule-candidate")) == 1
    assert restarted.pending_candidates == []


async def test_operational_case_does_not_cache_a_failed_durable_write() -> None:
    class _FailingStore(InMemoryStateStore):
        async def write_state_with_audit_if_absent(self, *args: Any, **kwargs: Any) -> bool:
            del args, kwargs
            raise RuntimeError("durable write failed")

    case_input = _operational_input("f", OperationalOutcomeClass.SUCCESS)
    muninn = Muninn(
        case_history=CaseHistoryMaterializer(
            metadata=InMemoryCaseHistoryMetadataStore(),
            artifacts=InMemoryCaseHistoryArtifactStore(),
        ),
        durable_state_store=_FailingStore(),
    )

    with pytest.raises(RuntimeError, match="durable write failed"):
        await muninn.on_typed_message(
            "object.event",
            {
                "producer_principal": "Huginn",
                "event_type": "case_history.operational_case.v1",
                "attributes": case_input.to_mapping(),
            },
        )

    assert (
        muninn.state_store.get(
            "operational_case_fingerprint_cohorts",
            _operating_pattern_state_key(case_input),
        )
        is None
    )


async def test_operational_case_does_not_cache_an_unpersisted_emission_marker() -> None:
    class _SecondWriteFails(InMemoryStateStore):
        def __init__(self) -> None:
            super().__init__()
            self.write_count = 0

        async def compare_and_set_state_with_audit(self, *args: Any, **kwargs: Any) -> bool:
            self.write_count += 1
            if any(":emitted:" in key for key in args[1].get("entries", {})):
                raise RuntimeError("emission marker write failed")
            return await super().compare_and_set_state_with_audit(*args, **kwargs)

        async def write_state_if_absent(self, key: str, value: dict[str, Any]) -> bool:
            self.write_count += 1
            if ":emitted:" in key:
                raise RuntimeError("emission marker write failed")
            return await super().write_state_if_absent(key, value)

    durable = _SecondWriteFails()
    bus = InMemoryBus(registry=load_pantheon(), isolate_handlers=False)
    muninn = Muninn(
        case_history=CaseHistoryMaterializer(
            metadata=InMemoryCaseHistoryMetadataStore(),
            artifacts=InMemoryCaseHistoryArtifactStore(),
        ),
        durable_state_store=durable,
    )
    muninn.bind_bus(bus)
    first = _operational_input("a", OperationalOutcomeClass.SUCCESS)
    second = _operational_input("b", OperationalOutcomeClass.SUCCESS)
    await muninn.on_typed_message(
        "object.event",
        {"producer_principal": "Huginn", **_operational_raw("first", first)},
    )

    with pytest.raises(RuntimeError, match="emission marker write failed"):
        await muninn.on_typed_message(
            "object.event",
            {"producer_principal": "Huginn", **_operational_raw("second", second)},
        )

    assert (
        muninn.state_store.get(
            "operational_case_fingerprint_cohorts", _operating_pattern_state_key(first)
        )
        is None
    )
    stored = await durable.read_state(f"case-history-derived:v1:{first.access_scope_digest}")
    assert stored is not None
    assert not any(":emitted:" in key for key in stored["entries"])


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
    projections = muninn._case_projection_store(success_one.access_scope_digest)
    same_cohort = await projections.read_state(_operating_pattern_state_key(success_one))
    other_cohort = await projections.read_state(_operating_pattern_state_key(other_mechanism))
    assert same_cohort is not None and len(cast(list[object], same_cohort["cases"])) == 2
    assert other_cohort is not None and len(cast(list[object], other_cohort["cases"])) == 1

    await huginn.ingest(_operational_raw("balanced-control", control))

    contexts = bus.messages_on("object.context-index")
    candidates = bus.messages_on("object.rule-candidate")
    assert len(candidates) == 1
    assert len(mimir.pending_candidates()) == 1
    assert contexts[-1].payload["failure_fingerprint"] == success_one.failure_fingerprint.digest
    assert contexts[-1].key == _operating_pattern_state_key(success_one)
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
    patterns = bus.messages_on("object.pattern")
    assert len(patterns) == 1
    pattern_id = patterns[0].payload["pattern_id"]
    key = f"{_operating_pattern_state_key(success_one)}:pattern:{pattern_id}"
    retained = await projections.read_state(key)
    assert retained is not None
    assert retained["execution_authority"] is False
    assert retained["promotion_authority"] is False
    snapshots = bus.messages_on("object.state-snapshot")
    assert len(snapshots) == 1
    assert snapshots[0].payload["pattern_id"] == pattern_id
    assert retained["candidate"]["evidence"]["immutable_case_refs"] == immutable_refs
    restarted = Muninn(durable_state_store=durable, case_history=muninn._case_history)
    await restarted.on_typed_message("object.pattern", dict(patterns[0].payload))
    assert restarted.state_store.get("operating_patterns", key) is None
    assert (
        await restarted._case_projection_store(success_one.access_scope_digest).read_state(key)
        == retained
    )
    query = {
        "cohort_key": _operating_pattern_state_key(success_one),
        "pattern_id": pattern_id,
        "access_scope_digest": success_one.access_scope_digest,
        "purpose": success_one.purpose,
    }
    assert await restarted.read_operating_pattern(**query) == retained
    from fdai.core.ontology_platform.functions import FunctionInvocationContext
    from fdai.core.ontology_platform.pattern_queries import OperatingPatternQuery
    from fdai.shared.providers.decision_evidence_verifier import DecisionEvidenceAdmission

    class _ReadAdmission:
        async def admit(self, **values):
            return DecisionEvidenceAdmission(
                **values,
                receipt_digest="sha256:" + "c" * 64,
                verification_bundle_digest="sha256:" + "d" * 64,
                verified_at=_NOW,
                valid_until=_NOW + timedelta(days=60),
            )

    reader = OperatingPatternQuery(
        store=durable,
        materializer=lambda: muninn._case_history,
        admission=_ReadAdmission(),
        source_revision="example-release",
        clock=lambda: _NOW + timedelta(days=1),
    )
    invocation = FunctionInvocationContext(
        caller_agent="Bragi",
        principal_ref="operator-one",
        principal_scope_digest="sha256:" + "f" * 64,
        purposes=("operations-review",),
    )
    result = await reader.read(
        {
            "access_scope_digest": success_one.access_scope_digest,
            "purpose": success_one.purpose,
            "failure_fingerprint": None,
            "limit": 20,
        },
        invocation,
    )
    assert result["patterns"][0]["pattern_id"] == pattern_id
    assert "params" not in result["patterns"][0]
    assert result["execution_authority"] is False
    with pytest.raises(PermissionError, match="authenticated"):
        await reader.read({}, FunctionInvocationContext(caller_agent="Bragi"))
    from unittest.mock import AsyncMock

    arguments = {
        "access_scope_digest": success_one.access_scope_digest,
        "purpose": success_one.purpose,
        "failure_fingerprint": None,
        "limit": 20,
    }
    never_read = AsyncMock()
    invalid_reader = OperatingPatternQuery(
        store=never_read,
        materializer=lambda: muninn._case_history,
        admission=_ReadAdmission(),
        source_revision="example-release",
        clock=lambda: _NOW,
    )
    for changes in (
        {"access_scope_digest": []},
        {"purpose": " "},
        {"failure_fingerprint": 1},
        {"limit": True},
    ):
        with pytest.raises(ValueError):
            await invalid_reader.read({**arguments, **changes}, invocation)
    never_read.read_state.assert_not_awaited()
    no_admission = OperatingPatternQuery(
        store=never_read,
        materializer=lambda: muninn._case_history,
        admission=None,
        source_revision="example-release",
        clock=lambda: _NOW,
    )
    with pytest.raises(PermissionError, match="admission"):
        await no_admission.read(arguments, invocation)
    never_read.read_state.assert_not_awaited()
    assert (
        await restarted.read_operating_pattern(**{**query, "access_scope_digest": "e" * 64}) is None
    )
    assert await restarted.read_operating_pattern(**{**query, "purpose": "other-purpose"}) is None
    emitted_candidate = bus.messages_on("object.rule-candidate")[0].payload
    assert emitted_candidate["case_scope"] == {
        "access_scope_digest": success_one.access_scope_digest,
        "purpose": success_one.purpose,
    }
    with pytest.raises(PermissionError, match="no longer current"):
        await mimir.on_typed_message(
            "object.rule-candidate",
            {
                **emitted_candidate,
                "case_scope": {"access_scope_digest": "e" * 64, "purpose": success_one.purpose},
            },
        )

    assert (await reader.read({**arguments, "purpose": "other-purpose"}, invocation))[
        "patterns"
    ] == []
    assert (await reader.read({**arguments, "failure_fingerprint": "f" * 64}, invocation))[
        "patterns"
    ] == []
    with pytest.raises(ValueError, match="fields"):
        await reader.read({**arguments, "extra": True}, invocation)

    class _ChangingCases:
        calls = 0

        async def current_revision_available(self, **_values):
            self.calls += 1
            return self.calls <= len(immutable_refs)

    changing_reader = OperatingPatternQuery(
        store=durable,
        materializer=lambda: _changing,
        admission=_ReadAdmission(),
        source_revision="example-release",
        clock=lambda: _NOW + timedelta(days=1),
    )
    _changing = _ChangingCases()
    with pytest.raises(PermissionError, match="changed"):
        await changing_reader.read(arguments, invocation)
    source_missing = await changing_reader.read(arguments, invocation)
    assert source_missing["unavailable"] is True and not source_missing["patterns"]

    for missing in ("source", "admission", "expired"):
        admission = AsyncMock()
        admission.admit.return_value = (
            None
            if missing == "admission"
            else await _ReadAdmission().admit(
                evidence_digest="sha256:" + "a" * 64,
                scope_digest="sha256:" + "b" * 64,
                purpose_id="case-history-read",
                source_revision="example-release",
            )
        )
        guarded_reader = OperatingPatternQuery(
            store=never_read,
            materializer=lambda: None,
            admission=_ReadAdmission() if missing == "source" else admission,
            source_revision="example-release",
            clock=lambda selected=missing: (
                _NOW + timedelta(days=61) if selected == "expired" else _NOW
            ),
        )
        if missing == "source":
            assert (await guarded_reader.read(arguments, invocation))["unavailable"] is True
        else:
            with pytest.raises(PermissionError, match="authorization"):
                await guarded_reader.read(arguments, invocation)
    never_read.read_state.assert_not_awaited()

    await huginn.ingest(_operational_raw("balanced-control", control))
    assert len(bus.messages_on("object.rule-candidate")) == 1


@pytest.mark.parametrize(
    "changes",
    [
        {"access_scope_digest": "e" * 64},
        {"purpose": "separate-operational-review"},
        {"fdai_revision": "e" * 40},
        {"scenario_set_version": "2.0.0"},
    ],
)
async def test_incompatible_cases_cannot_form_a_balanced_learning_cohort(
    changes: dict[str, object],
) -> None:
    bus, huginn, muninn, _norns, _mimir, durable = _learning_chain()
    success = _operational_input("a", OperationalOutcomeClass.SUCCESS)
    control = replace(_operational_input("b", OperationalOutcomeClass.ROLLBACK), **changes)
    await huginn.ingest(_operational_raw("isolated-success", success))
    await huginn.ingest(_operational_raw("isolated-control", control))
    assert _operating_pattern_state_key(success) != _operating_pattern_state_key(control)
    assert bus.messages_on("object.context-index") == []
    assert bus.messages_on("object.rule-candidate") == []
    for case_input in (success, control):
        cohort = await muninn._case_projection_store(case_input.access_scope_digest).read_state(
            _operating_pattern_state_key(case_input)
        )
        assert cohort is not None
        assert len(cohort["cases"]) == 1


@pytest.mark.parametrize(
    "mutation",
    ["wrong-owner", "wrong-scope", "wrong-pattern", "unknown-version", "extra-authority"],
)
async def test_unverified_pattern_publication_cannot_write_retained_state(mutation: str) -> None:
    bus, huginn, muninn, _norns, _mimir, durable = _learning_chain()
    success = _operational_input("a", OperationalOutcomeClass.SUCCESS)
    control = _operational_input("b", OperationalOutcomeClass.ROLLBACK)
    await huginn.ingest(_operational_raw("first", success))
    await huginn.ingest(_operational_raw("second", control))
    original = bus.messages_on("object.pattern")[0].payload
    payload = dict(original)
    field = {
        "wrong-owner": "producer_principal",
        "wrong-scope": "access_scope_digest",
        "wrong-pattern": "pattern_id",
        "unknown-version": "schema_version",
        "extra-authority": "execution_authority",
    }[mutation]
    payload[field] = "Other" if mutation == "wrong-owner" else "e" * 64
    prior_snapshots = len(bus.messages_on("object.state-snapshot"))
    await muninn.on_typed_message("object.pattern", payload)
    assert len(bus.messages_on("object.state-snapshot")) == prior_snapshots
    key = f"{payload['cohort_key']}:pattern:{payload['pattern_id']}"
    retained = await muninn._case_projection_store(success.access_scope_digest).read_state(key)
    if mutation == "wrong-pattern":
        assert retained is None
    else:
        assert retained is not None
        assert retained["access_scope_digest"] == success.access_scope_digest


async def test_changed_pattern_candidate_is_not_returned_as_current_evidence() -> None:
    bus, huginn, muninn, _norns, _mimir, durable = _learning_chain()
    success = _operational_input("a", OperationalOutcomeClass.SUCCESS)
    await huginn.ingest(_operational_raw("first", success))
    await huginn.ingest(
        _operational_raw("second", _operational_input("b", OperationalOutcomeClass.ROLLBACK))
    )
    publication = bus.messages_on("object.pattern")[0].payload
    key = f"{publication['cohort_key']}:pattern:{publication['pattern_id']}"
    projections = muninn._case_projection_store(success.access_scope_digest)
    record = await projections.read_state(key)
    assert record is not None
    record["candidate"]["target_rule_id"] = "ops.other-action"
    state_key = f"case-history-derived:v1:{success.access_scope_digest}"
    state = await durable.read_state(state_key)
    assert state is not None
    state["entries"][key]["value"] = record
    await durable.write_state(state_key, state)
    assert (
        await muninn.read_operating_pattern(
            cohort_key=publication["cohort_key"],
            pattern_id=publication["pattern_id"],
            access_scope_digest=success.access_scope_digest,
            purpose=success.purpose,
        )
        is None
    )


async def test_removed_case_artifact_invalidates_retained_pattern_read() -> None:
    bus, huginn, muninn, _norns, _mimir, _durable = _learning_chain()
    success = _operational_input("a", OperationalOutcomeClass.SUCCESS)
    await huginn.ingest(_operational_raw("first", success))
    await huginn.ingest(
        _operational_raw("second", _operational_input("b", OperationalOutcomeClass.ROLLBACK))
    )
    publication = bus.messages_on("object.pattern")[0].payload
    assert muninn._case_history is not None
    metadata = muninn._case_history._metadata
    records = await metadata.list_closed(
        access_scope_digest=success.access_scope_digest,
        purpose=success.purpose,
        outcome_labels=(),
        limit=10,
    )
    assert records[0].storage_ref is not None
    await muninn._case_history._artifacts.delete(records[0].storage_ref)
    assert (
        await muninn.read_operating_pattern(
            cohort_key=publication["cohort_key"],
            pattern_id=publication["pattern_id"],
            access_scope_digest=success.access_scope_digest,
            purpose=success.purpose,
        )
        is None
    )


async def test_delayed_pattern_uses_its_frozen_cohort_after_later_case_arrives() -> None:
    bus, huginn, muninn, _norns, _mimir, durable = _learning_chain()
    success = _operational_input("a", OperationalOutcomeClass.SUCCESS)
    await huginn.ingest(_operational_raw("first", success))
    await huginn.ingest(
        _operational_raw("second", _operational_input("b", OperationalOutcomeClass.ROLLBACK))
    )
    original = dict(bus.messages_on("object.pattern")[0].payload)
    original_key = f"{original['cohort_key']}:pattern:{original['pattern_id']}"
    await huginn.ingest(
        _operational_raw("third", _operational_input("c", OperationalOutcomeClass.SUCCESS))
    )
    restarted = Muninn(durable_state_store=durable, case_history=muninn._case_history)
    await restarted.on_typed_message("object.pattern", original)
    assert (
        await restarted._case_projection_store(success.access_scope_digest).read_state(original_key)
        is not None
    )
    assert restarted.behavior_snapshot()["operating_pattern:retained"] == 1


async def test_new_case_revision_withdraws_old_pattern_from_current_reads() -> None:
    bus, huginn, muninn, _norns, _mimir, _durable = _learning_chain()
    success = _operational_input("a", OperationalOutcomeClass.SUCCESS)
    await huginn.ingest(_operational_raw("first", success))
    await huginn.ingest(
        _operational_raw("second", _operational_input("b", OperationalOutcomeClass.ROLLBACK))
    )
    original = bus.messages_on("object.pattern")[0].payload
    assert muninn._case_history is not None
    metadata = muninn._case_history._metadata
    records = await metadata.list_closed(
        access_scope_digest=success.access_scope_digest,
        purpose=success.purpose,
        outcome_labels=(),
        limit=10,
    )
    prior = records[0]
    await metadata.append_revision(
        replace(
            prior,
            revision=prior.revision + 1,
            state_revision=prior.state_revision + 1,
            parent_manifest_digest=prior.manifest_digest,
            manifest_digest="e" * 64,
        )
    )
    assert (
        await muninn.read_operating_pattern(
            cohort_key=original["cohort_key"],
            pattern_id=original["pattern_id"],
            access_scope_digest=success.access_scope_digest,
            purpose=success.purpose,
        )
        is None
    )


async def test_raw_response_outcome_cannot_create_candidate() -> None:
    bus, huginn, muninn, _norns, _mimir, _durable = _learning_chain()

    await huginn.ingest(_raw(_outcome(1, label="verified", mode="enforce")))
    await huginn.ingest(_raw(_outcome(2, label="mismatch", mode="shadow")))

    assert bus.messages_on("object.context-index") == []
    assert bus.messages_on("object.rule-candidate") == []
    assert muninn.behavior_snapshot()["operating_pattern:mechanism_evidence_insufficient"] == 2


async def test_retention_tick_removes_pattern_and_cohort_bodies_and_blocks_replay() -> None:
    from fdai.core.case_history import CaseHistoryRetentionService
    from fdai.core.case_history.derived import CaseHistoryDerivedRetention

    bus, huginn, muninn, _norns, _mimir, durable = _learning_chain()
    success = _operational_input("a", OperationalOutcomeClass.SUCCESS)
    await huginn.ingest(_operational_raw("first", success))
    await huginn.ingest(
        _operational_raw("second", _operational_input("b", OperationalOutcomeClass.ROLLBACK))
    )
    publication = dict(bus.messages_on("object.pattern")[0].payload)
    assert muninn._case_history is not None
    materializer = muninn._case_history
    muninn._case_history_retention = CaseHistoryRetentionService(
        metadata=materializer._metadata,
        artifacts=materializer._artifacts,
        derived_data=CaseHistoryDerivedRetention(store=durable, materializer=materializer),
    )
    muninn._case_history_clock = lambda: _NOW + timedelta(days=100)
    await huginn.ingest(
        {
            "id": "case-history-retention:example",
            "event_id": "case-history-retention:example",
            "correlation_id": "case-history-retention:example",
            "idempotency_key": "case-history-retention:example",
            "source": "case-history-retention-scheduler",
            "event_type": "case_history.retention_due",
            "attributes": {},
        }
    )
    state = await durable.read_state(f"case-history-derived:v1:{success.access_scope_digest}")
    assert state is not None and state["entries"] == {}
    await muninn.on_typed_message("object.pattern", publication)
    after = await durable.read_state(f"case-history-derived:v1:{success.access_scope_digest}")
    assert after == state
    assert muninn.state_store.get("operating_patterns", publication["pattern_id"]) is None


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
