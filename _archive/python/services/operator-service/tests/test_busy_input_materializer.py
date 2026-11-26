"""Focused tests for the Operator API busy-input materializer."""

from __future__ import annotations

import pytest
from fdai_operator_service.busy_input_materializer import (
    MAX_QUEUED_BUSY_INPUTS,
    BusyInputCapacityError,
    BusyInputOperatorMaterializer,
)
from fdai_operator_service.families.conversation.contracts import ConversationBoundaryError


def test_busy_input_materializer_enforces_principal_scope_and_404_equivalence() -> None:
    mat = BusyInputOperatorMaterializer()
    mat.ensure_session(
        session_id="sess-1",
        owner_principal_id="owner-a",
        mode="steer",
        active_turn_id="turn-1",
    )

    projected = mat.inspect(session_id="sess-1", principal_id="owner-a")
    assert projected["mode"] == "steer"
    assert projected["active_turn_id"] == "turn-1"

    # Foreign principal receives the exact same 404 as a non-existent session
    with pytest.raises(ConversationBoundaryError) as foreign_exc:
        mat.inspect(session_id="sess-1", principal_id="owner-b")
    with pytest.raises(ConversationBoundaryError) as missing_exc:
        mat.inspect(session_id="sess-missing", principal_id="owner-b")
    assert foreign_exc.value.status_code == 404
    assert missing_exc.value.status_code == 404
    assert foreign_exc.value.code == missing_exc.value.code == "session_not_found"


def test_busy_input_materializer_submit_idempotency_and_revision_conflicts() -> None:
    mat = BusyInputOperatorMaterializer()
    mat.ensure_session(
        session_id="sess-1",
        owner_principal_id="owner-a",
        mode="steer",
        active_turn_id="turn-1",
    )

    first = mat.submit(
        session_id="sess-1",
        principal_id="owner-a",
        payload={
            "input_id": "in-1",
            "idempotency_key": "idem-1",
            "content": "focus on koreacentral",
            "kind": "prose",
        },
    )
    assert first["duplicate"] is False
    assert first["submitted"]["disposition"] == "steered"

    replay = mat.submit(
        session_id="sess-1",
        principal_id="owner-a",
        payload={
            "input_id": "in-1",
            "idempotency_key": "idem-1",
            "content": "focus on koreacentral",
            "kind": "prose",
        },
    )
    assert replay["duplicate"] is True

    with pytest.raises(ConversationBoundaryError) as idem_conflict:
        mat.submit(
            session_id="sess-1",
            principal_id="owner-a",
            payload={
                "input_id": "in-1",
                "idempotency_key": "idem-1",
                "content": "different text",
                "kind": "prose",
            },
        )
    assert idem_conflict.value.status_code == 409
    assert idem_conflict.value.code == "busy_input_idempotency_conflict"

    # Stale revision conflict on mode change and cancel_current
    with pytest.raises(ConversationBoundaryError) as rev_conflict:
        mat.set_mode(
            session_id="sess-1",
            principal_id="owner-a",
            mode="interrupt",
            expected_revision=1,
        )
    assert rev_conflict.value.status_code == 409

    mode_changed = mat.set_mode(
        session_id="sess-1",
        principal_id="owner-a",
        mode="interrupt",
        expected_revision=2,
    )
    assert mode_changed["mode"] == "interrupt"
    assert mode_changed["revision"] == 3

    cancelled = mat.cancel_current(
        session_id="sess-1",
        principal_id="owner-a",
        expected_revision=3,
    )
    assert cancelled["cancelled"] is True
    assert cancelled["session"]["active_turn_id"] is None
    assert cancelled["session"]["revision"] == 4


def test_busy_input_rejects_foreign_principal_on_submit_and_read_session_state() -> None:
    mat = BusyInputOperatorMaterializer()
    mat.ensure_session(
        session_id="sess-owned",
        owner_principal_id="owner-a",
        mode="queue",
        active_turn_id="turn-1",
    )

    with pytest.raises(PermissionError) as read_exc:
        mat.read_session_state(session_id="sess-owned", principal_id="owner-b")
    assert getattr(read_exc.value, "status_code", None) == 403

    with pytest.raises(PermissionError) as submit_exc:
        mat.submit_busy_input(
            session_id="sess-owned",
            principal_id="owner-b",
            payload={
                "input_id": "in-foreign",
                "idempotency_key": "idem-foreign",
                "content": "unauthorized steer",
                "kind": "prose",
            },
        )
    assert getattr(submit_exc.value, "status_code", None) == 403


def test_busy_input_enforces_max_queued_capacity_and_emits_state_digest() -> None:
    assert MAX_QUEUED_BUSY_INPUTS == 32
    mat = BusyInputOperatorMaterializer()
    mat.ensure_session(
        session_id="sess-cap",
        owner_principal_id="owner-a",
        mode="queue",
        active_turn_id="turn-1",
    )
    initial_state = mat.read_session_state(session_id="sess-cap", principal_id="owner-a")
    initial_digest = str(initial_state["state_digest"])
    assert initial_digest.startswith("sha256:") and len(initial_digest) == 71

    for idx in range(MAX_QUEUED_BUSY_INPUTS):
        res = mat.submit(
            session_id="sess-cap",
            principal_id="owner-a",
            payload={
                "input_id": f"in-{idx}",
                "idempotency_key": f"idem-{idx}",
                "content": f"queued item {idx}",
                "kind": "prose",
            },
        )
        assert str(res["session"]["state_digest"]).startswith("sha256:")

    with pytest.raises(BusyInputCapacityError) as cap_exc:
        mat.submit(
            session_id="sess-cap",
            principal_id="owner-a",
            payload={
                "input_id": "in-overflow",
                "idempotency_key": "idem-overflow",
                "content": "overflow item",
                "kind": "prose",
            },
        )
    assert cap_exc.value.status_code == 429
    assert isinstance(cap_exc.value, ValueError)
