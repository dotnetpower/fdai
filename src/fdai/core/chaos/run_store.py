"""StateStore-backed chaos run snapshots with append-only transition audit."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime

from fdai.core.chaos.run_state import ChaosRunSnapshot, ChaosRunState, transition_chaos_run
from fdai.shared.providers.state_store import StateStore


class ChaosRunConflictError(RuntimeError):
    """A concurrent writer advanced the chaos run revision."""


class ChaosRunStore:
    def __init__(self, *, state_store: StateStore) -> None:
        self._store = state_store

    async def create(self, *, run_id: str, at: datetime) -> ChaosRunSnapshot:
        if not run_id.strip() or at.tzinfo is None:
            raise ValueError("run_id and aware timestamp are required")
        snapshot = ChaosRunSnapshot(
            run_id=run_id,
            state=ChaosRunState.PLANNED,
            revision=0,
            updated_at=at,
            last_idempotency_key=f"{run_id}:created",
        )
        created = await self._store.write_state_with_audit_if_absent(
            _key(run_id),
            _serialize(snapshot),
            _audit(snapshot, from_state=None),
        )
        if created:
            return snapshot
        existing = await self.get(run_id)
        if existing is None:
            raise ChaosRunConflictError("chaos run create lost without readable state")
        return existing

    async def transition(
        self,
        snapshot: ChaosRunSnapshot,
        *,
        target: ChaosRunState,
        idempotency_key: str,
        at: datetime,
    ) -> ChaosRunSnapshot:
        updated = transition_chaos_run(
            snapshot,
            target=target,
            idempotency_key=idempotency_key,
            at=at,
        )
        if updated is snapshot:
            return snapshot
        applied = await self._store.compare_and_set_state_with_audit(
            _key(snapshot.run_id),
            _serialize(updated),
            expected_revision=snapshot.revision,
            audit_entry=_audit(updated, from_state=snapshot.state),
        )
        if not applied:
            raise ChaosRunConflictError("chaos run revision changed concurrently")
        return updated

    async def get(self, run_id: str) -> ChaosRunSnapshot | None:
        raw = await self._store.read_state(_key(run_id))
        return _deserialize(raw) if raw is not None else None


def _key(run_id: str) -> str:
    return f"chaos-run:{run_id}"


def _serialize(snapshot: ChaosRunSnapshot) -> dict[str, object]:
    return {
        "run_id": snapshot.run_id,
        "state": snapshot.state.value,
        "revision": snapshot.revision,
        "updated_at": snapshot.updated_at.astimezone(UTC).isoformat(),
        "last_idempotency_key": snapshot.last_idempotency_key,
    }


def _deserialize(raw: Mapping[str, object]) -> ChaosRunSnapshot:
    try:
        updated_at = datetime.fromisoformat(str(raw["updated_at"]))
        raw_revision = raw["revision"]
        if isinstance(raw_revision, bool) or not isinstance(raw_revision, int):
            raise TypeError("stored chaos revision MUST be an integer")
        return ChaosRunSnapshot(
            run_id=str(raw["run_id"]),
            state=ChaosRunState(str(raw["state"])),
            revision=raw_revision,
            updated_at=updated_at,
            last_idempotency_key=str(raw["last_idempotency_key"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ChaosRunConflictError("stored chaos run is malformed") from exc


def _audit(
    snapshot: ChaosRunSnapshot,
    *,
    from_state: ChaosRunState | None,
) -> dict[str, object]:
    return {
        "event_id": snapshot.last_idempotency_key,
        "idempotency_key": snapshot.last_idempotency_key,
        "actor": "Saga",
        "producer_principal": "Saga",
        "action_kind": "chaos.run.transition",
        "mode": "enforce",
        "run_id": snapshot.run_id,
        "from_state": from_state.value if from_state is not None else None,
        "to_state": snapshot.state.value,
        "revision": snapshot.revision,
        "recorded_at": snapshot.updated_at.astimezone(UTC).isoformat(),
    }


__all__ = ["ChaosRunConflictError", "ChaosRunStore"]
