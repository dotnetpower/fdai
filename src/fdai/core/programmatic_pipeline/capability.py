"""Run-bound random capability tokens for pipeline broker calls."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta


class PipelineCapabilityError(PermissionError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class PipelineCapability:
    token: str
    run_id: str
    expires_at: datetime
    allowed_tools: frozenset[str]
    max_calls: int
    max_input_bytes: int


@dataclass(slots=True)
class _CapabilityState:
    token_digest: str
    expires_at: datetime
    allowed_tools: frozenset[str]
    max_calls: int
    max_input_bytes: int
    call_ids: set[str]


class PipelineCapabilityAuthority:
    def __init__(self, *, clock: Callable[[], datetime] | None = None) -> None:
        self._clock = clock or (lambda: datetime.now(tz=UTC))
        self._states: dict[str, _CapabilityState] = {}
        self._runs_by_digest: dict[str, str] = {}

    def issue(
        self,
        *,
        run_id: str,
        allowed_tools: frozenset[str],
        ttl_seconds: float,
        max_calls: int,
        max_input_bytes: int,
    ) -> PipelineCapability:
        if run_id in self._states:
            raise PipelineCapabilityError("duplicate_run", "capability already issued for run")
        token = secrets.token_urlsafe(32)
        digest = _digest(token)
        expires_at = self._clock() + timedelta(seconds=ttl_seconds)
        self._states[run_id] = _CapabilityState(
            token_digest=digest,
            expires_at=expires_at,
            allowed_tools=allowed_tools,
            max_calls=max_calls,
            max_input_bytes=max_input_bytes,
            call_ids=set(),
        )
        self._runs_by_digest[digest] = run_id
        return PipelineCapability(
            token=token,
            run_id=run_id,
            expires_at=expires_at,
            allowed_tools=allowed_tools,
            max_calls=max_calls,
            max_input_bytes=max_input_bytes,
        )

    def authorize(
        self,
        *,
        run_id: str,
        token: str,
        call_id: str,
        tool_id: str,
        input_bytes: int,
    ) -> int:
        state = self._states.get(run_id)
        digest = _digest(token)
        if state is None:
            if digest in self._runs_by_digest:
                raise PipelineCapabilityError("wrong_run", "capability belongs to another run")
            raise PipelineCapabilityError("forged_token", "capability is not recognized")
        if not hmac.compare_digest(state.token_digest, digest):
            if digest in self._runs_by_digest:
                raise PipelineCapabilityError("wrong_run", "capability belongs to another run")
            raise PipelineCapabilityError("forged_token", "capability is not recognized")
        if self._clock() >= state.expires_at:
            raise PipelineCapabilityError("expired_token", "capability has expired")
        if tool_id not in state.allowed_tools:
            raise PipelineCapabilityError("tool_forbidden", "tool is outside the capability")
        if input_bytes > state.max_input_bytes:
            raise PipelineCapabilityError("input_too_large", "tool input exceeds the capability")
        if call_id in state.call_ids:
            raise PipelineCapabilityError("replay", "call_id has already been used")
        if len(state.call_ids) >= state.max_calls:
            raise PipelineCapabilityError("call_limit", "tool call limit is exhausted")
        state.call_ids.add(call_id)
        return len(state.call_ids)

    def revoke(self, run_id: str) -> None:
        state = self._states.pop(run_id, None)
        if state is not None:
            self._runs_by_digest.pop(state.token_digest, None)


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


__all__ = [
    "PipelineCapability",
    "PipelineCapabilityAuthority",
    "PipelineCapabilityError",
]
