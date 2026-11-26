"""Durable audited failure streaks for live blast-radius probes."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime

from fdai.shared.providers.blast_probe import ProbeQuery
from fdai.shared.providers.state_store import StateStore

_MAX_CAS_ATTEMPTS = 8
_MAX_STREAK = 1_000_000


@dataclass(frozen=True, slots=True)
class StateStoreProbeFailureStreakSource:
    """Maintain one privacy-bounded CAS counter per probe and target."""

    store: StateStore

    async def get(self, query: ProbeQuery) -> int:
        """Return the current consecutive failure count."""

        state = await self.store.read_state(_state_key(query))
        if state is None:
            return 0
        _, streak = _state_values(state, expected_identity=_identity_digest(query))
        return streak

    async def record_failure(self, query: ProbeQuery) -> int:
        """Atomically increment the streak and append a content-free audit entry."""

        return await self._update(query, reset=False)

    async def record_success(self, query: ProbeQuery) -> None:
        """Reset a nonzero streak without creating success-only state."""

        await self._update(query, reset=True)

    async def _update(self, query: ProbeQuery, *, reset: bool) -> int:
        key = _state_key(query)
        identity = _identity_digest(query)
        for _ in range(_MAX_CAS_ATTEMPTS):
            current = await self.store.read_state(key)
            if current is None:
                if reset:
                    return 0
                revision = 1
                streak = 1
                value = _state_value(identity=identity, revision=revision, streak=streak)
                created = await self.store.write_state_with_audit_if_absent(
                    key,
                    value,
                    _audit_entry(
                        identity=identity,
                        revision=revision,
                        streak=streak,
                        transition="failure",
                    ),
                )
                if created:
                    return streak
                continue

            current_revision, current_streak = _state_values(
                current,
                expected_identity=identity,
            )
            if reset and current_streak == 0:
                return 0
            revision = current_revision + 1
            streak = 0 if reset else min(_MAX_STREAK, current_streak + 1)
            changed = await self.store.compare_and_set_state_with_audit(
                key,
                _state_value(identity=identity, revision=revision, streak=streak),
                expected_revision=current_revision,
                audit_entry=_audit_entry(
                    identity=identity,
                    revision=revision,
                    streak=streak,
                    transition="success" if reset else "failure",
                ),
            )
            if changed:
                return streak
        raise RuntimeError("live blast probe streak update exceeded its CAS retry bound")


def _state_values(
    state: Mapping[str, object],
    *,
    expected_identity: str,
) -> tuple[int, int]:
    revision = state.get("revision")
    streak = state.get("streak")
    if (
        state.get("schema_version") != "1.0.0"
        or state.get("identity_digest") != expected_identity
        or isinstance(revision, bool)
        or not isinstance(revision, int)
        or revision < 1
        or isinstance(streak, bool)
        or not isinstance(streak, int)
        or not 0 <= streak <= _MAX_STREAK
    ):
        raise RuntimeError("live blast probe streak state is malformed")
    return revision, streak


def _state_value(*, identity: str, revision: int, streak: int) -> dict[str, object]:
    return {
        "schema_version": "1.0.0",
        "identity_digest": identity,
        "revision": revision,
        "streak": streak,
    }


def _audit_entry(
    *,
    identity: str,
    revision: int,
    streak: int,
    transition: str,
) -> dict[str, object]:
    return {
        "type": "live_blast_probe_streak",
        "identity_digest": identity,
        "revision": revision,
        "streak": streak,
        "transition": transition,
        "execution_authority": False,
        "recorded_at": datetime.now(tz=UTC).isoformat(),
    }


def _state_key(query: ProbeQuery) -> str:
    return f"live-blast-probe-streak:{_identity_digest(query).removeprefix('sha256:')}"


def _identity_digest(query: ProbeQuery) -> str:
    digest = hashlib.sha256(
        (f"fdai.live-blast-probe-streak.v1\0{query.probe_id}\0{query.target_ref}").encode()
    ).hexdigest()
    return f"sha256:{digest}"


__all__ = ["StateStoreProbeFailureStreakSource"]
