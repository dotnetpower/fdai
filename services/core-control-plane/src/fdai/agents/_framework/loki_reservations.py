"""Durable Loki proposal reservations with revision-fenced updates."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from fdai.shared.providers.state_store import StateStore

_STATE_KEY = "pantheon/loki/chaos-reservations"
_MAX_CAS_ATTEMPTS = 8
_MAX_IDENTIFIER_CHARS = 512
_MAX_TARGETS = 32


@dataclass(frozen=True, slots=True)
class ReservationResult:
    targets: tuple[str, ...]
    occupied: frozenset[str]
    duplicate: bool = False


@dataclass(frozen=True, slots=True)
class ReservationRecord:
    action_type: str
    requested_targets: tuple[str, ...]
    selected_targets: tuple[str, ...]
    reserved_at: str


class LokiReservationJournal:
    """Atomically reserve and release proposal targets across replicas."""

    def __init__(self, store: StateStore, *, blast_radius_cap: int) -> None:
        self._store = store
        self._cap = blast_radius_cap

    async def snapshot(self) -> frozenset[str]:
        _, stored_cap, experiments = _decode(await self._store.read_state(_STATE_KEY))
        self._validate_cap(stored_cap)
        return _occupied(experiments)

    async def reserve(
        self,
        *,
        experiment_id: str,
        action_type: str,
        targets: tuple[str, ...],
        reserved_at: str,
    ) -> ReservationResult:
        _validate_reservation_identity(experiment_id, action_type, targets)
        for _ in range(_MAX_CAS_ATTEMPTS):
            current = await self._store.read_state(_STATE_KEY)
            revision, stored_cap, experiments = _decode(current)
            self._validate_cap(stored_cap)
            existing = experiments.get(experiment_id)
            if existing is not None:
                if existing.action_type != action_type or existing.requested_targets != targets:
                    raise ValueError("chaos experiment identity conflicts with its reservation")
                return ReservationResult(
                    targets=existing.selected_targets,
                    occupied=_occupied(experiments),
                    duplicate=True,
                )
            occupied = _occupied(experiments)
            available = self._cap - len(occupied)
            selected = tuple(target for target in targets if target not in occupied)[:available]
            if not selected:
                return ReservationResult(targets=(), occupied=occupied)
            next_experiments = dict(experiments)
            next_experiments[experiment_id] = ReservationRecord(
                action_type=action_type,
                requested_targets=targets,
                selected_targets=selected,
                reserved_at=reserved_at,
            )
            next_record = _encode(revision + 1, self._cap, next_experiments)
            audit = {
                "actor": "Loki",
                "action_kind": "chaos.reservation.created",
                "experiment_id": experiment_id,
                "revision": revision + 1,
                "target_count": len(selected),
            }
            written = (
                await self._store.write_state_with_audit_if_absent(
                    _STATE_KEY,
                    next_record,
                    audit,
                )
                if current is None
                else await self._store.compare_and_set_state_with_audit(
                    _STATE_KEY,
                    next_record,
                    expected_revision=revision,
                    audit_entry=audit,
                )
            )
            if written:
                return ReservationResult(
                    targets=selected,
                    occupied=_occupied(next_experiments),
                )
        raise RuntimeError("chaos reservation contention exceeded the bounded retry limit")

    async def release(
        self,
        *,
        experiment_id: str,
        action_type: str,
        targets: tuple[str, ...],
    ) -> ReservationResult | None:
        _validate_reservation_identity(experiment_id, action_type, targets)
        for _ in range(_MAX_CAS_ATTEMPTS):
            current = await self._store.read_state(_STATE_KEY)
            revision, stored_cap, experiments = _decode(current)
            self._validate_cap(stored_cap)
            existing = experiments.get(experiment_id)
            if existing is None:
                return None
            if existing.action_type != action_type or existing.selected_targets != targets:
                raise ValueError("chaos completion does not match its reservation")
            next_experiments = dict(experiments)
            del next_experiments[experiment_id]
            next_record = _encode(revision + 1, self._cap, next_experiments)
            written = await self._store.compare_and_set_state_with_audit(
                _STATE_KEY,
                next_record,
                expected_revision=revision,
                audit_entry={
                    "actor": "Loki",
                    "action_kind": "chaos.reservation.released",
                    "experiment_id": experiment_id,
                    "revision": revision + 1,
                    "target_count": len(targets),
                },
            )
            if written:
                return ReservationResult(targets=targets, occupied=_occupied(next_experiments))
        raise RuntimeError("chaos release contention exceeded the bounded retry limit")

    async def expire_stale(self, *, cutoff: str) -> ReservationResult:
        for _ in range(_MAX_CAS_ATTEMPTS):
            current = await self._store.read_state(_STATE_KEY)
            revision, stored_cap, experiments = _decode(current)
            self._validate_cap(stored_cap)
            next_experiments = {
                experiment_id: reservation
                for experiment_id, reservation in experiments.items()
                if not reservation.reserved_at or reservation.reserved_at > cutoff
            }
            if len(next_experiments) == len(experiments):
                return ReservationResult(targets=(), occupied=_occupied(experiments))
            next_record = _encode(revision + 1, self._cap, next_experiments)
            expired_targets = tuple(
                target
                for experiment_id, reservation in experiments.items()
                if experiment_id not in next_experiments
                for target in reservation.selected_targets
            )
            written = await self._store.compare_and_set_state_with_audit(
                _STATE_KEY,
                next_record,
                expected_revision=revision,
                audit_entry={
                    "actor": "Loki",
                    "action_kind": "chaos.reservation.expired",
                    "revision": revision + 1,
                    "target_count": len(expired_targets),
                },
            )
            if written:
                return ReservationResult(
                    targets=expired_targets,
                    occupied=_occupied(next_experiments),
                )
        raise RuntimeError("chaos reservation expiry contention exceeded the bounded retry limit")

    def _validate_cap(self, stored_cap: int | None) -> None:
        if stored_cap is not None and stored_cap != self._cap:
            raise ValueError("chaos reservation blast-radius cap conflicts with durable state")


def _decode(
    record: Mapping[str, Any] | None,
) -> tuple[int, int | None, dict[str, ReservationRecord]]:
    if record is None:
        return 0, None, {}
    revision = record.get("revision")
    blast_radius_cap = record.get("blast_radius_cap")
    raw_experiments = record.get("experiments")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        raise ValueError("chaos reservation revision must be a positive integer")
    if (
        isinstance(blast_radius_cap, bool)
        or not isinstance(blast_radius_cap, int)
        or blast_radius_cap < 1
    ):
        raise ValueError("chaos reservation blast-radius cap must be a positive integer")
    if not isinstance(raw_experiments, Mapping):
        raise ValueError("chaos reservation experiments must be an object")
    experiments: dict[str, ReservationRecord] = {}
    for experiment_id, raw in raw_experiments.items():
        if (
            not isinstance(experiment_id, str)
            or not _safe_identifier(experiment_id)
            or not isinstance(raw, Mapping)
        ):
            raise ValueError("chaos reservation experiment is malformed")
        action_type = raw.get("action_type")
        raw_requested = raw.get("requested_targets")
        raw_targets = raw.get("targets")
        reserved_at = raw.get("reserved_at", "")
        if (
            not isinstance(action_type, str)
            or not _safe_identifier(action_type)
            or not isinstance(raw_requested, list)
            or not isinstance(raw_targets, list)
        ):
            raise ValueError("chaos reservation fields are malformed")
        requested = tuple(
            target.strip()
            for target in raw_requested
            if isinstance(target, str) and _safe_identifier(target)
        )
        targets = tuple(
            target.strip()
            for target in raw_targets
            if isinstance(target, str) and _safe_identifier(target)
        )
        if (
            len(requested) != len(raw_requested)
            or not requested
            or len(requested) > _MAX_TARGETS
            or len(set(requested)) != len(requested)
            or len(targets) != len(raw_targets)
            or not targets
            or len(set(targets)) != len(targets)
            or not set(targets).issubset(requested)
        ):
            raise ValueError("chaos reservation targets are malformed")
        if not isinstance(reserved_at, str):
            raise ValueError("chaos reservation reserved_at is malformed")
        experiments[experiment_id] = ReservationRecord(
            action_type=action_type,
            requested_targets=requested,
            selected_targets=targets,
            reserved_at=reserved_at,
        )
    _occupied(experiments)
    return revision, blast_radius_cap, experiments


def _encode(
    revision: int,
    blast_radius_cap: int,
    experiments: dict[str, ReservationRecord],
) -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "revision": revision,
        "blast_radius_cap": blast_radius_cap,
        "experiments": {
            experiment_id: {
                "action_type": reservation.action_type,
                "requested_targets": list(reservation.requested_targets),
                "targets": list(reservation.selected_targets),
                "reserved_at": reservation.reserved_at,
            }
            for experiment_id, reservation in sorted(experiments.items())
        },
    }


def _occupied(
    experiments: dict[str, ReservationRecord],
) -> frozenset[str]:
    targets = tuple(
        target for reservation in experiments.values() for target in reservation.selected_targets
    )
    if len(set(targets)) != len(targets):
        raise ValueError("chaos reservation targets overlap")
    return frozenset(targets)


def _safe_identifier(value: str) -> bool:
    stripped = value.strip()
    return (
        bool(stripped)
        and stripped == value
        and len(stripped) <= _MAX_IDENTIFIER_CHARS
        and not any((ord(char) < 32 and char not in "\t") or ord(char) == 127 for char in stripped)
    )


def _validate_reservation_identity(
    experiment_id: str,
    action_type: str,
    targets: tuple[str, ...],
) -> None:
    if not _safe_identifier(experiment_id) or not _safe_identifier(action_type):
        raise ValueError("chaos reservation identity is malformed")
    if not 1 <= len(targets) <= _MAX_TARGETS:
        raise ValueError("chaos reservation targets are malformed")
    if any(not isinstance(target, str) or not _safe_identifier(target) for target in targets):
        raise ValueError("chaos reservation targets are malformed")
    if len(set(target.strip() for target in targets)) != len(targets):
        raise ValueError("chaos reservation targets are malformed")


__all__ = ["LokiReservationJournal", "ReservationRecord", "ReservationResult"]
