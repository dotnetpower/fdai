"""Durable monotonic generation times for exact Assurance Twin source revisions."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta

from fdai.delivery.assurance_twin_writers import AssuranceTwinPublishRequest
from fdai.shared.providers.state_store import StateStore

_PREFIX = "runtime:assurance-twin-evidence:"
_MAX_RESERVATIONS = 128


class AssuranceTwinEvidenceExpiredError(ValueError):
    """The next monotonic source time would exceed its evidence freshness."""


class AssuranceTwinEvidenceClockCapacityError(RuntimeError):
    """Compatibility name for bounded clock-capacity failures."""


class AssuranceTwinEvidenceClockContentionError(RuntimeError):
    """The bounded clock could not win its compare-and-set retry."""


class StateStoreTwinEvidenceClock:
    """Reserve retry-stable first-seen times without dropping unresolved revisions."""

    def __init__(self, *, store: StateStore) -> None:
        self._store = store

    async def stable_generated_at(
        self,
        request: AssuranceTwinPublishRequest,
        *,
        proposed: datetime,
        fresh_until: datetime,
    ) -> datetime:
        retained = await self._store.read_state(_source_key(request))
        if retained is not None:
            record = retained.get("record")
            raw = record.get("generated_at") if isinstance(record, Mapping) else None
            if not isinstance(raw, str):
                raise ValueError("Assurance Twin retained generation time is unavailable")
            return _generation_time(raw)
        return await self._reserve(
            request,
            proposed=proposed,
            fresh_until=fresh_until,
        )

    async def release(self, request: AssuranceTwinPublishRequest) -> None:
        clock_key = _clock_key(request)
        for _attempt in range(8):
            clock = await self._store.read_state(clock_key)
            if clock is None:
                return
            revision = clock.get("revision")
            reservations = clock.get("reservations")
            if (
                not isinstance(revision, int)
                or isinstance(revision, bool)
                or not isinstance(reservations, Mapping)
            ):
                raise ValueError("Assurance Twin evidence clock is malformed")
            if request.source_revision not in reservations:
                return
            updated = {
                **dict(clock),
                "revision": revision + 1,
                "reservations": {
                    str(source_revision): str(generated_at)
                    for source_revision, generated_at in reservations.items()
                    if source_revision != request.source_revision
                },
            }
            if await self._store.compare_and_set_state_with_audit(
                clock_key,
                updated,
                expected_revision=revision,
                audit_entry=_clock_audit(request, revision=revision + 1),
            ):
                return
        raise AssuranceTwinEvidenceClockContentionError(
            "Assurance Twin evidence clock release exceeded its retry bound"
        )

    async def _reserve(
        self,
        request: AssuranceTwinPublishRequest,
        *,
        proposed: datetime,
        fresh_until: datetime,
    ) -> datetime:
        archived = await self._store.read_state(_reservation_key(request))
        if archived is not None:
            raw_archived = archived.get("generated_at")
            if not isinstance(raw_archived, str):
                raise ValueError("Assurance Twin archived reservation is malformed")
            return _generation_time(raw_archived)
        clock_key = _clock_key(request)
        for _attempt in range(8):
            clock = await self._store.read_state(clock_key)
            if clock is None:
                initial = {
                    "kind": "assurance_twin_evidence_clock",
                    "revision": 1,
                    "last_generated_at": proposed.astimezone(UTC).isoformat(),
                    "reservations": {request.source_revision: proposed.astimezone(UTC).isoformat()},
                }
                await self._store.write_state_with_audit_if_absent(
                    clock_key,
                    initial,
                    _clock_audit(request, revision=1),
                )
                clock = await self._store.read_state(clock_key)
            if clock is None:
                raise RuntimeError("Assurance Twin evidence clock disappeared")
            revision = clock.get("revision")
            reservations = clock.get("reservations")
            raw_last = clock.get("last_generated_at")
            if (
                not isinstance(revision, int)
                or isinstance(revision, bool)
                or not isinstance(reservations, Mapping)
                or not isinstance(raw_last, str)
            ):
                raise ValueError("Assurance Twin evidence clock is malformed")
            reserved = reservations.get(request.source_revision)
            if isinstance(reserved, str):
                return _generation_time(reserved)
            candidate = max(
                proposed.astimezone(UTC),
                _generation_time(raw_last) + timedelta(microseconds=1),
            )
            if candidate >= fresh_until.astimezone(UTC):
                raise AssuranceTwinEvidenceExpiredError(
                    "Assurance Twin monotonic generation time exceeds freshness"
                )
            retained_reservations = {
                str(source_revision): str(generated_at)
                for source_revision, generated_at in reservations.items()
                if isinstance(source_revision, str) and isinstance(generated_at, str)
            }
            if len(retained_reservations) >= _MAX_RESERVATIONS:
                spill_revision, spill_time = min(
                    retained_reservations.items(),
                    key=lambda item: (item[1], item[0]),
                )
                await self._archive(request, spill_revision, spill_time)
                retained_reservations.pop(spill_revision)
            updated = {
                **dict(clock),
                "revision": revision + 1,
                "last_generated_at": candidate.isoformat(),
                "reservations": {
                    **retained_reservations,
                    request.source_revision: candidate.isoformat(),
                },
            }
            if await self._store.compare_and_set_state_with_audit(
                clock_key,
                updated,
                expected_revision=revision,
                audit_entry=_clock_audit(request, revision=revision + 1),
            ):
                return candidate
        raise AssuranceTwinEvidenceClockContentionError(
            "Assurance Twin evidence clock exceeded its retry bound"
        )

    async def _archive(
        self,
        request: AssuranceTwinPublishRequest,
        source_revision: str,
        generated_at: str,
    ) -> None:
        await self._store.write_state_with_audit_if_absent(
            _reservation_key_for(
                kind=request.kind,
                source_key=request.source_key,
                source_revision=source_revision,
            ),
            {
                "kind": "assurance_twin_evidence_clock_reservation",
                "revision": 1,
                "generated_at": generated_at,
            },
            {
                "kind": "assurance_twin_evidence_clock_reservation_archived",
                "producer_principal": ("Heimdall" if request.kind == "posture" else "Forseti"),
                "request_kind": request.kind,
                "source_revision": source_revision,
                "execution_authority": False,
            },
        )


def _generation_time(raw: str) -> datetime:
    try:
        generated_at = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise ValueError("Assurance Twin retained generation time is invalid") from exc
    if generated_at.tzinfo is None or generated_at.utcoffset() is None:
        raise ValueError("Assurance Twin retained generation time is timezone-naive")
    return generated_at


def _source_key(request: AssuranceTwinPublishRequest) -> str:
    return f"{_PREFIX}{request.idempotency_key.removeprefix('sha256:')}"


def _clock_key(request: AssuranceTwinPublishRequest) -> str:
    identity = f"{request.kind}\0{request.source_key}".encode()
    return f"{_PREFIX}clock:{hashlib.sha256(identity).hexdigest()}"


def _reservation_key(request: AssuranceTwinPublishRequest) -> str:
    return _reservation_key_for(
        kind=request.kind,
        source_key=request.source_key,
        source_revision=request.source_revision,
    )


def _reservation_key_for(
    *,
    kind: str,
    source_key: str,
    source_revision: str,
) -> str:
    identity = f"{kind}\0{source_key}\0{source_revision}".encode()
    return f"{_PREFIX}clock-reservation:{hashlib.sha256(identity).hexdigest()}"


def _clock_audit(
    request: AssuranceTwinPublishRequest,
    *,
    revision: int,
) -> dict[str, object]:
    return {
        "kind": "assurance_twin_evidence_clock_advanced",
        "producer_principal": "Heimdall" if request.kind == "posture" else "Forseti",
        "request_kind": request.kind,
        "clock_revision": revision,
        "source_revision": request.source_revision,
        "execution_authority": False,
    }


__all__ = [
    "AssuranceTwinEvidenceClockCapacityError",
    "AssuranceTwinEvidenceClockContentionError",
    "AssuranceTwinEvidenceExpiredError",
    "StateStoreTwinEvidenceClock",
]
