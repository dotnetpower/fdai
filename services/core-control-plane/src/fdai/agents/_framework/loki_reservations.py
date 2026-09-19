"""Durable Loki proposal reservations with revision-fenced updates."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from fdai.shared.providers.state_store import StateStore

_STATE_KEY = "pantheon/loki/chaos-reservations"
_MAX_CAS_ATTEMPTS = 8


@dataclass(frozen=True, slots=True)
class ReservationResult:
    targets: tuple[str, ...]
    occupied: frozenset[str]
    duplicate: bool = False


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
    ) -> ReservationResult:
        for _ in range(_MAX_CAS_ATTEMPTS):
            current = await self._store.read_state(_STATE_KEY)
            revision, stored_cap, experiments = _decode(current)
            self._validate_cap(stored_cap)
            existing = experiments.get(experiment_id)
            if existing is not None:
                existing_action, requested_targets, selected_targets = existing
                if existing_action != action_type or requested_targets != targets:
                    raise ValueError("chaos experiment identity conflicts with its reservation")
                return ReservationResult(
                    targets=selected_targets,
                    occupied=_occupied(experiments),
                    duplicate=True,
                )
            occupied = _occupied(experiments)
            available = self._cap - len(occupied)
            selected = tuple(target for target in targets if target not in occupied)[:available]
            if not selected:
                return ReservationResult(targets=(), occupied=occupied)
            next_experiments = dict(experiments)
            next_experiments[experiment_id] = (action_type, targets, selected)
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
        for _ in range(_MAX_CAS_ATTEMPTS):
            current = await self._store.read_state(_STATE_KEY)
            revision, stored_cap, experiments = _decode(current)
            self._validate_cap(stored_cap)
            existing = experiments.get(experiment_id)
            if existing is None:
                return None
            existing_action, _, selected_targets = existing
            if existing_action != action_type or selected_targets != targets:
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

    def _validate_cap(self, stored_cap: int | None) -> None:
        if stored_cap is not None and stored_cap != self._cap:
            raise ValueError("chaos reservation blast-radius cap conflicts with durable state")


def _decode(
    record: Mapping[str, Any] | None,
) -> tuple[int, int | None, dict[str, tuple[str, tuple[str, ...], tuple[str, ...]]]]:
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
    experiments: dict[str, tuple[str, tuple[str, ...], tuple[str, ...]]] = {}
    for experiment_id, raw in raw_experiments.items():
        if not isinstance(experiment_id, str) or not experiment_id or not isinstance(raw, Mapping):
            raise ValueError("chaos reservation experiment is malformed")
        action_type = raw.get("action_type")
        raw_requested = raw.get("requested_targets")
        raw_targets = raw.get("targets")
        if (
            not isinstance(action_type, str)
            or not action_type
            or not isinstance(raw_requested, list)
            or not isinstance(raw_targets, list)
        ):
            raise ValueError("chaos reservation fields are malformed")
        requested = tuple(target for target in raw_requested if isinstance(target, str) and target)
        targets = tuple(target for target in raw_targets if isinstance(target, str) and target)
        if (
            len(requested) != len(raw_requested)
            or not requested
            or len(set(requested)) != len(requested)
            or len(targets) != len(raw_targets)
            or not targets
            or len(set(targets)) != len(targets)
            or not set(targets).issubset(requested)
        ):
            raise ValueError("chaos reservation targets are malformed")
        experiments[experiment_id] = (action_type, requested, targets)
    _occupied(experiments)
    return revision, blast_radius_cap, experiments


def _encode(
    revision: int,
    blast_radius_cap: int,
    experiments: dict[str, tuple[str, tuple[str, ...], tuple[str, ...]]],
) -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "revision": revision,
        "blast_radius_cap": blast_radius_cap,
        "experiments": {
            experiment_id: {
                "action_type": action_type,
                "requested_targets": list(requested),
                "targets": list(targets),
            }
            for experiment_id, (action_type, requested, targets) in sorted(experiments.items())
        },
    }


def _occupied(
    experiments: dict[str, tuple[str, tuple[str, ...], tuple[str, ...]]],
) -> frozenset[str]:
    targets = tuple(target for _, _, reserved in experiments.values() for target in reserved)
    if len(set(targets)) != len(targets):
        raise ValueError("chaos reservation targets overlap")
    return frozenset(targets)


__all__ = ["LokiReservationJournal", "ReservationResult"]
