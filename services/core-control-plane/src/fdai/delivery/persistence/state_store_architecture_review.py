"""Durable idempotency and projection status for ARB observations."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping

from fdai.core.architecture_review import ArchitectureReviewObservation
from fdai.shared.providers.state_store import StateStore

_PREFIX = "architecture-review:observation:"


class StateStoreArchitectureReviewStateStore:
    """Persist one bounded no-authority observation identity across replicas."""

    def __init__(self, store: StateStore) -> None:
        self._store = store

    async def get(self, key: str) -> ArchitectureReviewObservation | None:
        record = await self._store.read_state(_state_key(key))
        if record is None:
            return None
        return _observation_from_record(record)

    async def put_if_absent(
        self,
        key: str,
        value: ArchitectureReviewObservation,
    ) -> ArchitectureReviewObservation | None:
        created = await self._store.write_state_if_absent(
            _state_key(key),
            {
                "schema_version": "1.0.0",
                "idempotency_key": key,
                "observation": value.to_mapping(),
                "projection_status": "pending",
            },
        )
        return None if created else await self.get(key)

    async def get_projection_status(self, key: str) -> str:
        record = await self._store.read_state(_state_key(key))
        if record is None:
            return "pending"
        status = record.get("projection_status")
        return status if isinstance(status, str) else "pending"

    async def mark_projection(self, key: str, status: str) -> None:
        if status not in {"pending", "projected", "failed", "unavailable"}:
            raise ValueError("architecture review projection status is invalid")
        state_key = _state_key(key)
        for _ in range(8):
            record = await self._store.read_state(state_key)
            if record is None:
                raise ValueError("architecture review observation state is unavailable")
            revision = record.get("revision", 0)
            if isinstance(revision, bool) or not isinstance(revision, int):
                raise ValueError("architecture review observation revision is invalid")
            updated = {
                name: item
                for name, item in record.items()
                if name not in {"revision", "updated_at"}
            }
            updated["projection_status"] = status
            updated["revision"] = revision + 1
            if await self._store.compare_and_set_state(
                state_key,
                updated,
                expected_revision=revision,
            ):
                return
        raise RuntimeError("architecture review projection status update conflicted")


def _state_key(idempotency_key: str) -> str:
    if not idempotency_key.strip():
        raise ValueError("architecture review idempotency key MUST be non-empty")
    digest = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()
    return f"{_PREFIX}{digest}"


def _observation_from_record(record: Mapping[str, object]) -> ArchitectureReviewObservation:
    if record.get("schema_version") != "1.0.0":
        raise ValueError("architecture review observation schema version is unsupported")
    raw = record.get("observation")
    if not isinstance(raw, Mapping):
        raise ValueError("architecture review observation payload is invalid")
    required = {
        name: raw.get(name)
        for name in (
            "change_id",
            "idempotency_key",
            "correlation_id",
            "target_ref",
            "change_digest",
            "recommendation",
        )
    }
    if any(not isinstance(value, str) or not value for value in required.values()):
        raise ValueError("architecture review observation identity is invalid")
    reasons = raw.get("reasons")
    if not isinstance(reasons, list) or any(not isinstance(item, str) for item in reasons):
        raise ValueError("architecture review observation reasons are invalid")
    normalized = raw.get("normalized_change")
    if not isinstance(normalized, Mapping):
        raise ValueError("architecture review normalized Change is invalid")
    projection_status = record.get("projection_status")
    projected = projection_status == "projected"
    return ArchitectureReviewObservation(
        change_id=str(required["change_id"]),
        idempotency_key=str(required["idempotency_key"]),
        correlation_id=str(required["correlation_id"]),
        target_ref=str(required["target_ref"]),
        change_digest=str(required["change_digest"]),
        recommendation=str(required["recommendation"]) if projected else "hold",
        reasons=(
            tuple(reasons)
            if projected
            else tuple(sorted({*reasons, "persisted_projection_incomplete"}))
        ),
        context=None,
        evidence=None,
        scenario=None,
        decision_case=None,
        impact_envelope=None,
        normalized_change=tuple((str(key), value) for key, value in normalized.items()),
    )


__all__ = ["StateStoreArchitectureReviewStateStore"]
