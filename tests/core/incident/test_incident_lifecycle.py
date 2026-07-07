"""Incident lifecycle - state-machine + registry + audit persistence."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from fdai.core.incident import (
    IncidentRegistry,
    IncidentStateMachine,
    IncidentTransitionError,
    incident_id_for,
)
from fdai.shared.contracts.models import IncidentSeverity, IncidentState
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
    # Only one open transition audited (idempotent).
    assert len(list(state_store.incident_transitions)) == 1


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


async def test_transition_on_unknown_incident_raises(registry: IncidentRegistry) -> None:
    with pytest.raises(KeyError):
        await registry.transition(
            incident_id=UUID("00000000-0000-0000-0000-000000000099"),
            to_state=IncidentState.TRIAGING,
            actor_oid="oid-oncall",
        )
