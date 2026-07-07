"""In-memory dict-backed :class:`StateStore` for unit tests + debugger sessions.

Ships in the main package (not under ``tests/``) so a fork MAY also use it
as a lightweight backend for a local, throwaway environment. It is **not**
suitable for production - mutations vanish on process restart.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from copy import deepcopy
from threading import Lock
from typing import Any

from fdai.shared.providers.state_store import StateStore

_GENESIS_HASH = "0" * 64


def _canonical(entry: Mapping[str, Any]) -> str:
    """Deterministic JSON serialization (sorted keys, no whitespace)."""
    return json.dumps(dict(entry), sort_keys=True, separators=(",", ":"), default=str)


def _next_hash(previous: str, entry: Mapping[str, Any]) -> str:
    body = previous + _canonical(entry)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


class InMemoryStateStore(StateStore):
    """Dict-backed :class:`StateStore` with a genuine audit hash-chain.

    The audit chain follows the same rule the real Postgres adapter will
    honor: each entry's :attr:`previous_hash` equals the prior entry's
    ``entry_hash`` (or the genesis constant for the first entry). Callers
    that store the chain can therefore verify tamper-evidence with
    :meth:`verify_chain`.
    """

    def __init__(self) -> None:
        self._state: dict[str, Mapping[str, Any]] = {}
        self._audit: list[dict[str, Any]] = []
        self._incident_transitions: dict[str, dict[str, Any]] = {}
        self._lock = Lock()

    # ---- StateStore Protocol -------------------------------------------------

    async def append_audit_entry(self, entry: Mapping[str, Any]) -> None:
        with self._lock:
            previous = self._audit[-1]["entry_hash"] if self._audit else _GENESIS_HASH
            stored: dict[str, Any] = {
                "entry": deepcopy(dict(entry)),
                "previous_hash": previous,
                "entry_hash": _next_hash(previous, entry),
            }
            self._audit.append(stored)

    async def read_state(self, key: str) -> Mapping[str, Any] | None:
        return deepcopy(self._state.get(key)) if key in self._state else None

    async def write_state(self, key: str, value: Mapping[str, Any]) -> None:
        self._state[key] = deepcopy(dict(value))

    async def append_incident_transition(self, entry: Mapping[str, Any]) -> None:
        """Append one incident transition to the shared audit chain.

        Idempotent on ``entry["idempotency_key"]``: a re-delivery of
        the same transition is a no-op that does NOT extend the audit
        chain (matches the Postgres adapter's UNIQUE constraint
        contract).
        """
        key = str(entry.get("idempotency_key") or "")
        if not key:
            raise ValueError("incident transition MUST carry a non-empty idempotency_key")
        with self._lock:
            if key in self._incident_transitions:
                return
            self._incident_transitions[key] = deepcopy(dict(entry))
        # Route through the standard audit-chain path so hash-chain
        # verification stays global and postmortem timelines see the
        # transitions.
        await self.append_audit_entry(entry)

    # ---- Test helpers --------------------------------------------------------

    @property
    def incident_transitions(self) -> Iterable[Mapping[str, Any]]:
        """Read-only view of every incident transition seen (deduped by key)."""
        return tuple(deepcopy(e) for e in self._incident_transitions.values())

    @property
    def audit_entries(self) -> Iterable[Mapping[str, Any]]:
        """Read-only view of the audit chain (deep-copied so callers cannot mutate)."""
        return tuple(deepcopy(e) for e in self._audit)

    def verify_chain(self) -> bool:
        """Recompute every hash and confirm the chain is intact."""
        previous = _GENESIS_HASH
        for record in self._audit:
            if record["previous_hash"] != previous:
                return False
            expected = _next_hash(previous, record["entry"])
            if record["entry_hash"] != expected:
                return False
            previous = record["entry_hash"]
        return True


__all__ = ["InMemoryStateStore"]
