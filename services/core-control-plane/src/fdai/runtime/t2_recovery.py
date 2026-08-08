"""Durable T2 proposer recovery observations and Huginn ingress projection."""

from __future__ import annotations

import asyncio
import hashlib
import logging
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any, Protocol

from fdai.core.tiers.t2_reasoning import (
    T2AttemptReceipt,
    T2FailureClass,
    T2RecoveryObserver,
)
from fdai.shared.providers.state_store import StateStore

T2RecoveryIngress = Callable[[dict[str, Any]], Awaitable[object]]
_RECEIPT_PREFIX = "t2-recovery:receipt:"
_LOG = logging.getLogger(__name__)


class T2RecoveryLegacyReader(Protocol):
    async def read_failures(self, *, limit: int) -> Sequence[Mapping[str, object]]: ...


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
        await self._mark_forwarded(state_key, state, audit)

    async def reconcile(self, *, limit: int = 100) -> int:
        """Retry durable receipts whose Huginn forwarding did not commit."""

        records = await self._store.read_states(_RECEIPT_PREFIX, limit=limit)
        reconciled = 0
        for state in records:
            if state.get("forwarded") is True:
                continue
            receipt = _receipt_from_mapping(state)
            receipt_id = str(state.get("receipt_id") or _receipt_id(receipt.to_dict()))
            state_key = f"{_RECEIPT_PREFIX}{receipt_id}"
            await self._ingress(_raw_event(receipt, receipt_id=receipt_id))
            if await self._mark_forwarded(
                state_key,
                dict(state),
                _observation_audit(receipt, receipt_id=receipt_id),
            ):
                reconciled += 1
        return reconciled

    async def backfill(self, entries: Sequence[Mapping[str, object]]) -> int:
        """Materialize legacy T2 proposer errors without replaying providers."""

        backfilled = 0
        for entry in entries:
            reason = str(entry.get("t2_reason") or "")
            if not reason.startswith("t2_proposer_error:"):
                continue
            receipt = T2AttemptReceipt(
                event_id=str(entry.get("event_id") or "legacy-unknown"),
                correlation_id=str(
                    entry.get("correlation_id") or entry.get("event_id") or "legacy-unknown"
                ),
                route_ref="legacy",
                preferred_route_ref="legacy",
                attempt=1,
                candidate_count=1,
                status="failed",
                failure_class=_legacy_failure_class(reason),
                retryable=False,
                terminal=True,
                recovered=False,
                observed_at=str(entry.get("recorded_at") or "1970-01-01T00:00:00+00:00"),
            )
            receipt_id = _receipt_id(receipt.to_dict())
            if await self._store.read_state(f"{_RECEIPT_PREFIX}{receipt_id}") is not None:
                continue
            await self.observe(receipt)
            backfilled += 1
        return backfilled

    async def _mark_forwarded(
        self,
        state_key: str,
        state: Mapping[str, object],
        audit: Mapping[str, object],
    ) -> bool:
        receipt_id = str(state.get("receipt_id") or "")
        revision = _positive_integer(state.get("revision"), field="revision")
        return await self._store.compare_and_set_state_with_audit(
            state_key,
            {**dict(state), "forwarded": True, "revision": revision + 1},
            expected_revision=revision,
            audit_entry={
                **dict(audit),
                "idempotency_key": f"{receipt_id}:forwarded",
                "action_kind": "t2.proposer.attempt.forwarded",
            },
        )


class T2RecoveryMaintenance:
    """Bounded periodic reconciliation and one-way legacy materialization."""

    __slots__ = ("_interval", "_legacy_reader", "_limit", "_observer")

    def __init__(
        self,
        *,
        observer: DurableT2RecoveryObserver,
        legacy_reader: T2RecoveryLegacyReader | None = None,
        interval_seconds: float = 60.0,
        limit: int = 100,
    ) -> None:
        if interval_seconds <= 0 or limit < 1:
            raise ValueError("T2 recovery maintenance bounds MUST be positive")
        self._observer = observer
        self._legacy_reader = legacy_reader
        self._interval = interval_seconds
        self._limit = limit

    async def run_once(self) -> dict[str, int]:
        reconciled = await self._observer.reconcile(limit=self._limit)
        entries = (
            await self._legacy_reader.read_failures(limit=self._limit)
            if self._legacy_reader is not None
            else ()
        )
        backfilled = await self._observer.backfill(tuple(entries))
        return {"reconciled": reconciled, "backfilled": backfilled}

    async def run(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            try:
                await self.run_once()
            except Exception:  # noqa: BLE001 - retain the next bounded retry
                _LOG.exception("t2_recovery_maintenance_failed")
            try:
                await asyncio.wait_for(stop.wait(), timeout=self._interval)
            except TimeoutError:
                continue


def _receipt_id(projection: Mapping[str, object]) -> str:
    identity = "\0".join(
        str(projection.get(field) or "") for field in ("event_id", "route_ref", "attempt", "status")
    )
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def _receipt_from_mapping(value: Mapping[str, object]) -> T2AttemptReceipt:
    failure = value.get("failure_class")
    return T2AttemptReceipt(
        event_id=str(value["event_id"]),
        correlation_id=str(value["correlation_id"]),
        route_ref=str(value["route_ref"]),
        preferred_route_ref=str(value.get("preferred_route_ref") or "primary"),
        attempt=_positive_integer(value.get("attempt"), field="attempt"),
        candidate_count=_positive_integer(value.get("candidate_count"), field="candidate_count"),
        status=str(value["status"]),
        failure_class=T2FailureClass(str(failure)) if failure else None,
        retryable=value.get("retryable") is True,
        terminal=value.get("terminal") is True,
        recovered=value.get("recovered") is True,
        observed_at=str(value["observed_at"]),
    )


def _legacy_failure_class(reason: str) -> T2FailureClass:
    error_type = reason.partition(":")[2]
    if "Timeout" in error_type:
        return T2FailureClass.TIMEOUT
    if error_type in {"ValueError", "TypeError", "JSONDecodeError"}:
        return T2FailureClass.INVALID_RESPONSE
    return T2FailureClass.PROVIDER_ERROR


def _positive_integer(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"T2 recovery {field} MUST be a positive integer")
    return value


def _observation_audit(receipt: T2AttemptReceipt, *, receipt_id: str) -> dict[str, object]:
    return {
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
            "preferred_route_ref": receipt.preferred_route_ref,
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
    "T2RecoveryLegacyReader",
    "T2RecoveryMaintenance",
    "bind_t2_recovery_observer",
]
