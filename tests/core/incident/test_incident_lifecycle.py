"""Incident lifecycle - state-machine + registry + audit persistence."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from fdai.core.incident import (
    IncidentRegistry,
    IncidentReplayError,
    IncidentStateMachine,
    IncidentTransitionError,
    incident_id_for,
)
from fdai.shared.contracts.models import Incident, IncidentSeverity, IncidentState
from fdai.shared.providers.state_store import IncidentWriteConflictError
from fdai.shared.providers.testing.state_store import InMemoryStateStore


@pytest.fixture
def state_store() -> InMemoryStateStore:
    return InMemoryStateStore()


@pytest.fixture
def registry(state_store: InMemoryStateStore) -> IncidentRegistry:
    return IncidentRegistry(state_store=state_store)


# ---------------------------------------------------------------------------
# Deterministic id
# ---------------------------------------------------------------------------


def test_incident_id_is_deterministic_over_key_set_permutations() -> None:
    a = incident_id_for(["resource:foo", "deployment:bar"])
    b = incident_id_for(["deployment:bar", "resource:foo"])
    c = incident_id_for(["resource:foo", "resource:foo", "deployment:bar"])  # duplicate
    assert a == b == c


def test_incident_id_requires_at_least_one_key() -> None:
    with pytest.raises(ValueError, match="at least one correlation key"):
        incident_id_for([])
    with pytest.raises(ValueError, match="at least one correlation key"):
        incident_id_for(["", ""])  # empty strings filtered out -> empty set


# ---------------------------------------------------------------------------
# State-machine: legal edges + rejects
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "current, target",
    [
        (IncidentState.OPEN, IncidentState.TRIAGING),
        (IncidentState.OPEN, IncidentState.MITIGATED),
        (IncidentState.TRIAGING, IncidentState.MITIGATED),
        (IncidentState.TRIAGING, IncidentState.RESOLVED),
        (IncidentState.MITIGATED, IncidentState.RESOLVED),
        (IncidentState.RESOLVED, IncidentState.CLOSED),
        (IncidentState.RESOLVED, IncidentState.TRIAGING),
    ],
)
def test_state_machine_accepts_every_legal_edge(
    current: IncidentState, target: IncidentState
) -> None:
    IncidentStateMachine().validate(current=current, target=target)


@pytest.mark.parametrize(
    "current, target",
    [
        # No skipping open -> resolved / closed.
        (IncidentState.OPEN, IncidentState.RESOLVED),
        (IncidentState.OPEN, IncidentState.CLOSED),
        # Cannot regress mitigation.
        (IncidentState.MITIGATED, IncidentState.TRIAGING),
        (IncidentState.MITIGATED, IncidentState.OPEN),
        # Closed is terminal.
        (IncidentState.CLOSED, IncidentState.OPEN),
        (IncidentState.CLOSED, IncidentState.TRIAGING),
        (IncidentState.CLOSED, IncidentState.MITIGATED),
        (IncidentState.CLOSED, IncidentState.RESOLVED),
        # Same-state transition is illegal at the state-machine level;
        # the registry short-circuits it before invoking the machine.
        (IncidentState.OPEN, IncidentState.OPEN),
    ],
)
def test_state_machine_rejects_illegal_edges(current: IncidentState, target: IncidentState) -> None:
    with pytest.raises(IncidentTransitionError):
        IncidentStateMachine().validate(current=current, target=target)


# ---------------------------------------------------------------------------
# Registry: open + transition + idempotency
# ---------------------------------------------------------------------------


async def test_open_creates_incident_and_writes_audit(
    registry: IncidentRegistry, state_store: InMemoryStateStore
) -> None:
    event_id = UUID("00000000-0000-0000-0000-000000000001")
    inc = await registry.open(
        correlation_keys=["resource:foo"],
        severity=IncidentSeverity.SEV2,
        member_event_ids=[event_id],
        actor_oid="oid-detector",
    )
    assert inc.state is IncidentState.OPEN
    assert inc.severity is IncidentSeverity.SEV2
    assert inc.member_event_ids == (event_id,)
    assert inc.incident_id == incident_id_for(["resource:foo"])

    transitions = list(state_store.incident_transitions)
    assert len(transitions) == 1
    assert transitions[0]["kind"] == "incident.open"
    assert transitions[0]["correlation_id"] == str(inc.incident_id)
    assert transitions[0]["actor_oid"] == "oid-detector"
    assert state_store.verify_chain()  # audit hash-chain remains intact


async def test_open_is_idempotent_and_merges_member_events(
    registry: IncidentRegistry, state_store: InMemoryStateStore
) -> None:
    keys = ["resource:foo"]
    a = UUID("00000000-0000-0000-0000-00000000000a")
    b = UUID("00000000-0000-0000-0000-00000000000b")
    inc1 = await registry.open(
        correlation_keys=keys,
        severity=IncidentSeverity.SEV3,
        member_event_ids=[a],
        actor_oid="oid-detector",
    )
    inc2 = await registry.open(
        correlation_keys=keys,
        severity=IncidentSeverity.SEV3,
        member_event_ids=[b, a],  # new + duplicate of a
        actor_oid="oid-detector",
    )
    assert inc1.incident_id == inc2.incident_id
    assert inc2.member_event_ids == (a, b)  # deduped + insertion-ordered
    transitions = list(state_store.incident_transitions)
    assert [entry["kind"] for entry in transitions] == [
        "incident.open",
        "incident.members",
    ]

    restored = IncidentRegistry(state_store=InMemoryStateStore())
    restored.rehydrate(await state_store.read_incident_transitions())
    assert restored.get(inc1.incident_id).member_event_ids == (a, b)  # type: ignore[union-attr]


async def test_open_is_idempotent_across_registries_and_actors(
    state_store: InMemoryStateStore,
) -> None:
    first_registry = IncidentRegistry(state_store=state_store)
    second_registry = IncidentRegistry(state_store=state_store)
    event_id = UUID("00000000-0000-0000-0000-000000000001")

    first = await first_registry.open(
        correlation_keys=["resource:foo"],
        severity=IncidentSeverity.SEV2,
        member_event_ids=[event_id],
        actor_oid="oid-detector-a",
    )
    second = await second_registry.open(
        correlation_keys=["resource:foo"],
        severity=IncidentSeverity.SEV2,
        member_event_ids=[event_id],
        actor_oid="oid-detector-b",
    )

    assert first.incident_id == second.incident_id
    transitions = list(state_store.incident_transitions)
    assert len(transitions) == 1
    assert transitions[0]["idempotency_key"] == f"{first.incident_id}::open"


async def test_conflicting_cross_registry_open_has_one_canonical_winner(
    state_store: InMemoryStateStore,
) -> None:
    first_registry = IncidentRegistry(state_store=state_store)
    second_registry = IncidentRegistry(state_store=state_store)
    event_id = UUID("00000000-0000-0000-0000-000000000001")

    results = await asyncio.gather(
        first_registry.open(
            correlation_keys=["resource:foo"],
            severity=IncidentSeverity.SEV1,
            member_event_ids=[event_id],
            actor_oid="Heimdall",
        ),
        second_registry.open(
            correlation_keys=["resource:foo"],
            severity=IncidentSeverity.SEV4,
            member_event_ids=[event_id],
            actor_oid="Heimdall",
        ),
        return_exceptions=True,
    )

    assert sum(isinstance(result, Incident) for result in results) == 1
    assert sum(isinstance(result, IncidentWriteConflictError) for result in results) == 1
    restored = IncidentRegistry(state_store=InMemoryStateStore())
    restored.rehydrate(await state_store.read_incident_transitions())
    assert len(restored.snapshot()) == 1
    canonical = next(iter(restored.snapshot().values()))
    assert first_registry.get(canonical.incident_id) == canonical
    assert second_registry.get(canonical.incident_id) == canonical


async def test_cross_registry_open_with_different_initial_assignee_conflicts(
    state_store: InMemoryStateStore,
) -> None:
    first = IncidentRegistry(state_store=state_store)
    second = IncidentRegistry(state_store=state_store)
    await first.open(
        correlation_keys=["resource:foo"],
        severity=IncidentSeverity.SEV2,
        member_event_ids=[UUID("00000000-0000-0000-0000-000000000001")],
        actor_oid="Heimdall",
        assignee_oid="operator-a",
    )

    with pytest.raises(IncidentWriteConflictError, match="conflict"):
        await second.open(
            correlation_keys=["resource:foo"],
            severity=IncidentSeverity.SEV2,
            member_event_ids=[UUID("00000000-0000-0000-0000-000000000001")],
            actor_oid="Heimdall",
            assignee_oid="operator-b",
        )


async def test_conflicting_cross_registry_transitions_have_one_winner(
    state_store: InMemoryStateStore,
) -> None:
    first_registry = IncidentRegistry(state_store=state_store)
    incident = await first_registry.open(
        correlation_keys=["resource:foo"],
        severity=IncidentSeverity.SEV2,
        member_event_ids=[UUID("00000000-0000-0000-0000-000000000001")],
        actor_oid="Heimdall",
    )
    second_registry = IncidentRegistry(state_store=state_store)
    second_registry.rehydrate(await state_store.read_incident_transitions())

    results = await asyncio.gather(
        first_registry.transition(
            incident_id=incident.incident_id,
            to_state=IncidentState.TRIAGING,
            actor_oid="operator-a",
        ),
        second_registry.transition(
            incident_id=incident.incident_id,
            to_state=IncidentState.MITIGATED,
            actor_oid="operator-b",
        ),
        return_exceptions=True,
    )

    assert sum(isinstance(result, Incident) for result in results) == 1
    assert sum(isinstance(result, IncidentWriteConflictError) for result in results) == 1
    restored = IncidentRegistry(state_store=InMemoryStateStore())
    restored.rehydrate(await state_store.read_incident_transitions())
    assert len(restored.snapshot()) == 1
    canonical = restored.get(incident.incident_id)
    assert first_registry.get(incident.incident_id) == canonical
    assert second_registry.get(incident.incident_id) == canonical


async def test_open_audit_failure_does_not_leave_phantom_incident() -> None:
    class FailingStateStore(InMemoryStateStore):
        async def append_incident_transition(self, entry: Mapping[str, object]) -> None:  # noqa: ARG002
            raise RuntimeError("injected audit failure")

    registry = IncidentRegistry(state_store=FailingStateStore())

    with pytest.raises(RuntimeError, match="injected audit failure"):
        await registry.open(
            correlation_keys=["resource:foo"],
            severity=IncidentSeverity.SEV2,
            member_event_ids=[UUID("00000000-0000-0000-0000-000000000001")],
            actor_oid="Heimdall",
        )

    assert registry.snapshot() == {}


async def test_bounded_audit_trim_does_not_lose_lifecycle_source() -> None:
    store = InMemoryStateStore(max_audit_entries=2)
    registry = IncidentRegistry(state_store=store)
    incident = await registry.open(
        correlation_keys=["resource:foo"],
        severity=IncidentSeverity.SEV2,
        member_event_ids=[UUID("00000000-0000-0000-0000-000000000001")],
        actor_oid="Heimdall",
    )
    for index in range(5):
        await store.append_audit_entry({"kind": "noise", "index": index})

    transitioned = await registry.transition(
        incident_id=incident.incident_id,
        to_state=IncidentState.TRIAGING,
        actor_oid="operator@example.com",
    )
    restored = IncidentRegistry(state_store=InMemoryStateStore())
    restored.rehydrate(await store.read_incident_transitions())

    assert transitioned.state is IncidentState.TRIAGING
    assert restored.get(incident.incident_id).state is IncidentState.TRIAGING  # type: ignore[union-attr]


async def test_transition_walks_full_lifecycle(
    registry: IncidentRegistry, state_store: InMemoryStateStore
) -> None:
    inc = await registry.open(
        correlation_keys=["resource:foo"],
        severity=IncidentSeverity.SEV2,
        member_event_ids=[UUID("00000000-0000-0000-0000-000000000001")],
        actor_oid="oid-detector",
    )
    inc = await registry.transition(
        incident_id=inc.incident_id,
        to_state=IncidentState.TRIAGING,
        actor_oid="oid-oncall",
    )
    assert inc.state is IncidentState.TRIAGING
    inc = await registry.transition(
        incident_id=inc.incident_id,
        to_state=IncidentState.MITIGATED,
        actor_oid="oid-oncall",
        reason="rolled back deploy",
    )
    assert inc.state is IncidentState.MITIGATED
    assert inc.mitigated_at is not None
    assert inc.mitigation_summary == "rolled back deploy"
    inc = await registry.transition(
        incident_id=inc.incident_id,
        to_state=IncidentState.RESOLVED,
        actor_oid="oid-oncall",
    )
    assert inc.resolved_at is not None
    inc = await registry.transition(
        incident_id=inc.incident_id,
        to_state=IncidentState.CLOSED,
        actor_oid="oid-approver",
    )
    assert inc.closed_at is not None
    assert state_store.verify_chain()  # every transition audited without breaking the chain


async def test_transition_is_idempotent_same_state(registry: IncidentRegistry) -> None:
    inc = await registry.open(
        correlation_keys=["resource:foo"],
        severity=IncidentSeverity.SEV3,
        member_event_ids=[UUID("00000000-0000-0000-0000-000000000001")],
        actor_oid="oid-detector",
    )
    # Re-emitting the same terminal state is a no-op, NOT an error.
    same = await registry.transition(
        incident_id=inc.incident_id,
        to_state=IncidentState.OPEN,
        actor_oid="oid-detector",
    )
    assert same.state is inc.state
    # The registry returns the current in-memory record (same identity)
    # so callers can chain without re-fetching.
    assert same is inc


async def test_illegal_transition_raises_and_leaves_audit_unchanged(
    registry: IncidentRegistry, state_store: InMemoryStateStore
) -> None:
    inc = await registry.open(
        correlation_keys=["resource:foo"],
        severity=IncidentSeverity.SEV3,
        member_event_ids=[UUID("00000000-0000-0000-0000-000000000001")],
        actor_oid="oid-detector",
    )
    audit_before = len(list(state_store.incident_transitions))
    with pytest.raises(IncidentTransitionError):
        await registry.transition(
            incident_id=inc.incident_id,
            to_state=IncidentState.RESOLVED,  # illegal from OPEN
            actor_oid="oid-oncall",
        )
    # Fail-closed: no audit row written for a rejected transition.
    assert len(list(state_store.incident_transitions)) == audit_before


async def test_transition_dedupes_on_idempotency_key(
    registry: IncidentRegistry, state_store: InMemoryStateStore
) -> None:
    inc = await registry.open(
        correlation_keys=["resource:foo"],
        severity=IncidentSeverity.SEV3,
        member_event_ids=[UUID("00000000-0000-0000-0000-000000000001")],
        actor_oid="oid-detector",
    )
    at = datetime.now(tz=UTC)
    _ = await registry.transition(
        incident_id=inc.incident_id,
        to_state=IncidentState.TRIAGING,
        actor_oid="oid-oncall",
        at=at,
    )
    # Simulate a re-delivery: same (incident, target, actor) with the
    # same timestamp yields the same idempotency key → InMemoryStateStore
    # silently no-ops the append.
    _ = await registry.transition(
        incident_id=inc.incident_id,
        to_state=IncidentState.MITIGATED,
        actor_oid="oid-oncall",
        at=at,
    )
    # Re-delivery of the MITIGATED transition MUST not create a duplicate.
    _ = await registry.transition(
        incident_id=inc.incident_id,
        to_state=IncidentState.MITIGATED,
        actor_oid="oid-oncall",
        at=at + timedelta(seconds=1),  # different timestamp, same intent
    )
    transitions = list(state_store.incident_transitions)
    # open + triaging + mitigated (deduped) = 3
    assert len(transitions) == 3
    kinds = [t["to_state"] if "to_state" in t else "open" for t in transitions]
    assert kinds == ["open", "triaging", "mitigated"]


async def test_transition_reopen_cycle_by_same_actor_audits_every_edge(
    registry: IncidentRegistry, state_store: InMemoryStateStore
) -> None:
    # A legal reopen cycle repeats the resolved->triaging edge. Because the
    # idempotency key includes the transition timestamp, the second reopen by
    # the SAME actor does not collide with the first and get silently dropped -
    # which would leave in-memory state at triaging while audit-replay
    # reconstructed only up to resolved (divergence).
    inc = await registry.open(
        correlation_keys=["resource:foo"],
        severity=IncidentSeverity.SEV2,
        member_event_ids=[UUID("00000000-0000-0000-0000-000000000001")],
        actor_oid="oid-detector",
    )
    base = datetime.now(tz=UTC)
    edges = [
        (IncidentState.TRIAGING, 0),
        (IncidentState.RESOLVED, 1),
        (IncidentState.TRIAGING, 2),  # reopen 1
        (IncidentState.RESOLVED, 3),
        (IncidentState.TRIAGING, 4),  # reopen 2 - same edge as reopen 1
    ]
    for target, secs in edges:
        inc = await registry.transition(
            incident_id=inc.incident_id,
            to_state=target,
            actor_oid="oid-oncall",  # same actor throughout
            at=base + timedelta(seconds=secs),
        )
    assert inc.state is IncidentState.TRIAGING
    transitions = list(state_store.incident_transitions)
    # open + 5 transitions, none dropped by an idempotency-key collision.
    assert len(transitions) == 6
    assert state_store.verify_chain()


async def test_reopen_can_adjust_severity_and_replay_it(
    registry: IncidentRegistry,
    state_store: InMemoryStateStore,
) -> None:
    incident = await registry.open(
        correlation_keys=["resource:foo"],
        severity=IncidentSeverity.SEV3,
        member_event_ids=[UUID("00000000-0000-0000-0000-000000000001")],
        actor_oid="Heimdall",
    )
    incident = await registry.transition(
        incident_id=incident.incident_id,
        to_state=IncidentState.TRIAGING,
        actor_oid="operator@example.com",
    )
    incident = await registry.transition(
        incident_id=incident.incident_id,
        to_state=IncidentState.RESOLVED,
        actor_oid="operator@example.com",
    )
    reopened = await registry.transition(
        incident_id=incident.incident_id,
        to_state=IncidentState.TRIAGING,
        actor_oid="operator@example.com",
        severity=IncidentSeverity.SEV1,
        reason="customer impact recurred",
    )

    restored = IncidentRegistry(state_store=InMemoryStateStore())
    restored.rehydrate(await state_store.read_incident_transitions())

    assert reopened.severity is IncidentSeverity.SEV1
    assert restored.get(incident.incident_id).severity is IncidentSeverity.SEV1  # type: ignore[union-attr]


async def test_severity_change_outside_reopen_is_rejected(
    registry: IncidentRegistry,
) -> None:
    incident = await registry.open(
        correlation_keys=["resource:foo"],
        severity=IncidentSeverity.SEV3,
        member_event_ids=[UUID("00000000-0000-0000-0000-000000000001")],
        actor_oid="Heimdall",
    )

    with pytest.raises(ValueError, match="only on resolved -> triaging"):
        await registry.transition(
            incident_id=incident.incident_id,
            to_state=IncidentState.TRIAGING,
            actor_oid="operator@example.com",
            severity=IncidentSeverity.SEV1,
        )


async def test_assignment_is_idempotent_and_survives_replay(
    registry: IncidentRegistry,
    state_store: InMemoryStateStore,
) -> None:
    incident = await registry.open(
        correlation_keys=["resource:foo"],
        severity=IncidentSeverity.SEV2,
        member_event_ids=[UUID("00000000-0000-0000-0000-000000000001")],
        actor_oid="Heimdall",
    )
    assigned = await registry.assign(
        incident_id=incident.incident_id,
        assignee_oid="operator-oid",
        actor_oid="dispatcher-oid",
        at=datetime(2026, 7, 15, 0, 5, tzinfo=UTC),
    )
    replayed = await registry.assign(
        incident_id=incident.incident_id,
        assignee_oid="operator-oid",
        actor_oid="dispatcher-oid",
        at=datetime(2026, 7, 15, 0, 6, tzinfo=UTC),
    )
    restored = IncidentRegistry(state_store=InMemoryStateStore())
    restored.rehydrate(await state_store.read_incident_transitions())

    assert assigned.assignee_oid == "operator-oid"
    assert replayed == assigned
    assert restored.get(incident.incident_id).assignee_oid == "operator-oid"  # type: ignore[union-attr]
    assert [entry["kind"] for entry in state_store.incident_transitions] == [
        "incident.open",
        "incident.assigned",
    ]


async def test_initial_assignee_survives_replay(state_store: InMemoryStateStore) -> None:
    registry = IncidentRegistry(state_store=state_store)
    incident = await registry.open(
        correlation_keys=["resource:foo"],
        severity=IncidentSeverity.SEV2,
        member_event_ids=[UUID("00000000-0000-0000-0000-000000000001")],
        actor_oid="Heimdall",
        assignee_oid="operator-oid",
    )
    restored = IncidentRegistry(state_store=InMemoryStateStore())

    restored.rehydrate(await state_store.read_incident_transitions())

    assert restored.get(incident.incident_id).assignee_oid == "operator-oid"  # type: ignore[union-attr]


async def test_external_ticket_link_is_idempotent_and_projects_to_audit(
    registry: IncidentRegistry,
    state_store: InMemoryStateStore,
) -> None:
    incident = await registry.open(
        correlation_keys=["resource:foo"],
        severity=IncidentSeverity.SEV2,
        member_event_ids=[UUID("00000000-0000-0000-0000-000000000001")],
        actor_oid="Heimdall",
    )

    first = await registry.link_ticket(
        incident_id=incident.incident_id,
        provider="GitHub",
        ticket_id="ISSUE-42",
        ticket_url="https://example.com/issues/42",
        actor_oid="Saga",
        at=datetime(2026, 7, 15, 0, 5, tzinfo=UTC),
    )
    await registry.link_ticket(
        incident_id=incident.incident_id,
        provider="github",
        ticket_id="ISSUE-42",
        ticket_url="https://example.com/issues/42",
        actor_oid="Saga",
        at=datetime(2026, 7, 15, 0, 6, tzinfo=UTC),
    )
    restored = IncidentRegistry(state_store=InMemoryStateStore())
    restored.rehydrate(await state_store.read_incident_transitions())

    assert first.provider == "github"
    assert restored.get(incident.incident_id) is not None
    assert [entry["kind"] for entry in state_store.incident_transitions] == [
        "incident.open",
        "incident.ticket",
    ]


async def test_rehydrate_restores_full_lifecycle(state_store: InMemoryStateStore) -> None:
    source = IncidentRegistry(state_store=state_store)
    incident = await source.open(
        correlation_keys=["resource:foo"],
        severity=IncidentSeverity.SEV2,
        member_event_ids=[UUID("00000000-0000-0000-0000-000000000001")],
        actor_oid="Heimdall",
        opened_at=datetime(2026, 7, 15, tzinfo=UTC),
    )
    incident = await source.transition(
        incident_id=incident.incident_id,
        to_state=IncidentState.TRIAGING,
        actor_oid="operator@example.com",
        reason="acknowledged",
        at=datetime(2026, 7, 15, 0, 5, tzinfo=UTC),
    )
    restored = IncidentRegistry(state_store=InMemoryStateStore())

    count = restored.rehydrate(entry["entry"] for entry in state_store.audit_entries)

    assert count == 1
    assert restored.get(incident.incident_id) == incident


async def test_rehydrate_accepts_legacy_transition_without_severity(
    state_store: InMemoryStateStore,
) -> None:
    source = IncidentRegistry(state_store=state_store)
    incident = await source.open(
        correlation_keys=["resource:foo"],
        severity=IncidentSeverity.SEV2,
        member_event_ids=[UUID("00000000-0000-0000-0000-000000000001")],
        actor_oid="Heimdall",
    )
    await source.transition(
        incident_id=incident.incident_id,
        to_state=IncidentState.TRIAGING,
        actor_oid="operator@example.com",
    )
    entries = [dict(entry) for entry in await state_store.read_incident_transitions()]
    entries[-1].pop("severity")
    entries[-1].pop("from_severity")
    restored = IncidentRegistry(state_store=InMemoryStateStore())

    restored.rehydrate(entries)

    assert restored.get(incident.incident_id).severity is IncidentSeverity.SEV2  # type: ignore[union-attr]


async def test_rehydrate_failure_keeps_existing_snapshot(
    state_store: InMemoryStateStore,
) -> None:
    registry = IncidentRegistry(state_store=state_store)
    existing = await registry.open(
        correlation_keys=["resource:existing"],
        severity=IncidentSeverity.SEV3,
        member_event_ids=[UUID("00000000-0000-0000-0000-000000000001")],
        actor_oid="Heimdall",
        opened_at=datetime(2026, 7, 15, tzinfo=UTC),
    )
    malformed = {
        "kind": "incident.open",
        "incident_id": str(UUID("00000000-0000-0000-0000-000000000001")),
        "state": "open",
        "severity": "sev2",
        "opened_at": "2026-07-15T00:00:00+00:00",
        "correlation_keys": ["resource:tampered"],
        "member_event_ids": ["00000000-0000-0000-0000-000000000001"],
    }

    with pytest.raises(IncidentReplayError, match="incident_id does not match"):
        registry.rehydrate([malformed])

    assert tuple(registry.snapshot()) == (existing.incident_id,)


async def test_transition_on_unknown_incident_raises(registry: IncidentRegistry) -> None:
    with pytest.raises(KeyError):
        await registry.transition(
            incident_id=UUID("00000000-0000-0000-0000-000000000099"),
            to_state=IncidentState.TRIAGING,
            actor_oid="oid-oncall",
        )
