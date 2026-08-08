"""Chat-session primitives for the ontology-grounded assurance twin.

Ships the dataclasses + Protocol seams so a fork (or a future upstream
UI) can wire a chat surface on top of the assurance twin's
NL-to-typed-query pipeline. The actual browser chat UI is out of scope
for upstream today - what upstream ships is the audit-safe backbone:

- :class:`ChatMessage` - one turn in a conversation (user or assistant).
- :class:`ChatSession` - immutable snapshot: session id, RBAC principal,
  declared purposes, message history, correlation id to the audit log.
- :class:`ChatSessionStore` Protocol - fork-plugged persistence
  (Postgres, Redis, in-memory dev).

Design invariants
-----------------
- Every assistant message MUST carry a ``grounding`` field listing the
  ontology query paths that backed the answer. An answer whose
  grounding is empty is a Bug (the assurance-twin abstain contract
  MUST have short-circuited before the message was formed).
- Every session MUST carry the caller's declared purposes so the
  projection ACL (:mod:`fdai.shared.ontology.acl`) applies the same
  redaction the Operator API panels apply.
- Sessions are immutable snapshots: adding a turn produces a new
  :class:`ChatSession` via :meth:`ChatSession.with_message`. A store
  that mutates in place violates the audit contract.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol, runtime_checkable

from fdai.shared.contracts.models import CeilingRole


class ChatRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"


@dataclass(frozen=True, slots=True)
class ChatMessage:
    """One turn in a conversation."""

    role: ChatRole
    text: str
    at: datetime
    """RFC 3339 UTC timestamp."""

    grounding: tuple[str, ...] = ()
    """Ontology query paths cited (e.g. ``["Resource[type=object-storage].props.public_access"]``).

    MUST be non-empty for assistant messages; empty on user messages
    (they are questions, not answers).
    """

    abstain_reason: str | None = None
    """When set, the assistant declined to answer (grounding missing,
    policy escape, ACL redaction). Included so the audit trail records
    why the model declined."""

    def as_json(self) -> dict[str, object]:
        return {
            "role": self.role.value,
            "text": self.text,
            "at": self.at.isoformat(),
            "grounding": list(self.grounding),
            "abstain_reason": self.abstain_reason,
        }


@dataclass(frozen=True, slots=True)
class ChatSession:
    """Immutable snapshot of one operator's chat with the assurance twin."""

    session_id: str
    caller_id: str
    caller_role: CeilingRole
    declared_purposes: frozenset[str]
    correlation_id: str
    """Ties every message in this session to one audit-log correlation."""

    created_at: datetime
    messages: tuple[ChatMessage, ...] = ()

    def with_message(self, message: ChatMessage) -> ChatSession:
        """Return a new session with ``message`` appended."""
        return replace(self, messages=self.messages + (message,))

    @classmethod
    def new(
        cls,
        *,
        session_id: str,
        caller_id: str,
        caller_role: CeilingRole,
        declared_purposes: frozenset[str],
        correlation_id: str,
    ) -> ChatSession:
        return cls(
            session_id=session_id,
            caller_id=caller_id,
            caller_role=caller_role,
            declared_purposes=declared_purposes,
            correlation_id=correlation_id,
            created_at=datetime.now(tz=UTC),
        )

    def as_json(self) -> dict[str, object]:
        return {
            "session_id": self.session_id,
            "caller_id": self.caller_id,
            "caller_role": self.caller_role.value,
            "declared_purposes": sorted(self.declared_purposes),
            "correlation_id": self.correlation_id,
            "created_at": self.created_at.isoformat(),
            "messages": [m.as_json() for m in self.messages],
        }


@runtime_checkable
class ChatSessionStore(Protocol):
    """Fork-injected persistence seam for chat sessions."""

    async def load(self, session_id: str) -> ChatSession | None:
        """Return the session or ``None`` when unknown."""
        ...

    async def save(self, session: ChatSession) -> None:
        """Persist the immutable snapshot; the caller MUST NOT mutate it after saving."""
        ...


@dataclass(slots=True)
class InMemoryChatSessionStore:
    """Fixture-grade store used by tests and the local dev harness."""

    _sessions: dict[str, ChatSession] = field(default_factory=dict)

    async def load(self, session_id: str) -> ChatSession | None:
        return self._sessions.get(session_id)

    async def save(self, session: ChatSession) -> None:
        self._sessions[session.session_id] = session


class GroundingRequiredError(ValueError):
    """Raised when an assistant message is added without any grounding.

    The assurance twin invariant says: no grounding, no answer. This
    guard fires locally so a bug in a fork's twin adapter cannot
    silently ship an ungrounded answer.
    """


def append_assistant_answer(
    session: ChatSession,
    *,
    text: str,
    grounding: Sequence[str],
    at: datetime | None = None,
) -> ChatSession:
    """Convenience: validate + append an assistant answer to a session.

    Empty ``grounding`` raises :class:`GroundingRequiredError` unless
    ``text`` is empty (the assurance twin's abstain path returns an
    empty answer body; use :func:`append_assistant_abstain` instead).
    """
    if not grounding:
        raise GroundingRequiredError("assistant message MUST cite at least one ontology query path")
    message = ChatMessage(
        role=ChatRole.ASSISTANT,
        text=text,
        at=at or datetime.now(tz=UTC),
        grounding=tuple(grounding),
    )
    return session.with_message(message)


def append_assistant_abstain(
    session: ChatSession,
    *,
    reason: str,
    at: datetime | None = None,
) -> ChatSession:
    """Convenience: append an abstain message with a human-legible reason."""
    if not reason:
        raise ValueError("abstain MUST carry a non-empty reason")
    message = ChatMessage(
        role=ChatRole.ASSISTANT,
        text="",
        at=at or datetime.now(tz=UTC),
        grounding=(),
        abstain_reason=reason,
    )
    return session.with_message(message)


def append_user_question(
    session: ChatSession,
    *,
    text: str,
    at: datetime | None = None,
) -> ChatSession:
    """Convenience: append a user question."""
    if not text.strip():
        raise ValueError("user question MUST be non-empty")
    message = ChatMessage(
        role=ChatRole.USER,
        text=text,
        at=at or datetime.now(tz=UTC),
    )
    return session.with_message(message)


__all__ = [
    "ChatMessage",
    "ChatRole",
    "ChatSession",
    "ChatSessionStore",
    "GroundingRequiredError",
    "InMemoryChatSessionStore",
    "append_assistant_abstain",
    "append_assistant_answer",
    "append_user_question",
]
