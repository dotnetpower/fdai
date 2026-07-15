"""Tests for the console action-submit path (``POST /chat/action``).

Covers the submitter logic (RBAC capability gate, verb -> ActionType mapping,
proposal shape published to the raw event topic) and the route wiring (200
submitted / 403 capability / 400 bad body). The proposal that lands on the bus
is exactly what the pantheon's Huginn ingests, so the judge/approve/execute
pipeline (tested in tests/agents/test_chat_to_pipeline_e2e.py) takes over from
there.
"""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID

import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.testclient import TestClient

from fdai.core.console_request import PriorRequestOutcome
from fdai.core.incident.proposal_store import InMemoryIncidentProposalStore
from fdai.core.incident.registry import IncidentRegistry
from fdai.core.incident.workflow import IncidentLifecycleWorkflow
from fdai.core.rbac.resolver import Principal
from fdai.core.rbac.roles import Role
from fdai.delivery.read_api.auth import build_authenticator
from fdai.delivery.read_api.main import ReadApiConfig, build_app
from fdai.delivery.read_api.read_model import AuditItem, InMemoryConsoleReadModel
from fdai.delivery.read_api.routes.console_action import (
    ConsoleActionSubmitter,
    RefusalRecord,
    make_console_action_route,
)
from fdai.delivery.read_api.routes.incident_projection import project_incidents
from fdai.shared.contracts.models import IncidentSeverity, IncidentState
from fdai.shared.providers.testing.event_bus import InMemoryEventBus
from fdai.shared.providers.testing.state_store import InMemoryStateStore

_TOPIC = "fdai.events"


def _submitter() -> tuple[ConsoleActionSubmitter, InMemoryEventBus]:
    bus = InMemoryEventBus()
    return ConsoleActionSubmitter(event_bus=bus, raw_event_topic=_TOPIC), bus


async def _drain(bus: InMemoryEventBus, topic: str) -> list[Any]:
    out: list[Any] = []
    async for env in bus.subscribe(topic, "test-group"):
        out.append(env)
    return out


def _principal(oid: str, role: Role) -> Principal:
    return Principal(oid=oid, roles=frozenset({role}))


# ---------------------------------------------------------------------------
# Submitter logic
# ---------------------------------------------------------------------------


def test_reader_is_refused_and_nothing_is_published() -> None:
    sub, bus = _submitter()
    res = asyncio.run(
        sub.submit(question="restart svc-1", principal=_principal("u-reader", Role.READER))
    )
    assert res["submitted"] is False
    assert res["reason"] == "rbac_capability"
    assert res["required_capability"] == "author-draft-pr"
    assert asyncio.run(_drain(bus, _TOPIC)) == []


def test_contributor_submits_and_publishes_the_proposal() -> None:
    sub, bus = _submitter()
    res = asyncio.run(
        sub.submit(
            question="restart svc-1 now",
            principal=_principal("u-contrib", Role.CONTRIBUTOR),
            session_id="s1",
        )
    )
    assert res["submitted"] is True
    assert res["action_type"] == "ops.restart-service"
    corr = res["correlation_id"]

    envs = asyncio.run(_drain(bus, _TOPIC))
    assert len(envs) == 1
    payload = envs[0].payload
    assert payload["initiator_principal"] == "u-contrib"
    assert payload["operator_initiated"] is True
    assert payload["action_type"] == "ops.restart-service"
    assert payload["event_type"] == "operator_request"
    assert payload["correlation_id"] == corr
    assert payload["idempotency_key"] == corr
    # Keyed by the resource so per-resource ordering holds.
    assert envs[0].key == "svc-1"


def test_owner_may_submit() -> None:
    sub, bus = _submitter()
    res = asyncio.run(
        sub.submit(question="failover prod-1", principal=_principal("u-owner", Role.OWNER))
    )
    assert res["submitted"] is True
    assert res["action_type"] == "ops.failover-primary"


def test_unmapped_command_abstains_without_publishing() -> None:
    sub, bus = _submitter()
    res = asyncio.run(
        sub.submit(
            question="provision a new cluster",
            principal=_principal("u-contrib", Role.CONTRIBUTOR),
        )
    )
    assert res["submitted"] is False
    assert res["reason"] == "unmapped_action_intent"
    assert asyncio.run(_drain(bus, _TOPIC)) == []


def test_incident_request_requires_same_session_confirmation_then_creates() -> None:
    bus = InMemoryEventBus()
    registry = IncidentRegistry(state_store=InMemoryStateStore())
    submitter = ConsoleActionSubmitter(
        event_bus=bus,
        raw_event_topic=_TOPIC,
        incident_workflow=IncidentLifecycleWorkflow(registry=registry),
    )
    principal = _principal("u-contrib", Role.CONTRIBUTOR)

    prepared = asyncio.run(
        submitter.submit(
            question="prod-api-01 대상으로 SEV2 장애 케이스 열어줘",
            principal=principal,
            session_id="incident-session",
        )
    )
    created = asyncio.run(
        submitter.submit(
            question="확인",
            principal=principal,
            session_id="incident-session",
        )
    )

    assert prepared["submitted"] is False
    assert prepared["reason"] == "incident_confirmation_required"
    assert "확인하면 생성" in prepared["message"]
    assert created["submitted"] is True
    assert created["action_type"] == "incident.create"
    assert created["created"] is True
    assert len(registry.snapshot()) == 1
    assert asyncio.run(_drain(bus, _TOPIC)) == []


def test_created_incident_audit_projects_into_roster() -> None:
    store = InMemoryStateStore()
    registry = IncidentRegistry(state_store=store)
    submitter = ConsoleActionSubmitter(
        event_bus=InMemoryEventBus(),
        raw_event_topic=_TOPIC,
        incident_workflow=IncidentLifecycleWorkflow(registry=registry),
    )
    principal = _principal("u-contrib", Role.CONTRIBUTOR)
    asyncio.run(
        submitter.submit(
            question="Open a SEV2 incident for target prod-api-01",
            principal=principal,
            session_id="s1",
        )
    )
    asyncio.run(submitter.submit(question="confirm", principal=principal, session_id="s1"))
    stored = tuple(store.audit_entries)[0]
    entry = stored["entry"]
    item = AuditItem(
        seq=1,
        event_id=str(entry["member_event_ids"][0]),
        correlation_id=str(entry["correlation_id"]),
        actor=str(entry["actor_oid"]),
        action_kind=str(entry["kind"]),
        mode="enforce",
        entry=entry,
        entry_hash=str(stored["entry_hash"]),
        previous_hash=str(stored["previous_hash"]),
        recorded_at=str(entry["opened_at"]),
    )

    roster = project_incidents((item,), status="active")

    assert len(roster) == 1
    assert roster[0].incident_id == entry["incident_id"]
    assert roster[0].correlation_id == entry["correlation_id"]


def test_incident_request_with_missing_fields_asks_for_details() -> None:
    bus = InMemoryEventBus()
    submitter = ConsoleActionSubmitter(
        event_bus=bus,
        raw_event_topic=_TOPIC,
        incident_workflow=IncidentLifecycleWorkflow(
            registry=IncidentRegistry(state_store=InMemoryStateStore())
        ),
    )

    result = asyncio.run(
        submitter.submit(
            question="장애 케이스 생성해줘",
            principal=_principal("u-contrib", Role.CONTRIBUTOR),
            session_id="incident-session",
        )
    )

    assert result["submitted"] is False
    assert result["reason"] == "incident_details_required"
    assert "severity" in result["message"]


def test_incident_confirmation_is_isolated_by_principal_and_session() -> None:
    registry = IncidentRegistry(state_store=InMemoryStateStore())
    submitter = ConsoleActionSubmitter(
        event_bus=InMemoryEventBus(),
        raw_event_topic=_TOPIC,
        incident_workflow=IncidentLifecycleWorkflow(registry=registry),
    )
    asyncio.run(
        submitter.submit(
            question="Open a SEV2 incident for target prod-api-01",
            principal=_principal("u-one", Role.CONTRIBUTOR),
            session_id="s1",
        )
    )

    wrong_user = asyncio.run(
        submitter.submit(
            question="confirm",
            principal=_principal("u-two", Role.CONTRIBUTOR),
            session_id="s1",
        )
    )
    wrong_session = asyncio.run(
        submitter.submit(
            question="confirm",
            principal=_principal("u-one", Role.CONTRIBUTOR),
            session_id="s2",
        )
    )

    assert wrong_user["reason"] == "unmapped_action_intent"
    assert wrong_session["reason"] == "unmapped_action_intent"
    assert registry.snapshot() == {}


def test_incident_confirmation_crosses_submitter_replica() -> None:
    proposals = InMemoryIncidentProposalStore()
    workflow = IncidentLifecycleWorkflow(
        registry=IncidentRegistry(state_store=InMemoryStateStore())
    )
    first = ConsoleActionSubmitter(
        event_bus=InMemoryEventBus(),
        raw_event_topic=_TOPIC,
        incident_workflow=workflow,
        incident_proposals=proposals,
    )
    second = ConsoleActionSubmitter(
        event_bus=InMemoryEventBus(),
        raw_event_topic=_TOPIC,
        incident_workflow=workflow,
        incident_proposals=proposals,
    )
    principal = _principal("u-contrib", Role.CONTRIBUTOR)

    prepared = asyncio.run(
        first.submit(
            question="Open a SEV2 incident for target prod-api-01",
            principal=principal,
            session_id="s1",
        )
    )
    confirmed = asyncio.run(second.submit(question="confirm", principal=principal, session_id="s1"))

    assert prepared["reason"] == "incident_confirmation_required"
    assert confirmed["submitted"] is True
    assert confirmed["created"] is True


async def test_concurrent_incident_confirmation_creates_once() -> None:
    proposals = InMemoryIncidentProposalStore()
    registry = IncidentRegistry(state_store=InMemoryStateStore())
    submitter = ConsoleActionSubmitter(
        event_bus=InMemoryEventBus(),
        raw_event_topic=_TOPIC,
        incident_workflow=IncidentLifecycleWorkflow(registry=registry),
        incident_proposals=proposals,
    )
    principal = _principal("u-contrib", Role.CONTRIBUTOR)
    await submitter.submit(
        question="Open a SEV2 incident for target prod-api-01",
        principal=principal,
        session_id="s1",
    )

    results = await asyncio.gather(
        *(
            submitter.submit(question="confirm", principal=principal, session_id="s1")
            for _ in range(8)
        )
    )

    assert sum(result["submitted"] is True for result in results) == 1
    assert len(registry.snapshot()) == 1


def test_sessionless_incident_request_and_confirmation_are_refused() -> None:
    registry = IncidentRegistry(state_store=InMemoryStateStore())
    submitter = ConsoleActionSubmitter(
        event_bus=InMemoryEventBus(),
        raw_event_topic=_TOPIC,
        incident_workflow=IncidentLifecycleWorkflow(registry=registry),
    )
    principal = _principal("u-contrib", Role.CONTRIBUTOR)

    prepared = asyncio.run(
        submitter.submit(
            question="Open a SEV2 incident for target prod-api-01",
            principal=principal,
        )
    )
    confirmed = asyncio.run(submitter.submit(question="confirm", principal=principal))
    ordinary_action = asyncio.run(submitter.submit(question="restart svc-1", principal=principal))

    assert prepared["reason"] == "incident_session_required"
    assert confirmed["reason"] == "incident_session_required"
    assert ordinary_action["submitted"] is True
    assert registry.snapshot() == {}


async def test_incident_transition_and_assignment_commands_use_registry() -> None:
    registry = IncidentRegistry(state_store=InMemoryStateStore())
    incident = await registry.open(
        correlation_keys=("resource:prod-api-01",),
        severity=IncidentSeverity.SEV2,
        member_event_ids=(UUID("00000000-0000-0000-0000-000000000001"),),
        actor_oid="Heimdall",
    )
    submitter = ConsoleActionSubmitter(
        event_bus=InMemoryEventBus(),
        raw_event_topic=_TOPIC,
        incident_workflow=IncidentLifecycleWorkflow(registry=registry),
    )
    principal = _principal("u-contrib", Role.CONTRIBUTOR)

    transitioned = await submitter.submit(
        question=f"transition incident {incident.incident_id} to triaging",
        principal=principal,
        session_id="s1",
    )
    assigned = await submitter.submit(
        question=f"incident {incident.incident_id} 담당자 operator-oid 지정",
        principal=principal,
        session_id="s1",
    )

    current = registry.get(incident.incident_id)
    assert transitioned["submitted"] is True
    assert transitioned["action_type"] == "incident.transition"
    assert assigned["submitted"] is True
    assert assigned["action_type"] == "incident.assign"
    assert current is not None
    assert current.state is IncidentState.TRIAGING
    assert current.assignee_oid == "operator-oid"


def test_incident_ticket_request_routes_to_action_type_pipeline() -> None:
    bus = InMemoryEventBus()
    submitter = ConsoleActionSubmitter(
        event_bus=bus,
        raw_event_topic=_TOPIC,
        action_type_names=frozenset({"tool.open-incident-ticket"}),
        incident_workflow=IncidentLifecycleWorkflow(
            registry=IncidentRegistry(state_store=InMemoryStateStore())
        ),
    )

    result = asyncio.run(
        submitter.submit(
            question="open incident ticket ISSUE-42",
            principal=_principal("u-contrib", Role.CONTRIBUTOR),
            session_id="s1",
        )
    )

    assert result["submitted"] is True
    assert result["action_type"] == "tool.open-incident-ticket"


def test_catalog_action_suffix_maps_without_guessing() -> None:
    bus = InMemoryEventBus()
    submitter = ConsoleActionSubmitter(
        event_bus=bus,
        raw_event_topic=_TOPIC,
        action_type_names=frozenset({"ops.flush-cache", "ops.scale-out"}),
    )

    result = asyncio.run(
        submitter.submit(
            question="flush cache cache-1",
            principal=_principal("u-contrib", Role.CONTRIBUTOR),
        )
    )

    assert result["submitted"] is True
    assert result["action_type"] == "ops.flush-cache"
    assert result["resource_id"] == "cache-1"


def test_exact_catalog_action_id_does_not_become_resource_id() -> None:
    bus = InMemoryEventBus()
    submitter = ConsoleActionSubmitter(
        event_bus=bus,
        raw_event_topic=_TOPIC,
        action_type_names=frozenset({"ops.scale-out"}),
    )

    result = asyncio.run(
        submitter.submit(
            question="run ops.scale-out workload-1",
            principal=_principal("u-contrib", Role.CONTRIBUTOR),
        )
    )

    assert result["submitted"] is True
    assert result["action_type"] == "ops.scale-out"
    assert result["resource_id"] == "workload-1"


def test_ambiguous_catalog_suffix_abstains() -> None:
    bus = InMemoryEventBus()
    submitter = ConsoleActionSubmitter(
        event_bus=bus,
        raw_event_topic=_TOPIC,
        action_type_names=frozenset({"ops.scale-out", "remediate.scale-out"}),
    )

    result = asyncio.run(
        submitter.submit(
            question="scale out workload-1",
            principal=_principal("u-contrib", Role.CONTRIBUTOR),
        )
    )

    assert result["submitted"] is False
    assert result["reason"] == "unmapped_action_intent"


# ---------------------------------------------------------------------------
# Refusal observability (critique #21 - privilege-probing detection seam)
# ---------------------------------------------------------------------------


def _submitter_with_observer(
    records: list[RefusalRecord],
    *,
    prior: PriorRequestOutcome | None = None,
    observer_raises: bool = False,
) -> ConsoleActionSubmitter:
    bus = InMemoryEventBus()

    async def _observe(record: RefusalRecord) -> None:
        if observer_raises:
            raise RuntimeError("sink down")
        records.append(record)

    lookup = None
    if prior is not None:

        async def _lookup(_oid: str, _res: str | None, _at: str) -> PriorRequestOutcome:
            return prior

        lookup = _lookup

    return ConsoleActionSubmitter(
        event_bus=bus,
        raw_event_topic=_TOPIC,
        prior_outcome_lookup=lookup,
        refusal_observer=_observe,
    )


def test_observer_notified_on_capability_refusal() -> None:
    records: list[RefusalRecord] = []
    sub = _submitter_with_observer(records)
    asyncio.run(sub.submit(question="restart svc-1", principal=_principal("u-r", Role.READER)))
    assert len(records) == 1
    assert records[0].reason == "rbac_capability"
    assert records[0].actor == "u-r"


def test_observer_notified_on_blank_principal() -> None:
    records: list[RefusalRecord] = []
    sub = _submitter_with_observer(records)
    asyncio.run(sub.submit(question="restart svc-1", principal=_principal("   ", Role.CONTRIBUTOR)))
    assert len(records) == 1
    assert records[0].reason == "invalid_principal"
    assert records[0].actor == ""


def test_observer_notified_on_deny_override() -> None:
    records: list[RefusalRecord] = []
    sub = _submitter_with_observer(records, prior=PriorRequestOutcome.DENIED)
    asyncio.run(sub.submit(question="restart svc-1", principal=_principal("u-c", Role.CONTRIBUTOR)))
    assert len(records) == 1
    assert records[0].reason == "deny_override_forbidden"
    assert records[0].action_type == "ops.restart-service"


def test_observer_not_called_on_success_or_unmapped() -> None:
    records: list[RefusalRecord] = []
    sub = _submitter_with_observer(records)
    # A successful submit is not a refusal.
    asyncio.run(sub.submit(question="restart svc-1", principal=_principal("u-c", Role.CONTRIBUTOR)))
    # An unmapped command is a UX refusal, not a security one - not observed.
    asyncio.run(
        sub.submit(question="provision a cluster", principal=_principal("u-c", Role.CONTRIBUTOR))
    )
    assert records == []


def test_observer_failure_does_not_break_refusal() -> None:
    sub = _submitter_with_observer([], observer_raises=True)
    res = asyncio.run(
        sub.submit(question="restart svc-1", principal=_principal("u-r", Role.READER))
    )
    # Observer raised, but the refusal is still returned intact.
    assert res["submitted"] is False
    assert res["reason"] == "rbac_capability"


# ---------------------------------------------------------------------------
# Scenario B - deny-override block on re-request
# ---------------------------------------------------------------------------


def _submitter_with_prior(
    outcome: PriorRequestOutcome,
) -> tuple[ConsoleActionSubmitter, InMemoryEventBus]:
    bus = InMemoryEventBus()

    async def _lookup(_oid: str, _resource: str | None, _action_type: str) -> PriorRequestOutcome:
        return outcome

    return (
        ConsoleActionSubmitter(event_bus=bus, raw_event_topic=_TOPIC, prior_outcome_lookup=_lookup),
        bus,
    )


def test_prior_deny_blocks_rerequest_and_publishes_nothing() -> None:
    sub, bus = _submitter_with_prior(PriorRequestOutcome.DENIED)
    res = asyncio.run(
        sub.submit(question="restart svc-1", principal=_principal("u", Role.CONTRIBUTOR))
    )
    assert res["submitted"] is False
    assert res["reason"] == "deny_override_forbidden"
    # A deny is authoritative - nothing re-enters the pipeline.
    assert asyncio.run(_drain(bus, _TOPIC)) == []


def test_prior_no_op_allows_rerequest() -> None:
    sub, bus = _submitter_with_prior(PriorRequestOutcome.NO_OP)
    res = asyncio.run(
        sub.submit(question="restart svc-1", principal=_principal("u", Role.CONTRIBUTOR))
    )
    assert res["submitted"] is True
    # An unnecessary prior conclusion does not block a fresh judgement.
    assert len(asyncio.run(_drain(bus, _TOPIC))) == 1


def test_no_lookup_seam_treats_every_request_as_fresh() -> None:
    # Default submitter (no lookup) never applies the deny-override block.
    sub, bus = _submitter()
    res = asyncio.run(
        sub.submit(question="restart svc-1", principal=_principal("u", Role.CONTRIBUTOR))
    )
    assert res["submitted"] is True
    assert len(asyncio.run(_drain(bus, _TOPIC))) == 1


def test_route_prior_deny_gets_403() -> None:
    sub, _bus = _submitter_with_prior(PriorRequestOutcome.DENIED)
    client = TestClient(_app(sub, _principal("u", Role.CONTRIBUTOR)))
    resp = client.post("/chat/action", json={"prompt": "restart svc-1"})
    assert resp.status_code == 403
    assert resp.json()["reason"] == "deny_override_forbidden"


# ---------------------------------------------------------------------------
# Route wiring
# ---------------------------------------------------------------------------


def _app(sub: ConsoleActionSubmitter, principal: Principal) -> Starlette:
    async def _authz(_req: Request) -> Principal:
        return principal

    return Starlette(routes=[make_console_action_route(submitter=sub, authorize_principal=_authz)])


def test_route_contributor_gets_200_submitted() -> None:
    sub, _bus = _submitter()
    client = TestClient(_app(sub, _principal("u", Role.CONTRIBUTOR)))
    resp = client.post("/chat/action", json={"prompt": "restart svc-1", "session_id": "s"})
    assert resp.status_code == 200
    assert resp.json()["submitted"] is True


def test_route_reader_gets_403_capability() -> None:
    sub, _bus = _submitter()
    client = TestClient(_app(sub, _principal("u", Role.READER)))
    resp = client.post("/chat/action", json={"prompt": "restart svc-1"})
    assert resp.status_code == 403
    assert resp.json()["reason"] == "rbac_capability"


def test_route_unmapped_is_200_not_submitted() -> None:
    sub, _bus = _submitter()
    client = TestClient(_app(sub, _principal("u", Role.CONTRIBUTOR)))
    resp = client.post("/chat/action", json={"prompt": "provision a cluster"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["submitted"] is False
    assert body["reason"] == "unmapped_action_intent"


def test_route_rejects_empty_prompt() -> None:
    sub, _bus = _submitter()
    client = TestClient(_app(sub, _principal("u", Role.CONTRIBUTOR)))
    resp = client.post("/chat/action", json={"prompt": "   "})
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# build_app wiring (dev mode grants a Contributor principal)
# ---------------------------------------------------------------------------


@pytest.fixture
def _dev_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FDAI_READ_API_DEV_MODE", "1")


def _built_client(*, wire_action: bool) -> tuple[TestClient, InMemoryEventBus]:
    bus = InMemoryEventBus()
    submitter = ConsoleActionSubmitter(event_bus=bus, raw_event_topic=_TOPIC)
    auth = build_authenticator(verifier=lambda t: {"oid": "u"}, resolver=lambda claims: None)
    app = build_app(
        authenticator=auth,
        read_model=InMemoryConsoleReadModel(),
        config=ReadApiConfig(
            dev_mode=True,
            console_action=submitter if wire_action else None,
        ),
    )
    return TestClient(app), bus


def test_build_app_registers_action_route_when_wired(_dev_mode: None) -> None:
    client, bus = _built_client(wire_action=True)
    # dev mode grants a Contributor principal, so the submit succeeds.
    resp = client.post("/chat/action", json={"prompt": "restart svc-1"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["submitted"] is True
    # The proposal actually reached the bus.
    envs = asyncio.run(_drain(bus, _TOPIC))
    assert len(envs) == 1
    assert envs[0].payload["action_type"] == "ops.restart-service"


def test_build_app_omits_action_route_when_not_wired(_dev_mode: None) -> None:
    client, _bus = _built_client(wire_action=False)
    resp = client.post("/chat/action", json={"prompt": "restart svc-1"})
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Hardening
# ---------------------------------------------------------------------------


def test_empty_topic_is_rejected_at_construction() -> None:
    import pytest as _pytest

    with _pytest.raises(ValueError, match="non-empty topic"):
        ConsoleActionSubmitter(event_bus=InMemoryEventBus(), raw_event_topic="  ")


def test_blank_principal_oid_fails_closed() -> None:
    sub, bus = _submitter()
    blank = Principal(oid="  ", roles=frozenset({Role.CONTRIBUTOR}))
    res = asyncio.run(sub.submit(question="restart svc-1", principal=blank))
    assert res["submitted"] is False
    assert res["reason"] == "invalid_principal"
    assert asyncio.run(_drain(bus, _TOPIC)) == []


def test_client_idempotency_key_becomes_the_proposal_dedup_key() -> None:
    sub, bus = _submitter()
    res = asyncio.run(
        sub.submit(
            question="restart svc-1",
            principal=_principal("u", Role.CONTRIBUTOR),
            idempotency_key="dup-1",
        )
    )
    assert res["submitted"] is True
    envs = asyncio.run(_drain(bus, _TOPIC))
    # The dedup key is namespaced by the initiator so one operator cannot reuse
    # another's key to suppress their action.
    assert envs[0].payload["idempotency_key"] == "u::dup-1"
    # correlation_id stays server-generated and distinct from the dedup key.
    assert envs[0].payload["correlation_id"] != "dup-1"


def test_oversized_session_and_idempotency_keys_are_rejected() -> None:
    sub, bus = _submitter()
    oversized_session = asyncio.run(
        sub.submit(
            question="restart svc-1",
            principal=_principal("u", Role.CONTRIBUTOR),
            session_id="s" * 5_000,
        )
    )
    oversized_idempotency = asyncio.run(
        sub.submit(
            question="restart svc-1",
            principal=_principal("u", Role.CONTRIBUTOR),
            idempotency_key="k" * 5_000,
        )
    )

    assert oversized_session["reason"] == "session_id_too_long"
    assert oversized_idempotency["reason"] == "idempotency_key_too_long"
    assert asyncio.run(_drain(bus, _TOPIC)) == []


def test_oversized_question_is_bounded_in_the_proposal() -> None:
    sub, bus = _submitter()
    huge = "restart svc-1 " + ("x" * 10_000)

    result = asyncio.run(
        sub.submit(
            question=huge,
            principal=_principal("u", Role.CONTRIBUTOR),
            session_id="s1",
            idempotency_key="k1",
        )
    )

    assert result["submitted"] is True
    payload = asyncio.run(_drain(bus, _TOPIC))[0].payload
    assert len(payload["params"]["question"]) <= 2_000


def test_route_rejects_oversized_prompt() -> None:
    sub, _bus = _submitter()
    client = TestClient(_app(sub, _principal("u", Role.CONTRIBUTOR)))
    resp = client.post("/chat/action", json={"prompt": "restart " + ("x" * 5_000)})
    assert resp.status_code == 400


def test_route_rejects_non_string_idempotency_key() -> None:
    sub, _bus = _submitter()
    client = TestClient(_app(sub, _principal("u", Role.CONTRIBUTOR)))
    resp = client.post("/chat/action", json={"prompt": "restart svc-1", "idempotency_key": 5})
    assert resp.status_code == 400


@pytest.mark.parametrize("field", ["session_id", "idempotency_key"])
def test_route_rejects_oversized_identifier(field: str) -> None:
    sub, _bus = _submitter()
    client = TestClient(_app(sub, _principal("u", Role.CONTRIBUTOR)))

    response = client.post(
        "/chat/action",
        json={"prompt": "restart svc-1", field: "x" * 201},
    )

    assert response.status_code == 400
    assert field in response.text
