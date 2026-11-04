"""Durable shared provider-read admission, retry cooldown, and within-generation reuse (#2329).

Provides a ``StateStore``-backed admission and cooldown boundary shared across
concurrent inventory readers, recovery probes, and process restarts:

1. Binds each admission partition to an immutable ``ProviderReadScopeBinding``
   (``source_name``, ``authentication_selector_digest``, ``scope_universe_digest``,
   ``policy_digest``, ``generation_id``, and monotonic ``generation_seq``).
2. Retains ``cooldown_not_before`` (from ``Retry-After`` or quota headers) across
   adapter replacements, process restarts, and generation transitions.
3. Enforces exact per-generation request budgets with compare-and-set atomicity:
   - within-generation idempotent replays reuse completed request digests without
     consuming another physical request slot;
   - stale generations fail closed with :class:`StaleProviderReadGenerationError`;
   - cancelled or ambiguous transport attempts remain accounted as consumed and
     never silently replenish capacity;
   - unavailable state storage fails closed with
     :class:`ProviderReadAdmissionUnavailableError` rather than falling back to
     an accepting in-memory gate.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from math import isfinite
from typing import Any

import httpx
from fdai_service_contracts.ontology_query import content_digest

from fdai.delivery.http_retry import retry_not_before
from fdai.shared.providers.state_store import StateStore

_DIGEST_RE = re.compile(r"^sha256:[a-f0-9]{64}$")
_SOURCE_NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{1,63}$")
_STATE_KEY_PREFIX = "inventory-provider-read-admission:v1:"
_GENERATION_KEY_PREFIX = "inventory-provider-read-generation:v1:"
_MAX_CAS_ATTEMPTS = 16
_MAX_RETAINED_RESPONSE_BYTES = 262_144


async def resolve_or_allocate_collection_generation(
    state_store: StateStore,
    *,
    scope_ref: str,
    unfinished_generation_id: str | None = None,
    current_active_snapshot_id: str | None = None,
) -> tuple[str, int]:
    """Resume an in-progress generation after a crash or allocate the next sequence.

    If a previous run promoted a new ``active_snapshot_id`` and crashed before calling
    :func:`complete_collection_generation`, ``current_active_snapshot_id`` differs from
    the recorded ``baseline_active_snapshot_id`` and startup reconciles by advancing to
    the next generation rather than resuming the already-promoted one.
    """

    if not scope_ref.strip():
        raise ValueError("scope_ref MUST be non-empty")
    key = f"{_GENERATION_KEY_PREFIX}{scope_ref.strip()}"
    requested_unfinished = (unfinished_generation_id or "").strip() or None
    normalized_active_snapshot = (current_active_snapshot_id or "").strip() or None
    for _ in range(_MAX_CAS_ATTEMPTS):
        existing = await state_store.read_state(key)
        if existing is None:
            gen_id = requested_unfinished or "collection-gen-000001"
            initial = {
                "active_generation_id": gen_id,
                "active_generation_seq": 1,
                "baseline_active_snapshot_id": normalized_active_snapshot,
                "revision": 1,
                "scope_ref": scope_ref.strip(),
                "status": "in_progress",
            }
            if await state_store.write_state_if_absent(key, initial):
                return gen_id, 1
            continue
        stored_id = str(existing.get("active_generation_id") or "")
        stored_seq = int(existing.get("active_generation_seq") or 1)
        stored_status = str(existing.get("status") or "in_progress")
        stored_baseline_snapshot = existing.get("baseline_active_snapshot_id")
        expected_rev = int(existing.get("revision") or 1)
        snapshot_advanced = (
            normalized_active_snapshot is not None
            and normalized_active_snapshot != stored_baseline_snapshot
        )
        if not snapshot_advanced and (
            (requested_unfinished is not None and requested_unfinished == stored_id)
            or (requested_unfinished is None and stored_status == "in_progress")
        ):
            return stored_id, stored_seq
        next_seq = stored_seq + 1
        next_id = requested_unfinished or f"collection-gen-{next_seq:06d}"
        updated = {
            "active_generation_id": next_id,
            "active_generation_seq": next_seq,
            "baseline_active_snapshot_id": normalized_active_snapshot,
            "revision": expected_rev + 1,
            "scope_ref": scope_ref.strip(),
            "status": "in_progress",
        }
        if await state_store.compare_and_set_state(
            key,
            updated,
            expected_revision=expected_rev,
        ):
            return next_id, next_seq
    raise ProviderReadAdmissionUnavailableError(
        "collection generation CAS contention exceeded maximum attempts"
    )


async def complete_collection_generation(
    state_store: StateStore,
    *,
    scope_ref: str,
    generation_id: str,
    generation_seq: int,
    terminal_status: str = "completed",
) -> None:
    """Mark the current collection generation terminal (`completed` or `failed`)."""

    if (
        not scope_ref.strip()
        or not generation_id.strip()
        or generation_seq < 1
        or terminal_status not in {"completed", "failed"}
    ):
        raise ValueError("complete_collection_generation requires valid scope, generation, status")
    key = f"{_GENERATION_KEY_PREFIX}{scope_ref.strip()}"
    for _ in range(_MAX_CAS_ATTEMPTS):
        existing = await state_store.read_state(key)
        if existing is None:
            return
        if (
            existing.get("active_generation_id") != generation_id.strip()
            or int(existing.get("active_generation_seq") or 0) != generation_seq
        ):
            return
        if existing.get("status") in {"completed", "failed"}:
            return
        expected_rev = int(existing.get("revision") or 1)
        updated = {
            **existing,
            "revision": expected_rev + 1,
            "status": terminal_status,
        }
        if await state_store.compare_and_set_state(
            key,
            updated,
            expected_revision=expected_rev,
        ):
            return
    raise ProviderReadAdmissionUnavailableError(
        "collection generation completion CAS contention exceeded maximum attempts"
    )


class ProviderReadAdmissionError(RuntimeError):
    """Base fail-closed error for durable provider-read admission."""


class ProviderReadAdmissionUnavailableError(ProviderReadAdmissionError):
    """Raised when the durable admission store is unreachable or inconsistent."""


class StaleProviderReadGenerationError(ProviderReadAdmissionError):
    """Raised when a superseded generation attempts to consume or replenish budget."""


class ProviderReadBudgetExhaustedError(ProviderReadAdmissionError):
    """Raised when the generation's physical provider-read budget is exhausted."""


class ProviderReadCooldownActiveError(ProviderReadAdmissionError):
    """Raised when a durable provider cooldown is active and waiting is disabled."""

    def __init__(self, message: str, *, retry_not_before: datetime) -> None:
        super().__init__(message)
        self.retry_not_before = retry_not_before


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("provider-read admission timestamps MUST be timezone-aware")
    return value.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class ProviderReadScopeBinding:
    """Immutable identity, scope universe, policy, and generation binding for one source."""

    source_name: str
    authentication_selector_digest: str
    scope_universe_digest: str
    policy_digest: str
    generation_id: str
    generation_seq: int = 1

    def __post_init__(self) -> None:
        if _SOURCE_NAME_RE.fullmatch(self.source_name) is None:
            raise ValueError(f"invalid provider-read source_name: {self.source_name!r}")
        for field_name, val in (
            ("authentication_selector_digest", self.authentication_selector_digest),
            ("scope_universe_digest", self.scope_universe_digest),
            ("policy_digest", self.policy_digest),
        ):
            if _DIGEST_RE.fullmatch(val) is None:
                raise ValueError(f"{field_name} MUST be a canonical sha256 digest")
        if not self.generation_id.strip():
            raise ValueError("generation_id MUST be non-empty")
        if type(self.generation_seq) is not int or self.generation_seq < 1:
            raise ValueError("generation_seq MUST be a positive integer")

    @property
    def partition_digest(self) -> str:
        return content_digest(
            {
                "authentication_selector_digest": self.authentication_selector_digest,
                "policy_digest": self.policy_digest,
                "scope_universe_digest": self.scope_universe_digest,
                "source_name": self.source_name,
            }
        )

    @property
    def state_key(self) -> str:
        return f"{_STATE_KEY_PREFIX}{self.source_name}:{self.partition_digest[7:39]}"


@dataclass(frozen=True, slots=True)
class ProviderReadAdmissionReceipt:
    """Typed receipt for one admitted or reused provider read."""

    source_name: str
    generation_id: str
    generation_seq: int
    request_id: str
    idempotency_key: str
    reused: bool
    reused_response_digest: str | None
    requests_admitted: int
    requests_reused: int
    requests_held: int
    ambiguous_or_cancelled_count: int
    max_requests_per_generation: int
    reused_response_bytes: bytes | None = None


class DurableProviderReadAdmissionGate:
    """Coordinate provider-read budgets, reuse, and cooldowns across readers and restarts."""

    def __init__(
        self,
        *,
        state_store: StateStore,
        binding: ProviderReadScopeBinding,
        max_requests_per_generation: int = 64,
        max_defer_seconds: float = 120.0,
        clock: Callable[[], datetime] | None = None,
        sleep: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        if state_store is None:
            raise ValueError("DurableProviderReadAdmissionGate requires a non-null StateStore")
        if type(max_requests_per_generation) is not int or max_requests_per_generation < 1:
            raise ValueError("max_requests_per_generation MUST be a positive integer")
        if not isfinite(max_defer_seconds) or max_defer_seconds <= 0:
            raise ValueError("max_defer_seconds MUST be a positive finite float")
        self._state_store = state_store
        self._binding = binding
        self._max_requests = max_requests_per_generation
        self._max_defer_seconds = float(max_defer_seconds)
        self._clock = clock or (lambda: datetime.now(UTC))
        self._sleep = sleep or asyncio.sleep
        self._local_lock = asyncio.Lock()

    @property
    def binding(self) -> ProviderReadScopeBinding:
        return self._binding

    def _initial_state(self, now: datetime) -> dict[str, Any]:
        return {
            "active_generation_id": self._binding.generation_id,
            "active_generation_seq": self._binding.generation_seq,
            "ambiguous_or_cancelled_count": 0,
            "authentication_selector_digest": self._binding.authentication_selector_digest,
            "completed_requests": {},
            "cooldown_not_before": None,
            "in_flight_requests": {},
            "max_requests_per_generation": self._max_requests,
            "policy_digest": self._binding.policy_digest,
            "requests_admitted": 0,
            "requests_held": 0,
            "requests_reused": 0,
            "revision": 1,
            "scope_universe_digest": self._binding.scope_universe_digest,
            "source_name": self._binding.source_name,
            "updated_at": now.isoformat(),
        }

    def _validate_and_align_generation(
        self,
        current: Mapping[str, Any],
        *,
        now: datetime,
        allow_advance: bool,
    ) -> dict[str, Any]:
        if (
            current.get("source_name") != self._binding.source_name
            or current.get("authentication_selector_digest")
            != self._binding.authentication_selector_digest
            or current.get("scope_universe_digest") != self._binding.scope_universe_digest
            or current.get("policy_digest") != self._binding.policy_digest
        ):
            raise ProviderReadAdmissionUnavailableError(
                "stored provider-read admission state does not match scope/identity/policy binding"
            )
        stored_seq = int(current.get("active_generation_seq", 0))
        stored_gen = str(current.get("active_generation_id", ""))
        if self._binding.generation_seq < stored_seq or (
            self._binding.generation_seq == stored_seq and self._binding.generation_id != stored_gen
        ):
            raise StaleProviderReadGenerationError(
                f"provider-read generation {self._binding.generation_id!r} "
                f"(seq={self._binding.generation_seq}) is superseded by "
                f"{stored_gen!r} (seq={stored_seq})"
            )
        updated = dict(current)
        if self._binding.generation_seq > stored_seq:
            if not allow_advance:
                raise StaleProviderReadGenerationError(
                    "cannot complete or cancel a request across an uninitialized generation"
                )
            # Advance generation while preserving durable cooldown_not_before.
            updated.update(
                {
                    "active_generation_id": self._binding.generation_id,
                    "active_generation_seq": self._binding.generation_seq,
                    "ambiguous_or_cancelled_count": 0,
                    "completed_requests": {},
                    "in_flight_requests": {},
                    "max_requests_per_generation": self._max_requests,
                    "requests_admitted": 0,
                    "requests_held": 0,
                    "requests_reused": 0,
                    "updated_at": now.isoformat(),
                }
            )
        return updated

    async def _read_or_initialize(self, now: datetime) -> dict[str, Any]:
        key = self._binding.state_key
        try:
            existing = await self._state_store.read_state(key)
            if existing is not None:
                return dict(existing)
            initial = self._initial_state(now)
            created = await self._state_store.write_state_if_absent(key, initial)
            if created:
                return initial
            reread = await self._state_store.read_state(key)
            if reread is None:
                raise ProviderReadAdmissionUnavailableError(
                    "provider-read admission state disappeared during initialization"
                )
            return dict(reread)
        except ProviderReadAdmissionError:
            raise
        except Exception as exc:
            raise ProviderReadAdmissionUnavailableError(
                f"provider-read admission state store failed: {type(exc).__name__}"
            ) from exc

    async def defer(self, delay_seconds: float, *, now: datetime | None = None) -> datetime | None:
        """Durably record or extend a provider cooldown across readers and restarts."""

        if delay_seconds <= 0:
            return None
        bounded = min(float(delay_seconds), self._max_defer_seconds)
        at = _aware_utc(now or self._clock())
        candidate_deadline = at + timedelta(seconds=bounded)
        key = self._binding.state_key
        async with self._local_lock:
            for _ in range(_MAX_CAS_ATTEMPTS):
                current = await self._read_or_initialize(at)
                aligned = self._validate_and_align_generation(current, now=at, allow_advance=True)
                expected_rev = int(current.get("revision", 1))
                existing_raw = aligned.get("cooldown_not_before")
                effective_deadline = candidate_deadline
                if isinstance(existing_raw, str) and existing_raw:
                    existing_dt = _aware_utc(datetime.fromisoformat(existing_raw))
                    if existing_dt > effective_deadline:
                        effective_deadline = existing_dt
                aligned["cooldown_not_before"] = effective_deadline.isoformat()
                aligned["revision"] = expected_rev + 1
                aligned["updated_at"] = at.isoformat()
                try:
                    swapped = await self._state_store.compare_and_set_state(
                        key,
                        aligned,
                        expected_revision=expected_rev,
                    )
                except Exception as exc:
                    raise ProviderReadAdmissionUnavailableError(
                        f"provider-read cooldown write failed: {type(exc).__name__}"
                    ) from exc
                if swapped:
                    return effective_deadline
        raise ProviderReadAdmissionUnavailableError(
            "provider-read cooldown CAS contention exceeded maximum attempts"
        )

    async def observe(self, headers: httpx.Headers, *, now: datetime | None = None) -> None:
        """Extract Retry-After or quota reset headers and persist the cooldown."""

        at = _aware_utc(now or self._clock())
        deadline = retry_not_before(headers, now=at)
        if deadline is not None:
            delay = (deadline - at).total_seconds()
            if delay > 0:
                await self.defer(delay, now=at)

    async def wait(self, *, now: datetime | None = None) -> None:
        """Wait until any durable provider cooldown has elapsed."""

        while True:
            at = _aware_utc(now or self._clock())
            current = await self._read_or_initialize(at)
            aligned = self._validate_and_align_generation(current, now=at, allow_advance=True)
            raw_deadline = aligned.get("cooldown_not_before")
            if not isinstance(raw_deadline, str) or not raw_deadline:
                return
            deadline = _aware_utc(datetime.fromisoformat(raw_deadline))
            remaining = (deadline - at).total_seconds()
            if remaining <= 0:
                return
            await self._sleep(remaining)
            if now is not None:
                now = at + timedelta(seconds=remaining)

    async def acquire(
        self,
        *,
        request_id: str,
        idempotency_key: str,
        wait_for_cooldown: bool = False,
        now: datetime | None = None,
    ) -> ProviderReadAdmissionReceipt:
        """Atomically admit one provider read or reuse an identical within-generation result."""

        if not request_id.strip() or not idempotency_key.strip():
            raise ValueError("request_id and idempotency_key MUST be non-empty")
        if wait_for_cooldown:
            await self.wait(now=now)
        at = _aware_utc(now or self._clock())
        key = self._binding.state_key
        async with self._local_lock:
            for _ in range(_MAX_CAS_ATTEMPTS):
                current = await self._read_or_initialize(at)
                aligned = self._validate_and_align_generation(current, now=at, allow_advance=True)
                expected_rev = int(current.get("revision", 1))

                raw_deadline = aligned.get("cooldown_not_before")
                if isinstance(raw_deadline, str) and raw_deadline:
                    deadline = _aware_utc(datetime.fromisoformat(raw_deadline))
                    if at < deadline:
                        raise ProviderReadCooldownActiveError(
                            f"provider-read cooldown active until {deadline.isoformat()}",
                            retry_not_before=deadline,
                        )

                completed = dict(aligned.get("completed_requests") or {})
                if request_id in completed:
                    entry = completed[request_id]
                    if (
                        not isinstance(entry, Mapping)
                        or entry.get("idempotency_key") != idempotency_key
                    ):
                        raise ValueError(
                            f"provider-read request_id {request_id!r} conflicts with a different "
                            "idempotency_key"
                        )
                    reused_digest = str(entry.get("response_digest") or "")
                    reused_bytes: bytes | None = None
                    raw_body = entry.get("response_utf8")
                    if isinstance(raw_body, str):
                        encoded = raw_body.encode("utf-8")
                        actual_digest = f"sha256:{hashlib.sha256(encoded).hexdigest()}"
                        if actual_digest != reused_digest:
                            raise ProviderReadAdmissionUnavailableError(
                                "retained provider-read response body failed digest verification"
                            )
                        reused_bytes = encoded
                    aligned["requests_reused"] = int(aligned.get("requests_reused", 0)) + 1
                    aligned["revision"] = expected_rev + 1
                    aligned["updated_at"] = at.isoformat()
                    swapped = await self._cas(key, aligned, expected_revision=expected_rev)
                    if not swapped:
                        continue
                    return ProviderReadAdmissionReceipt(
                        source_name=self._binding.source_name,
                        generation_id=self._binding.generation_id,
                        generation_seq=self._binding.generation_seq,
                        request_id=request_id,
                        idempotency_key=idempotency_key,
                        reused=True,
                        reused_response_digest=reused_digest,
                        requests_admitted=int(aligned["requests_admitted"]),
                        requests_reused=int(aligned["requests_reused"]),
                        requests_held=int(aligned["requests_held"]),
                        ambiguous_or_cancelled_count=int(aligned["ambiguous_or_cancelled_count"]),
                        max_requests_per_generation=int(aligned["max_requests_per_generation"]),
                        reused_response_bytes=reused_bytes,
                    )

                in_flight = dict(aligned.get("in_flight_requests") or {})
                if request_id in in_flight:
                    raise ProviderReadAdmissionError(
                        f"provider-read request_id {request_id!r} is already in flight"
                    )

                admitted = int(aligned.get("requests_admitted", 0))
                max_requests = int(aligned.get("max_requests_per_generation", self._max_requests))
                if admitted >= max_requests:
                    aligned["requests_held"] = int(aligned.get("requests_held", 0)) + 1
                    aligned["revision"] = expected_rev + 1
                    aligned["updated_at"] = at.isoformat()
                    swapped = await self._cas(key, aligned, expected_revision=expected_rev)
                    if not swapped:
                        continue
                    raise ProviderReadBudgetExhaustedError(
                        f"provider-read budget exhausted for {self._binding.source_name!r} "
                        f"({admitted}/{max_requests})"
                    )

                in_flight[request_id] = {
                    "admitted_at": at.isoformat(),
                    "idempotency_key": idempotency_key,
                }
                aligned["in_flight_requests"] = in_flight
                aligned["requests_admitted"] = admitted + 1
                aligned["revision"] = expected_rev + 1
                aligned["updated_at"] = at.isoformat()
                swapped = await self._cas(key, aligned, expected_revision=expected_rev)
                if swapped:
                    return ProviderReadAdmissionReceipt(
                        source_name=self._binding.source_name,
                        generation_id=self._binding.generation_id,
                        generation_seq=self._binding.generation_seq,
                        request_id=request_id,
                        idempotency_key=idempotency_key,
                        reused=False,
                        reused_response_digest=None,
                        requests_admitted=int(aligned["requests_admitted"]),
                        requests_reused=int(aligned["requests_reused"]),
                        requests_held=int(aligned["requests_held"]),
                        ambiguous_or_cancelled_count=int(aligned["ambiguous_or_cancelled_count"]),
                        max_requests_per_generation=max_requests,
                    )
        raise ProviderReadAdmissionUnavailableError(
            "provider-read admission CAS contention exceeded maximum attempts"
        )

    async def complete(
        self,
        *,
        request_id: str,
        idempotency_key: str,
        response_digest: str,
        response_payload: bytes | None = None,
        retry_after_seconds: float | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Record completion of an admitted request for within-generation reuse."""

        if _DIGEST_RE.fullmatch(response_digest) is None:
            raise ValueError("response_digest MUST be a canonical sha256 digest")
        stored_utf8: str | None = None
        if response_payload is not None and len(response_payload) <= _MAX_RETAINED_RESPONSE_BYTES:
            payload_digest = f"sha256:{hashlib.sha256(response_payload).hexdigest()}"
            if payload_digest != response_digest:
                raise ValueError("response_payload SHA-256 does not match response_digest")
            stored_utf8 = response_payload.decode("utf-8")
        at = _aware_utc(now or self._clock())
        key = self._binding.state_key
        async with self._local_lock:
            for _ in range(_MAX_CAS_ATTEMPTS):
                current = await self._read_or_initialize(at)
                aligned = self._validate_and_align_generation(current, now=at, allow_advance=False)
                expected_rev = int(current.get("revision", 1))
                in_flight = dict(aligned.get("in_flight_requests") or {})
                completed = dict(aligned.get("completed_requests") or {})
                if request_id not in in_flight:
                    existing = completed.get(request_id)
                    if (
                        isinstance(existing, Mapping)
                        and existing.get("idempotency_key") == idempotency_key
                        and existing.get("response_digest") == response_digest
                    ):
                        return aligned
                    raise ProviderReadAdmissionError(
                        f"provider-read request_id {request_id!r} is not in flight"
                    )
                flight_entry = in_flight.pop(request_id)
                if (
                    isinstance(flight_entry, Mapping)
                    and flight_entry.get("idempotency_key") != idempotency_key
                ):
                    raise ValueError(
                        f"provider-read request_id {request_id!r} idempotency_key mismatch"
                    )
                entry_record: dict[str, Any] = {
                    "completed_at": at.isoformat(),
                    "idempotency_key": idempotency_key,
                    "response_digest": response_digest,
                }
                if stored_utf8 is not None:
                    entry_record["response_utf8"] = stored_utf8
                completed[request_id] = entry_record
                aligned["in_flight_requests"] = in_flight
                aligned["completed_requests"] = completed
                if retry_after_seconds is not None and retry_after_seconds > 0:
                    bounded = min(float(retry_after_seconds), self._max_defer_seconds)
                    candidate = at + timedelta(seconds=bounded)
                    existing_raw = aligned.get("cooldown_not_before")
                    if isinstance(existing_raw, str) and existing_raw:
                        existing_dt = _aware_utc(datetime.fromisoformat(existing_raw))
                        if existing_dt > candidate:
                            candidate = existing_dt
                    aligned["cooldown_not_before"] = candidate.isoformat()
                aligned["revision"] = expected_rev + 1
                aligned["updated_at"] = at.isoformat()
                if await self._cas(key, aligned, expected_revision=expected_rev):
                    return aligned
        raise ProviderReadAdmissionUnavailableError(
            "provider-read completion CAS contention exceeded maximum attempts"
        )

    async def record_ambiguous_or_cancelled(
        self,
        *,
        request_id: str,
        reason: str,
        retry_after_seconds: float | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Account for a cancelled or ambiguous request without replenishing capacity."""

        if not reason.strip():
            raise ValueError("reason MUST be non-empty")
        at = _aware_utc(now or self._clock())
        key = self._binding.state_key
        async with self._local_lock:
            for _ in range(_MAX_CAS_ATTEMPTS):
                current = await self._read_or_initialize(at)
                aligned = self._validate_and_align_generation(current, now=at, allow_advance=False)
                expected_rev = int(current.get("revision", 1))
                in_flight = dict(aligned.get("in_flight_requests") or {})
                if request_id not in in_flight:
                    raise ProviderReadAdmissionError(
                        f"provider-read request_id {request_id!r} is not in flight"
                    )
                in_flight.pop(request_id)
                aligned["in_flight_requests"] = in_flight
                # Never decrement requests_admitted: cancelled/ambiguous calls keep their slot.
                aligned["ambiguous_or_cancelled_count"] = (
                    int(aligned.get("ambiguous_or_cancelled_count", 0)) + 1
                )
                if retry_after_seconds is not None and retry_after_seconds > 0:
                    bounded = min(float(retry_after_seconds), self._max_defer_seconds)
                    candidate = at + timedelta(seconds=bounded)
                    existing_raw = aligned.get("cooldown_not_before")
                    if isinstance(existing_raw, str) and existing_raw:
                        existing_dt = _aware_utc(datetime.fromisoformat(existing_raw))
                        if existing_dt > candidate:
                            candidate = existing_dt
                    aligned["cooldown_not_before"] = candidate.isoformat()
                aligned["revision"] = expected_rev + 1
                aligned["updated_at"] = at.isoformat()
                if await self._cas(key, aligned, expected_revision=expected_rev):
                    return aligned
        raise ProviderReadAdmissionUnavailableError(
            "provider-read cancellation accounting CAS contention exceeded maximum attempts"
        )

    async def snapshot_accounting(self, *, now: datetime | None = None) -> dict[str, Any]:
        """Return a read-only copy of the current durable accounting record."""

        at = _aware_utc(now or self._clock())
        current = await self._read_or_initialize(at)
        return dict(current)

    async def _cas(
        self,
        key: str,
        payload: Mapping[str, Any],
        *,
        expected_revision: int,
    ) -> bool:
        try:
            return await self._state_store.compare_and_set_state(
                key,
                dict(payload),
                expected_revision=expected_revision,
            )
        except Exception as exc:
            raise ProviderReadAdmissionUnavailableError(
                f"provider-read admission CAS failed: {type(exc).__name__}"
            ) from exc


__all__ = [
    "DurableProviderReadAdmissionGate",
    "ProviderReadAdmissionError",
    "ProviderReadAdmissionReceipt",
    "ProviderReadAdmissionUnavailableError",
    "ProviderReadBudgetExhaustedError",
    "ProviderReadCooldownActiveError",
    "ProviderReadScopeBinding",
    "StaleProviderReadGenerationError",
    "complete_collection_generation",
    "resolve_or_allocate_collection_generation",
]
