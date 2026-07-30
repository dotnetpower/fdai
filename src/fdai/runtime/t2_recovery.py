"""Durable T2 proposer recovery observations and Huginn ingress projection."""

from __future__ import annotations

import hashlib
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from fdai.core.tiers.t2_reasoning import T2AttemptReceipt, T2RecoveryObserver
from fdai.shared.providers.state_store import StateStore

T2RecoveryIngress = Callable[[dict[str, Any]], Awaitable[object]]
_RECEIPT_PREFIX = "t2-recovery:receipt:"


class DurableT2RecoveryObserver(T2RecoveryObserver):
    """Persist sanitized receipts before forwarding one raw signal to Huginn."""

    __slots__ = ("_ingress", "_store")

    def __init__(self, *, store: StateStore, ingress: T2RecoveryIngress) -> None:
        self._store = store
        self._ingress = ingress

    async def observe(self, receipt: T2AttemptReceipt) -> None:
        projection = receipt.to_dict()
        receipt_id = _receipt_id(projection)
        state_key = f"{_RECEIPT_PREFIX}{receipt_id}"
        state = {**projection, "receipt_id": receipt_id, "forwarded": False, "revision": 1}
        audit = {
            "event_id": receipt.event_id,
            "correlation_id": receipt.correlation_id,
            "idempotency_key": receipt_id,
            "actor": "fdai.runtime.t2_recovery",
            "producer_principal": "Huginn",
            "action_kind": "t2.proposer.attempt.observed",
            "mode": "shadow",
            "stage": "t2_recovery_observation",
            "receipt_id": receipt_id,
            "route_ref": receipt.route_ref,
            "attempt": receipt.attempt,
            "status": receipt.status,
            "failure_class": (
                receipt.failure_class.value if receipt.failure_class is not None else None
            ),
            "terminal": receipt.terminal,
            "recovered": receipt.recovered,
            "recorded_at": receipt.observed_at,
        }
        created = await self._store.write_state_with_audit_if_absent(state_key, state, audit)
        if not created:
            return
        await self._ingress(_raw_event(receipt, receipt_id=receipt_id))
        await self._store.compare_and_set_state_with_audit(
            state_key,
            {**state, "forwarded": True, "revision": 2},
            expected_revision=1,
            audit_entry={
                **audit,
                "idempotency_key": f"{receipt_id}:forwarded",
                "action_kind": "t2.proposer.attempt.forwarded",
            },
        )


def _receipt_id(projection: Mapping[str, object]) -> str:
    identity = "\0".join(
        str(projection.get(field) or "") for field in ("event_id", "route_ref", "attempt", "status")
    )
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def _raw_event(receipt: T2AttemptReceipt, *, receipt_id: str) -> dict[str, Any]:
    recovered = receipt.status == "succeeded" and receipt.recovered
    event_type = (
        "control_plane.t2_proposer_recovered" if recovered else "control_plane.t2_proposer_attempt"
    )
    severity = "info" if recovered else "high" if receipt.terminal else "medium"
    return {
        "id": f"t2-recovery-{receipt_id}",
        "event_id": f"t2-recovery-{receipt_id}",
        "idempotency_key": f"t2-recovery-{receipt_id}",
        "correlation_id": receipt.correlation_id,
        "incident_correlation": "correlate" if receipt.terminal and not recovered else "none",
        "source": "fdai.t2-recovery",
        "resource_id": "control-plane:t2-proposer",
        "resource_type": "llm-endpoint",
        "event_type": event_type,
        "severity": severity,
        "attributes": {
            "route_ref": receipt.route_ref,
            "attempt": receipt.attempt,
            "candidate_count": receipt.candidate_count,
            "status": receipt.status,
            "failure_class": (
                receipt.failure_class.value if receipt.failure_class is not None else None
            ),
            "retryable": receipt.retryable,
            "terminal": receipt.terminal,
            "recovered": receipt.recovered,
        },
    }


def bind_t2_recovery_observer(
    *,
    proposer: object,
    store: StateStore,
    ingress: T2RecoveryIngress,
) -> DurableT2RecoveryObserver | None:
    """Bind recovery when the configured proposer supports runtime observation."""

    bind = getattr(proposer, "bind_observer", None)
    if not callable(bind):
        return None
    observer = DurableT2RecoveryObserver(store=store, ingress=ingress)
    bind(observer)
    return observer


__all__ = [
    "DurableT2RecoveryObserver",
    "T2RecoveryIngress",
    "bind_t2_recovery_observer",
]
