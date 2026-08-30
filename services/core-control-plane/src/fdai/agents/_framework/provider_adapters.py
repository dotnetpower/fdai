"""Provider-backed persistence adapters for Pantheon agents."""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import uuid4

from fdai.agents._framework.adapters import AuditEntry, _digest
from fdai.agents.thor import ActionRun, ActionRunState
from fdai.shared.providers.state_store import StateStore

_LOG = logging.getLogger(__name__)
_ACTION_RUN_STATE_RANK = {
    ActionRunState.PROPOSED: 0,
    ActionRunState.VERDICTED: 1,
    ActionRunState.HIL_PENDING: 2,
    ActionRunState.APPROVED: 3,
    ActionRunState.EXECUTING: 4,
    ActionRunState.EXECUTION_UNKNOWN: 5,
    ActionRunState.FAILED: 6,
    ActionRunState.SUCCEEDED: 7,
    ActionRunState.REJECTED: 7,
    ActionRunState.DENY_DROPPED: 7,
    ActionRunState.ROLLBACK_FAILED: 8,
    ActionRunState.ROLLED_BACK: 9,
}

# Distinctive one-key envelope used to round-trip a non-dict value through
# the Mapping-only StateStore contract. Using a reserved sentinel key (not
# a plausible user key like "value") lets ``get`` unwrap unambiguously.
_SCALAR_ENVELOPE_KEY = "__fdai_scalar__"


@dataclass
class StateStoreAuditChainAdapter:
    """Saga's audit chain, backed by ``StateStore.append_audit_entry``.

    The hash-linked chain contract stays identical to the in-memory
    version: ``seq``, ``prev_hash``, and ``entry_hash`` are computed
    the same way and the record is a plain dict handed to the Protocol.

    ``entries`` is a local snapshot cache used to compute the next
    ``prev_hash`` without a round-trip; a fork can override this class
    if the backing store already computes hash chains server-side.
    """

    store: StateStore
    entries: list[AuditEntry]
    durable: bool = True

    def __init__(self, store: StateStore) -> None:
        self.store = store
        self.entries = []

    async def append(
        self,
        *,
        principal: str,
        topic: str,
        correlation_id: str,
        payload: dict[str, Any],
    ) -> AuditEntry:
        seq = len(self.entries)
        prev_hash = self.entries[-1].entry_hash if self.entries else "0" * 64
        payload_digest = _digest(payload)
        entry_hash = _digest(
            {
                "seq": seq,
                "prev_hash": prev_hash,
                "principal": principal,
                "topic": topic,
                "correlation_id": correlation_id,
                "payload_digest": payload_digest,
            }
        )
        entry = AuditEntry(
            seq=seq,
            prev_hash=prev_hash,
            entry_hash=entry_hash,
            principal=principal,
            topic=topic,
            correlation_id=correlation_id,
            payload_digest=payload_digest,
        )
        self.entries.append(entry)
        # Hand the concrete record to the provider; the Protocol only
        # cares about the mapping shape.
        await self.store.append_audit_entry(
            {
                "seq": seq,
                "prev_hash": prev_hash,
                "entry_hash": entry_hash,
                "principal": principal,
                "topic": topic,
                "correlation_id": correlation_id,
                "payload_digest": payload_digest,
                "payload": payload,
            }
        )
        return entry

    def verify(self) -> None:
        """Local chain verification (equivalent to in-memory adapter)."""
        prev = "0" * 64
        for i, entry in enumerate(self.entries):
            if entry.seq != i or entry.prev_hash != prev:
                from fdai.agents._framework.adapters import AuditChainError

                raise AuditChainError(
                    f"chain break at seq {i}: prev={entry.prev_hash!r} expected {prev!r}"
                )
            prev = entry.entry_hash

    def entries_for_correlation(self, correlation_id: str) -> list[AuditEntry]:
        return [e for e in self.entries if e.correlation_id == correlation_id]


@dataclass
class StateStoreKvAdapter:
    """Muninn's context store, backed by ``StateStore.read_state`` /
    ``write_state``. Bucket + key are joined with ``|`` to form the
    Protocol key.
    """

    store: StateStore

    async def get(self, bucket: str, key: str) -> Any | None:
        value = await self.store.read_state(f"{bucket}|{key}")
        # Symmetric unwrap: a scalar written via ``put`` was wrapped in a
        # reserved one-key envelope; return the original scalar so the
        # round-trip is value-preserving (a dict written as-is is returned
        # unchanged because it lacks the sentinel key).
        if isinstance(value, Mapping) and set(value.keys()) == {_SCALAR_ENVELOPE_KEY}:
            return value[_SCALAR_ENVELOPE_KEY]
        return value

    async def put(self, bucket: str, key: str, value: Any) -> None:
        # StateStore expects a Mapping; wrap a non-dict in a reserved
        # one-key envelope so ``get`` can unwrap it back to the original
        # scalar (see :meth:`get`).
        stored: Mapping[str, Any]
        if isinstance(value, Mapping):
            stored = value
        else:
            stored = {_SCALAR_ENVELOPE_KEY: value}
        await self.store.write_state(f"{bucket}|{key}", stored)


@dataclass
class StateStoreActionRunStore:
    """Durable ActionRun, idempotency, and cross-replica resource claims."""

    store: StateStore
    run_prefix: str = "thor:run|"
    resource_claim_prefix: str = "thor:resource-claim|"
    completion_prefix: str = "thor:completion|"
    _max_active_runs: int = 10_000
    owner_id: str = field(default_factory=lambda: uuid4().hex)
    claim_lease_seconds: int = 600

    async def save(self, run: ActionRun) -> None:
        completion = await self.store.read_state(self._completion_key(run.idempotency_key))
        if completion is not None:
            if completion.get("status") == "completed":
                if (
                    completion.get("idempotency_key") != run.idempotency_key
                    or completion.get("resource_id") != run.resource_id
                ):
                    raise RuntimeError("Thor completion marker conflicts with ActionRun")
                return
            if (
                completion.get("status") != "reserved"
                or completion.get("idempotency_key") != run.idempotency_key
                or completion.get("resource_id") != run.resource_id
                or completion.get("correlation_id") != run.correlation_id
                or completion.get("owner_id") != self.owner_id
            ):
                raise RuntimeError("Thor completion marker conflicts with ActionRun")
        key = f"{self.run_prefix}{run.correlation_id}"
        for _ in range(8):
            current = await self.store.read_state(key)
            if current is None:
                if await self.store.write_state_if_absent(
                    key,
                    {**run.to_dict(), "active": "true", "revision": 0},
                ):
                    return
                continue
            if current.get("active") == "false":
                return
            try:
                current_state = ActionRunState(str(current.get("state") or ""))
            except ValueError as exc:
                raise RuntimeError("Thor ActionRun state is invalid") from exc
            current_rank = _ACTION_RUN_STATE_RANK[current_state]
            candidate_rank = _ACTION_RUN_STATE_RANK[run.state]
            lock_retry = (
                current_state is ActionRunState.EXECUTING
                and run.state in {ActionRunState.VERDICTED, ActionRunState.APPROVED}
                and run.outcome == "execution_resource_temporarily_unavailable"
            )
            if current_rank > candidate_rank and not lock_retry:
                return
            if current_rank == candidate_rank:
                candidate = run.to_dict()
                differences = {key for key, value in candidate.items() if current.get(key) != value}
                claim_recovery = (
                    differences == {"resource_claimed"}
                    and current.get("resource_claimed") is False
                    and candidate["resource_claimed"] is True
                )
                if differences and not claim_recovery:
                    raise RuntimeError("Thor ActionRun same-state payload conflicts")
                if not differences:
                    return
            revision = current.get("revision", 0)
            if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
                raise RuntimeError("Thor ActionRun revision is invalid")
            if await self.store.compare_and_set_state_with_audit(
                key,
                {
                    **run.to_dict(),
                    "active": "true",
                    "revision": revision + 1,
                },
                expected_revision=revision,
                audit_entry={
                    "kind": "thor.action-run-save",
                    "correlation_id": run.correlation_id,
                    "revision": revision + 1,
                },
            ):
                return
        raise RuntimeError("Thor ActionRun save exceeded its CAS retry bound")

    async def load_active(self) -> list[ActionRun]:
        runs_by_correlation: dict[str, ActionRun] = {}
        rows, total = await self.store.read_state_page(
            self.run_prefix,
            limit=self._max_active_runs,
            field="active",
            value="true",
        )
        if total > self._max_active_runs:
            raise RuntimeError("Thor active ActionRun count exceeds its recovery bound")
        for raw in rows:
            try:
                payload = dict(raw)
                payload.pop("active", None)
                run = ActionRun.from_dict(payload)
                runs_by_correlation[run.correlation_id] = run
            except (KeyError, ValueError, TypeError):
                # A single corrupt / schema-drifted row MUST NOT abort the
                # whole rehydration (which would leave every in-flight run
                # unrecovered). Skip and log it; the rest still restore.
                _LOG.exception(
                    "action_run_rehydrate_skip_corrupt",
                    extra={"correlation_id": str(raw.get("correlation_id") or "")},
                )
        claims, claim_total = await self.store.read_state_page(
            self.resource_claim_prefix,
            limit=self._max_active_runs,
            field="status",
            value="claimed",
        )
        if claim_total > self._max_active_runs:
            raise RuntimeError("Thor resource claim count exceeds its recovery bound")
        for claim in claims:
            claimed_by = claim.get("owner_id")
            lease_expires_at = _claim_lease_expiry(claim)
            claim_idempotency = str(claim.get("idempotency_key") or "")
            completion = (
                await self.store.read_state(self._completion_key(claim_idempotency))
                if claim_idempotency
                else None
            )
            if isinstance(completion, Mapping) and completion.get("status") == "completed":
                immutable_match = (
                    completion.get("resource_id") == claim.get("resource_id")
                    and completion.get("idempotency_key") == claim_idempotency
                    and completion.get("action_fingerprint") == claim.get("action_fingerprint")
                )
                if not immutable_match:
                    raise RuntimeError("Thor completion marker conflicts with resource claim")
                if claimed_by != self.owner_id and lease_expires_at > datetime.now(tz=UTC):
                    runs_by_correlation.pop(str(claim.get("correlation_id") or ""), None)
                    continue
                revision = claim.get("revision")
                if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
                    raise RuntimeError("Thor resource claim revision is invalid")
                released = {
                    **dict(claim),
                    "revision": revision + 1,
                    "status": "released",
                    "owner_id": self.owner_id,
                }
                claim_key = self._resource_claim_key(str(claim.get("resource_id") or ""))
                await self.store.compare_and_set_state_with_audit(
                    claim_key,
                    released,
                    expected_revision=revision,
                    audit_entry={
                        "kind": "thor.completed-claim-recovery",
                        "correlation_id": str(claim.get("correlation_id") or ""),
                        "revision": revision + 1,
                    },
                )
                runs_by_correlation.pop(str(claim.get("correlation_id") or ""), None)
                continue
            if claimed_by != self.owner_id and lease_expires_at > datetime.now(tz=UTC):
                runs_by_correlation.pop(str(claim.get("correlation_id") or ""), None)
                continue
            if claimed_by != self.owner_id:
                takeover_run_raw = claim.get("run")
                if not isinstance(takeover_run_raw, Mapping):
                    raise RuntimeError("Thor resource claim is missing its recovery ActionRun")
                takeover_run = ActionRun.from_dict(dict(takeover_run_raw))
                if await self._reserve_idempotency(takeover_run) != "acquired":
                    continue
                revision = claim.get("revision")
                if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
                    raise RuntimeError("Thor resource claim revision is invalid")
                claimed = {
                    **dict(claim),
                    "revision": revision + 1,
                    "owner_id": self.owner_id,
                    "lease_expires_at": _lease_expiry(self.claim_lease_seconds),
                }
                claim_key = self._resource_claim_key(str(claim.get("resource_id") or ""))
                if not await self.store.compare_and_set_state_with_audit(
                    claim_key,
                    claimed,
                    expected_revision=revision,
                    audit_entry={
                        "kind": "thor.resource-claim-takeover",
                        "correlation_id": str(claim.get("correlation_id") or ""),
                        "revision": revision + 1,
                    },
                ):
                    continue
                claim = claimed
            raw_run = claim.get("run")
            if not isinstance(raw_run, Mapping):
                raise RuntimeError("Thor resource claim is missing its recovery ActionRun")
            run = ActionRun.from_dict(dict(raw_run))
            run.resource_claimed = True
            existing = runs_by_correlation.get(run.correlation_id)
            if (
                existing is None
                or _ACTION_RUN_STATE_RANK[run.state] >= _ACTION_RUN_STATE_RANK[existing.state]
            ):
                runs_by_correlation[run.correlation_id] = run
            else:
                existing.resource_claimed = True
        return list(runs_by_correlation.values())

    async def delete(self, correlation_id: str) -> None:
        key = f"{self.run_prefix}{correlation_id}"
        current = await self.store.read_state(key)
        resource_id = current.get("resource_id") if isinstance(current, Mapping) else None
        idempotency_key = current.get("idempotency_key") if isinstance(current, Mapping) else None
        if isinstance(resource_id, str) and resource_id:
            if not isinstance(current, Mapping):  # pragma: no cover - resource came from mapping
                raise RuntimeError("Thor terminal ActionRun state is invalid")
            current_run = ActionRun.from_dict(
                {
                    name: value
                    for name, value in current.items()
                    if name not in {"active", "revision"}
                }
            )
            effective_key = (
                idempotency_key
                if isinstance(idempotency_key, str) and idempotency_key
                else correlation_id
            )
            if not await self._complete_idempotency(
                idempotency_key=effective_key,
                resource_id=resource_id,
                correlation_id=correlation_id,
                action_fingerprint=_action_fingerprint(current_run),
            ):
                raise RuntimeError("Thor completion marker conflicts with terminal run")
        for _ in range(8):
            current = await self.store.read_state(key)
            if current is None or current.get("active") == "false":
                return
            revision = current.get("revision", 0)
            if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
                raise RuntimeError("Thor ActionRun revision is invalid")
            if await self.store.compare_and_set_state_with_audit(
                key,
                {
                    "active": "false",
                    "correlation_id": correlation_id,
                    "revision": revision + 1,
                },
                expected_revision=revision,
                audit_entry={
                    "kind": "thor.action-run-delete",
                    "correlation_id": correlation_id,
                    "revision": revision + 1,
                },
            ):
                return
        raise RuntimeError("Thor ActionRun delete exceeded its CAS retry bound")

    async def claim_resource(
        self,
        run: ActionRun,
    ) -> Literal["acquired", "contended", "completed"]:
        """Atomically claim one mutation target across replicas."""

        resource_id = str(run.resource_id or "")
        correlation_id = run.correlation_id
        if not resource_id:
            raise ValueError("Thor resource claim requires a resource id")
        idempotency_status = await self._reserve_idempotency(run)
        if idempotency_status != "acquired":
            return idempotency_status
        key = self._resource_claim_key(resource_id)
        action_fingerprint = _action_fingerprint(run)
        value = {
            "revision": 0,
            "status": "claimed",
            "resource_id": resource_id,
            "correlation_id": correlation_id,
            "idempotency_key": run.idempotency_key,
            "owner_id": self.owner_id,
            "lease_expires_at": _lease_expiry(self.claim_lease_seconds),
            "action_fingerprint": action_fingerprint,
            "run": {**run.to_dict(), "resource_claimed": True},
        }
        if await self.store.write_state_if_absent(key, value):
            run.resource_claimed = True
            return "acquired"
        current = await self.store.read_state(key)
        if not isinstance(current, Mapping):
            return "contended"
        if current.get("status") != "released" or current.get("resource_id") != resource_id:
            return "contended"
        if current.get("correlation_id") == correlation_id:
            return "completed"
        revision = current.get("revision")
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
            return "contended"
        acquired = await self.store.compare_and_set_state_with_audit(
            key,
            {
                **value,
                "revision": revision + 1,
                "run": {**run.to_dict(), "resource_claimed": True},
            },
            expected_revision=revision,
            audit_entry={
                "kind": "thor.resource-claim",
                "resource_id": resource_id,
                "correlation_id": correlation_id,
                "revision": revision + 1,
            },
        )
        if not acquired:
            return "contended"
        run.resource_claimed = True
        return "acquired"

    async def release_resource(self, resource_id: str, correlation_id: str) -> bool:
        """Release only the exact claim held by this ActionRun."""

        key = self._resource_claim_key(resource_id)
        current = await self.store.read_state(key)
        if not isinstance(current, Mapping):
            return False
        revision = current.get("revision")
        if (
            current.get("status") not in {"claimed", "released"}
            or current.get("resource_id") != resource_id
            or current.get("correlation_id") != correlation_id
            or current.get("owner_id") != self.owner_id
        ):
            return False
        idempotency_key = str(
            (current.get("run") or {}).get("idempotency_key")
            if isinstance(current.get("run"), Mapping)
            else correlation_id
        )
        if not await self._complete_idempotency(
            idempotency_key=idempotency_key,
            resource_id=resource_id,
            correlation_id=correlation_id,
            action_fingerprint=str(current.get("action_fingerprint") or ""),
        ):
            return False
        if current.get("status") == "released":
            return True
        if (
            current.get("status") != "claimed"
            or isinstance(revision, bool)
            or not isinstance(revision, int)
            or revision < 0
        ):
            return False
        return await self.store.compare_and_set_state_with_audit(
            key,
            {
                "revision": revision + 1,
                "status": "released",
                "resource_id": resource_id,
                "correlation_id": correlation_id,
                "idempotency_key": current.get("idempotency_key"),
                "owner_id": current.get("owner_id"),
                "lease_expires_at": current.get("lease_expires_at"),
                "action_fingerprint": current.get("action_fingerprint"),
                "run": current.get("run"),
            },
            expected_revision=revision,
            audit_entry={
                "kind": "thor.resource-release",
                "resource_id": resource_id,
                "correlation_id": correlation_id,
                "revision": revision + 1,
            },
        )

    async def refresh_resource_claim(self, run: ActionRun) -> bool:
        """Atomically refresh recovery state while retaining the same claim owner."""

        resource_id = str(run.resource_id or "")
        if not resource_id:
            return False
        reservation_key = self._completion_key(run.idempotency_key)
        reservation = await self.store.read_state(reservation_key)
        reservation_revision = (
            reservation.get("revision") if isinstance(reservation, Mapping) else None
        )
        if (
            not isinstance(reservation, Mapping)
            or reservation.get("status") != "reserved"
            or reservation.get("owner_id") != self.owner_id
            or reservation.get("correlation_id") != run.correlation_id
            or reservation.get("action_fingerprint") != _action_fingerprint(run)
            or isinstance(reservation_revision, bool)
            or not isinstance(reservation_revision, int)
            or reservation_revision < 0
        ):
            return False
        if not await self.store.compare_and_set_state_with_audit(
            reservation_key,
            {
                **dict(reservation),
                "revision": reservation_revision + 1,
                "lease_expires_at": _lease_expiry(self.claim_lease_seconds),
            },
            expected_revision=reservation_revision,
            audit_entry={
                "kind": "thor.idempotency-reservation-refresh",
                "correlation_id": run.correlation_id,
                "revision": reservation_revision + 1,
            },
        ):
            return False
        key = self._resource_claim_key(resource_id)
        current = await self.store.read_state(key)
        if not isinstance(current, Mapping):
            return False
        revision = current.get("revision")
        if (
            current.get("status") != "claimed"
            or current.get("resource_id") != resource_id
            or current.get("correlation_id") != run.correlation_id
            or current.get("owner_id") != self.owner_id
            or isinstance(revision, bool)
            or not isinstance(revision, int)
            or revision < 0
        ):
            return False
        return await self.store.compare_and_set_state_with_audit(
            key,
            {
                **dict(current),
                "revision": revision + 1,
                "run": run.to_dict(),
                "lease_expires_at": _lease_expiry(self.claim_lease_seconds),
            },
            expected_revision=revision,
            audit_entry={
                "kind": "thor.resource-claim-refresh",
                "resource_id": resource_id,
                "correlation_id": run.correlation_id,
                "revision": revision + 1,
            },
        )

    async def validate_resource_claim(self, run: ActionRun) -> bool:
        """Verify owner and mutation fingerprint immediately before executor I/O."""

        resource_id = str(run.resource_id or "")
        if not resource_id:
            return False
        fingerprint = _action_fingerprint(run)
        claim = await self.store.read_state(self._resource_claim_key(resource_id))
        reservation = await self.store.read_state(self._completion_key(run.idempotency_key))
        now = datetime.now(tz=UTC)
        return bool(
            isinstance(claim, Mapping)
            and claim.get("status") == "claimed"
            and claim.get("resource_id") == resource_id
            and claim.get("correlation_id") == run.correlation_id
            and claim.get("idempotency_key") == run.idempotency_key
            and claim.get("owner_id") == self.owner_id
            and claim.get("action_fingerprint") == fingerprint
            and _claim_lease_expiry(claim) > now
            and isinstance(reservation, Mapping)
            and reservation.get("status") == "reserved"
            and reservation.get("correlation_id") == run.correlation_id
            and reservation.get("idempotency_key") == run.idempotency_key
            and reservation.get("owner_id") == self.owner_id
            and reservation.get("action_fingerprint") == fingerprint
            and _claim_lease_expiry(reservation) > now
        )

    def _resource_claim_key(self, resource_id: str) -> str:
        digest = hashlib.sha256(resource_id.encode("utf-8")).hexdigest()
        return f"{self.resource_claim_prefix}{digest}"

    def _completion_key(self, idempotency_key: str) -> str:
        digest = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()
        return f"{self.completion_prefix}{digest}"

    async def _reserve_idempotency(
        self,
        run: ActionRun,
    ) -> Literal["acquired", "contended", "completed"]:
        key = self._completion_key(run.idempotency_key)
        reservation = {
            "revision": 0,
            "status": "reserved",
            "resource_id": run.resource_id,
            "correlation_id": run.correlation_id,
            "idempotency_key": run.idempotency_key,
            "owner_id": self.owner_id,
            "lease_expires_at": _lease_expiry(self.claim_lease_seconds),
            "action_fingerprint": _action_fingerprint(run),
        }
        if await self.store.write_state_if_absent(key, reservation):
            return "acquired"
        current = await self.store.read_state(key)
        if not isinstance(current, Mapping):
            return "contended"
        if current.get("status") == "completed":
            return (
                "completed"
                if current.get("idempotency_key") == run.idempotency_key
                else "contended"
            )
        if (
            current.get("status") != "reserved"
            or current.get("idempotency_key") != run.idempotency_key
            or current.get("action_fingerprint") != reservation["action_fingerprint"]
        ):
            return "contended"
        if (
            current.get("owner_id") == self.owner_id
            and current.get("correlation_id") == run.correlation_id
        ):
            return "acquired"
        if _claim_lease_expiry(current) > datetime.now(tz=UTC):
            return "contended"
        revision = current.get("revision")
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
            return "contended"
        takeover = {**reservation, "revision": revision + 1}
        acquired = await self.store.compare_and_set_state_with_audit(
            key,
            takeover,
            expected_revision=revision,
            audit_entry={
                "kind": "thor.idempotency-reservation-takeover",
                "correlation_id": run.correlation_id,
                "revision": revision + 1,
            },
        )
        return "acquired" if acquired else "contended"

    async def _complete_idempotency(
        self,
        *,
        idempotency_key: str,
        resource_id: str,
        correlation_id: str,
        action_fingerprint: str,
    ) -> bool:
        key = self._completion_key(idempotency_key)
        current = await self.store.read_state(key)
        completion = {
            "status": "completed",
            "resource_id": resource_id,
            "correlation_id": correlation_id,
            "idempotency_key": idempotency_key,
            "owner_id": self.owner_id,
            "action_fingerprint": action_fingerprint,
        }
        if current is None:
            return await self.store.write_state_if_absent(key, completion)
        if current.get("status") == "completed":
            immutable = {
                "status",
                "resource_id",
                "correlation_id",
                "idempotency_key",
                "action_fingerprint",
            }
            return all(current.get(name) == completion[name] for name in immutable)
        revision = current.get("revision")
        if (
            current.get("status") != "reserved"
            or current.get("resource_id") != resource_id
            or current.get("correlation_id") != correlation_id
            or current.get("idempotency_key") != idempotency_key
            or current.get("owner_id") != self.owner_id
            or isinstance(revision, bool)
            or not isinstance(revision, int)
            or revision < 0
        ):
            return False
        return await self.store.compare_and_set_state_with_audit(
            key,
            {**completion, "revision": revision + 1},
            expected_revision=revision,
            audit_entry={
                "kind": "thor.idempotency-completed",
                "correlation_id": correlation_id,
                "revision": revision + 1,
            },
        )


def _action_fingerprint(run: ActionRun) -> str:
    payload = {
        "action_type": run.action_type,
        "resource_id": run.resource_id,
        "idempotency_key": run.idempotency_key,
        "params": run.params,
        "decision_case": run.decision_case,
        "operational_context": run.operational_context,
        "workflow_action": run.workflow_action,
        "kinetic_proposal": run.kinetic_proposal,
    }
    encoded = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _lease_expiry(seconds: int) -> str:
    return (datetime.now(tz=UTC) + timedelta(seconds=seconds)).isoformat()


def _claim_lease_expiry(claim: Mapping[str, Any]) -> datetime:
    raw = claim.get("lease_expires_at")
    if not isinstance(raw, str):
        return datetime.min.replace(tzinfo=UTC)
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return datetime.min.replace(tzinfo=UTC)
    return parsed.astimezone(UTC) if parsed.tzinfo is not None else datetime.min.replace(tzinfo=UTC)


__all__ = [
    "StateStoreAuditChainAdapter",
    "StateStoreKvAdapter",
    "StateStoreActionRunStore",
]
