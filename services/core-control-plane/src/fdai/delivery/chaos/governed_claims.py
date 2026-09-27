"""Durable per-target claims that keep at most one live chaos run per target.

The distributed logical-target lock serializes concurrent processes, but it
cannot see a run whose process stopped mid-fault. Each target therefore records
the run that last claimed it, and a run may take a claimed target only when the
holder released it. A holder releases its targets only when FDAI verified that
nothing remains live: it recovered, it was denied before injecting, or it
failed without attempting an injection. An escalated run, a run that failed
after an attempted injection, an orphaned run, and an unknown holder keep their
targets until an audited, human-approved closure record (see
``governed_closure``) releases them. Each run also binds the digest of the
enforce approval that authorized it, so that approval can never close the run,
and :class:`ClosureFencedRunStore` refuses ``injecting`` once a run is closed.
"""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import AsyncIterator, Mapping
from contextlib import AsyncExitStack, asynccontextmanager
from datetime import UTC, datetime

from fdai.core.chaos.run_state import ChaosRunSnapshot, ChaosRunState
from fdai.core.chaos.run_store import ChaosRunClaimError, ChaosRunStore
from fdai.delivery.chaos.governed_outcome import outcome_record_key
from fdai.shared.providers.resource_lock import ResourceLock, resource_lock_key
from fdai.shared.providers.state_store import StateStore
from fdai.shared.providers.tool import ToolPreconditionError

_RELEASING_STATES = frozenset({ChaosRunState.RECOVERED, ChaosRunState.DENIED})


def target_digest(target: str) -> str:
    """Return the stable digest that stands in for a target in claims and audit."""

    return hashlib.sha256(target.encode("utf-8")).hexdigest()


def chaos_target_claim_key(target: str) -> str:
    """Return the state key of one target's claim without embedding the target."""

    return f"chaos-target-claim:{target_digest(target)}"


def closure_record_key(run_id: str) -> str:
    """Return the create-only key of one run's human-approved closure record."""

    return f"chaos-run-closure:{run_id}"


def run_binding_key(run_id: str) -> str:
    """Return the create-only key binding one run to its enforce approval and targets."""

    return f"chaos-run-binding:{run_id}"


def approval_digest(approval_ref: str) -> str:
    """Return the digest a run binding keeps instead of the approval reference."""

    return hashlib.sha256(approval_ref.encode("utf-8")).hexdigest()


class ChaosRunClosedError(ChaosRunClaimError):
    """A run with a closure record can never inject."""


class ClosureFencedRunStore(ChaosRunStore):
    """Re-check the closure record immediately before the exclusive ``injecting`` CAS."""

    def __init__(self, *, state_store: StateStore) -> None:
        super().__init__(state_store=state_store)
        self._fence_store = state_store

    async def transition(
        self,
        snapshot: ChaosRunSnapshot,
        *,
        target: ChaosRunState,
        idempotency_key: str,
        at: datetime,
        exclusive: bool = False,
    ) -> ChaosRunSnapshot:
        if target is ChaosRunState.INJECTING:
            record = await self._fence_store.read_state(closure_record_key(snapshot.run_id))
            if record is not None:
                raise ChaosRunClosedError("a closed chaos run can never inject")
        return await super().transition(
            snapshot,
            target=target,
            idempotency_key=idempotency_key,
            at=at,
            exclusive=exclusive,
        )


@asynccontextmanager
async def held_target_locks(
    target_lock: ResourceLock,
    targets: tuple[str, ...],
    *,
    timeout: float,
) -> AsyncIterator[None]:
    """Hold every distributed logical-target lock in sorted order within a bounded wait."""

    async with AsyncExitStack() as stack:
        try:
            async with asyncio.timeout(timeout):
                for target in sorted(set(targets)):
                    lock = target_lock.acquire(resource_lock_key(target))
                    await stack.enter_async_context(lock)
        except TimeoutError as exc:
            raise ToolPreconditionError("logical-target lock was not acquired in time") from exc
        yield


class ChaosTargetClaims:
    """Claim every target of one run before its eligibility is evaluated."""

    def __init__(self, *, state_store: StateStore, run_store: ChaosRunStore) -> None:
        self._state_store = state_store
        self._run_store = run_store

    async def claim(self, *, run_id: str, targets: tuple[str, ...], at: datetime) -> bool:
        """Return ``False`` when another run still holds one of the targets."""

        for target in sorted(set(targets)):
            if not await self._claim_one(run_id=run_id, target=target, at=at):
                return False
        return True

    async def bind(
        self,
        *,
        run_id: str,
        targets: tuple[str, ...],
        approval_ref: str | None,
        at: datetime,
    ) -> None:
        """Record once which enforce approval and targets a run was admitted with."""

        record = {
            "run_id": run_id,
            "approval_digest": approval_digest(approval_ref) if approval_ref else None,
            "target_digests": sorted(target_digest(item) for item in set(targets)),
            "recorded_at": at.astimezone(UTC).isoformat(),
        }
        event_id = f"{run_id}:binding"
        await self._state_store.write_state_with_audit_if_absent(
            run_binding_key(run_id),
            record,
            {
                "event_id": event_id,
                "idempotency_key": event_id,
                "actor": "Saga",
                "producer_principal": "Saga",
                "action_kind": "chaos.run.binding",
                "mode": "enforce",
                "run_id": run_id,
                "target_digests": record["target_digests"],
                "recorded_at": record["recorded_at"],
            },
        )

    async def binding(self, run_id: str) -> Mapping[str, object] | None:
        record = await self._state_store.read_state(run_binding_key(run_id))
        return record if record is not None and record.get("run_id") == run_id else None

    async def holder(self, target: str) -> str | None:
        current = await self._state_store.read_state(chaos_target_claim_key(target))
        holder = str(current.get("run_id", "")) if current is not None else ""
        return holder or None

    async def closed(self, run_id: str) -> bool:
        record = await self._state_store.read_state(closure_record_key(run_id))
        return record is not None and record.get("run_id") == run_id

    async def released(self, run_id: str) -> bool:
        """Return whether ``run_id`` verifiably left nothing live on its targets."""

        if await self.closed(run_id):
            return True
        snapshot = await self._run_store.get(run_id)
        if snapshot is None:
            return False
        if snapshot.state in _RELEASING_STATES:
            return True
        if snapshot.state is not ChaosRunState.FAILED:
            return False
        record = await self._state_store.read_state(outcome_record_key(run_id))
        return (
            record is not None
            and record.get("run_id") == run_id
            and record.get("injected") is False
        )

    async def _claim_one(self, *, run_id: str, target: str, at: datetime) -> bool:
        key = chaos_target_claim_key(target)
        current = await self._state_store.read_state(key)
        if current is None:
            record = _record(run_id=run_id, revision=1, at=at)
            created = await self._state_store.write_state_with_audit_if_absent(
                key,
                record,
                _audit(run_id=run_id, target=target, record=record),
            )
            if created:
                return True
            current = await self._state_store.read_state(key)
            if current is None:
                return False
        holder = str(current.get("run_id", ""))
        if holder == run_id:
            return True
        if not holder or not await self.released(holder):
            return False
        revision = current.get("revision")
        if isinstance(revision, bool) or not isinstance(revision, int):
            return False
        record = _record(run_id=run_id, revision=revision + 1, at=at)
        return await self._state_store.compare_and_set_state_with_audit(
            key,
            record,
            expected_revision=revision,
            audit_entry=_audit(run_id=run_id, target=target, record=record),
        )


def _record(*, run_id: str, revision: int, at: datetime) -> dict[str, object]:
    return {
        "run_id": run_id,
        "revision": revision,
        "claimed_at": at.astimezone(UTC).isoformat(),
    }


def _audit(*, run_id: str, target: str, record: Mapping[str, object]) -> dict[str, object]:
    digest = target_digest(target)
    event_id = f"{run_id}:target-claim:{digest[:16]}:{record['revision']}"
    return {
        "event_id": event_id,
        "idempotency_key": event_id,
        "actor": "Saga",
        "producer_principal": "Saga",
        "action_kind": "chaos.target.claim",
        "mode": "enforce",
        "run_id": run_id,
        "target_digest": digest,
        "revision": record["revision"],
        "recorded_at": record["claimed_at"],
    }


__all__ = [
    "ChaosRunClosedError",
    "ChaosTargetClaims",
    "ClosureFencedRunStore",
    "approval_digest",
    "chaos_target_claim_key",
    "closure_record_key",
    "held_target_locks",
    "run_binding_key",
    "target_digest",
]
