"""Immutable, audit-atomic persistence for shadow-only decision contexts."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict

from fdai.core.mscp_profile.decision_context import MscpDecisionContext
from fdai.core.mscp_profile.readiness import MscpCandidateKey
from fdai.shared.providers.state_store import StateStore

_STATE_PREFIX = "mscp:decision-context:"


class MscpDecisionContextConflictError(RuntimeError):
    """One decision identity already has a different immutable projection."""


class StateStoreMscpDecisionContext:
    """Write one digest-bound context with audit and replay it after restart.

    This store cannot replace a prior projection or activate a profile. A
    conflicting retry must start a new decision identity after owner rereads.
    """

    def __init__(self, state_store: StateStore) -> None:
        self._state_store = state_store

    async def record(self, context: MscpDecisionContext) -> MscpDecisionContext:
        """Atomically create the first state and audit record; collapse retries."""

        if MscpDecisionContext.from_mapping(context.to_mapping()) != context:
            raise ValueError("MSCP decision context is not a valid immutable projection")
        key = _state_key(context.candidate, context.decision_id)
        created = await self._state_store.write_state_with_audit_if_absent(
            key,
            context.to_mapping(),
            {
                "kind": "mscp.decision_context.recorded",
                "decision_digest": key.removeprefix(_STATE_PREFIX),
                "context_digest": context.digest,
                "disposition": context.disposition,
                "reasons": list(context.reasons),
                "execution_authority": False,
            },
        )
        if not created:
            previous = await self.get(context.candidate, context.decision_id)
            if previous != context:
                raise MscpDecisionContextConflictError(
                    "MSCP decision context changed for an immutable decision"
                )
        return context

    async def get(self, candidate: MscpCandidateKey, decision_id: str) -> MscpDecisionContext:
        """Read and verify the original projection without consulting live owners."""

        value = await self._state_store.read_state(_state_key(candidate, decision_id))
        if value is None:
            raise KeyError("MSCP decision context is unavailable")
        context = MscpDecisionContext.from_mapping(value)
        if context.candidate != candidate or context.decision_id != decision_id:
            raise ValueError("MSCP decision context identity does not match its key")
        return context


def _state_key(candidate: MscpCandidateKey, decision_id: str) -> str:
    if not isinstance(decision_id, str) or not decision_id.strip() or len(decision_id) > 256:
        raise ValueError("MSCP decision id MUST be bounded text")
    identity = json.dumps(
        {"candidate": asdict(candidate), "decision_id": decision_id},
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return _STATE_PREFIX + hashlib.sha256(identity).hexdigest()
