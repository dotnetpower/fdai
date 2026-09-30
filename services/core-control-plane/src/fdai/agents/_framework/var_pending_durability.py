"""Durable pending-ticket helpers for Var."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Any

from fdai.agents._framework.var_decisions import PendingHilTicket, PendingShadowReview
from fdai.agents._framework.var_ticket_identity import (
    APPROVAL_STATE_PREFIX,
    ticket_from_identity,
    ticket_identity,
)
from fdai.shared.providers.state_store import StateStore

PENDING_TICKET_PREFIX = f"{APPROVAL_STATE_PREFIX}/pending-ticket/"
SHADOW_REVIEW_PREFIX = f"{APPROVAL_STATE_PREFIX}/shadow-review/"


async def checkpoint_pending_ticket(store: StateStore | None, ticket: PendingHilTicket) -> None:
    if store is None:
        return
    record = {
        "schema_version": "1.0.0",
        "revision": 1,
        "status": "pending",
        "correlation_id": ticket.correlation_id,
        "ticket_identity": ticket_identity(ticket),
    }
    created = await store.write_state_if_absent(pending_ticket_key(ticket.correlation_id), record)
    if created:
        return
    stored = await store.read_state(pending_ticket_key(ticket.correlation_id))
    if not isinstance(stored, Mapping):
        raise RuntimeError("durable pending HIL ticket disappeared")
    if stored.get("status") == "closed":
        return
    if stored.get("ticket_identity") != record["ticket_identity"]:
        raise RuntimeError("pending HIL ticket collided with a different identity")


async def load_pending_ticket(
    store: StateStore | None,
    correlation_id: str,
) -> PendingHilTicket | None:
    if store is None:
        return None
    stored = await store.read_state(pending_ticket_key(correlation_id))
    if stored is None or stored.get("status") != "pending":
        return None
    identity = stored.get("ticket_identity")
    if not isinstance(identity, Mapping):
        raise RuntimeError("durable pending HIL ticket is malformed")
    return ticket_from_identity(identity)


async def mark_pending_ticket_closed_by_identity(
    store: StateStore | None,
    correlation_id: str,
    action_run_identity: str | None,
) -> None:
    if store is None:
        return
    key = pending_ticket_key(correlation_id)
    for _attempt in range(16):
        stored = await store.read_state(key)
        if stored is None or stored.get("status") == "closed":
            return
        identity = stored.get("ticket_identity")
        if not isinstance(identity, Mapping):
            raise RuntimeError("durable pending HIL ticket is malformed")
        if identity.get("action_run_identity") != action_run_identity:
            raise RuntimeError("pending HIL ticket identity mismatch on close")
        revision = int(stored.get("revision", 1))
        if await store.compare_and_set_state(
            key,
            {**dict(stored), "status": "closed", "revision": revision + 1},
            expected_revision=revision,
        ):
            return
    raise RuntimeError("pending HIL ticket close CAS retry limit exceeded")


async def checkpoint_shadow_review(store: StateStore | None, review: PendingShadowReview) -> None:
    if store is None:
        return
    record = {
        "schema_version": "1.0.0",
        "revision": 1,
        "status": "pending",
        "correlation_id": review.correlation_id,
        "action_type": review.action_type,
        "observed_at": review.observed_at,
        "policy_escape": review.policy_escape,
        "initiator_principal": review.initiator_principal,
    }
    key = shadow_review_key(review.correlation_id)
    if await store.write_state_if_absent(key, record):
        return
    stored = await store.read_state(key)
    if not isinstance(stored, Mapping):
        raise RuntimeError("durable pending shadow review disappeared")
    if stored.get("status") == "closed":
        return
    comparable = {k: stored.get(k) for k in record if k != "revision"}
    expected = {k: v for k, v in record.items() if k != "revision"}
    if comparable != expected:
        raise RuntimeError("pending shadow review collided with a different identity")


async def mark_shadow_review_closed(store: StateStore | None, correlation_id: str) -> None:
    if store is None:
        return
    key = shadow_review_key(correlation_id)
    for _attempt in range(16):
        stored = await store.read_state(key)
        if stored is None or stored.get("status") == "closed":
            return
        revision = int(stored.get("revision", 1))
        if await store.compare_and_set_state(
            key,
            {**dict(stored), "status": "closed", "revision": revision + 1},
            expected_revision=revision,
        ):
            return
    raise RuntimeError("pending shadow review close CAS retry limit exceeded")


def durable_approval_evidence_available(store: StateStore | None) -> bool:
    state = getattr(store, "_state", None)
    if not isinstance(state, dict):
        return False
    prefix = f"{APPROVAL_STATE_PREFIX}/"
    return any(
        key.startswith(prefix)
        and isinstance(value, Mapping)
        and value.get("status", value.get("publication_status")) in {"pending", "published"}
        for key, value in state.items()
    )


def shadow_review_from_state(stored: Mapping[str, Any]) -> PendingShadowReview:
    if (
        stored.get("schema_version") != "1.0.0"
        or stored.get("status") != "pending"
        or not isinstance(stored.get("correlation_id"), str)
        or not stored["correlation_id"]
        or not isinstance(stored.get("action_type"), str)
        or not stored["action_type"]
        or not isinstance(stored.get("observed_at"), str)
        or not stored["observed_at"]
        or not isinstance(stored.get("policy_escape"), bool)
        or (
            stored.get("initiator_principal") is not None
            and not isinstance(stored.get("initiator_principal"), str)
        )
    ):
        raise RuntimeError("durable pending shadow review is malformed")
    return PendingShadowReview(
        correlation_id=str(stored["correlation_id"]),
        action_type=str(stored["action_type"]),
        observed_at=str(stored["observed_at"]),
        policy_escape=bool(stored["policy_escape"]),
        initiator_principal=(
            str(stored["initiator_principal"])
            if stored.get("initiator_principal") is not None
            else None
        ),
    )


def pending_ticket_key(correlation_id: str) -> str:
    return f"{PENDING_TICKET_PREFIX}{_digest(correlation_id)}"


def shadow_review_key(correlation_id: str) -> str:
    return f"{SHADOW_REVIEW_PREFIX}{_digest(correlation_id)}"


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


__all__ = [
    "PENDING_TICKET_PREFIX",
    "SHADOW_REVIEW_PREFIX",
    "checkpoint_pending_ticket",
    "checkpoint_shadow_review",
    "durable_approval_evidence_available",
    "load_pending_ticket",
    "mark_pending_ticket_closed_by_identity",
    "mark_shadow_review_closed",
    "shadow_review_from_state",
]
