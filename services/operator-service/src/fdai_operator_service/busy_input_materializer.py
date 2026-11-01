"""Operator API consumer and authoritative projection materializer for busy-input modes."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any

from fdai_operator_service.families.conversation.contracts import ConversationBoundaryError

ALLOWED_MODES = frozenset({"queue", "interrupt", "steer"})
ALLOWED_KINDS = frozenset({"prose", "approval", "denial", "emergency_stop"})
MAX_PENDING_ITEMS = 32
MAX_CONTENT_BYTES = 4_000


@dataclass(frozen=True, slots=True)
class BusyInputItemProjection:
    input_id: str
    idempotency_key: str
    sequence: int
    content: str
    kind: str
    disposition: str
    status: str
    received_at: str
    expires_at: str


@dataclass(frozen=True, slots=True)
class BusySessionRecord:
    session_id: str
    owner_principal_id: str
    mode: str
    revision: int
    active_turn_id: str | None
    pending: tuple[BusyInputItemProjection, ...] = ()


@dataclass(frozen=True, slots=True)
class _IdempotentBusySubmission:
    content: str
    kind: str
    submitted: dict[str, object]


class BusyInputOperatorMaterializer:
    """Authoritative Operator API materializer for inspect, submit, mode change, and cancel."""

    def __init__(self) -> None:
        self._sessions: dict[str, BusySessionRecord] = {}
        self._idempotency: dict[tuple[str, str], _IdempotentBusySubmission] = {}

    def ensure_session(
        self,
        *,
        session_id: str,
        owner_principal_id: str,
        mode: str = "queue",
        active_turn_id: str | None = None,
    ) -> BusySessionRecord:
        sid = _non_empty(session_id, "session_id")
        owner = _non_empty(owner_principal_id, "owner_principal_id")
        if mode not in ALLOWED_MODES:
            raise ConversationBoundaryError(400, "invalid_busy_mode", "unsupported busy-input mode")
        existing = self._sessions.get(sid)
        if existing is not None:
            if existing.owner_principal_id != owner:
                raise ConversationBoundaryError(404, "session_not_found", "session not found")
            return existing
        created = BusySessionRecord(
            session_id=sid,
            owner_principal_id=owner,
            mode=mode,
            revision=1,
            active_turn_id=active_turn_id,
        )
        self._sessions[sid] = created
        return created

    def inspect(
        self,
        *,
        session_id: str,
        principal_id: str,
    ) -> dict[str, object]:
        record = self._require_owned_session(session_id=session_id, principal_id=principal_id)
        return self._project(record)

    def set_mode(
        self,
        *,
        session_id: str,
        principal_id: str,
        mode: str,
        expected_revision: int,
    ) -> dict[str, object]:
        record = self._require_owned_session(session_id=session_id, principal_id=principal_id)
        if mode not in ALLOWED_MODES:
            raise ConversationBoundaryError(400, "invalid_busy_mode", "unsupported busy-input mode")
        if type(expected_revision) is not int or expected_revision != record.revision:
            raise ConversationBoundaryError(
                409,
                "busy_input_revision_conflict",
                "session revision conflict",
            )
        updated = replace(record, mode=mode, revision=record.revision + 1)
        self._sessions[record.session_id] = updated
        return self._project(updated)

    def submit(
        self,
        *,
        session_id: str,
        principal_id: str,
        payload: Mapping[str, Any],
        now: datetime | None = None,
    ) -> dict[str, object]:
        record = self._require_owned_session(session_id=session_id, principal_id=principal_id)
        idempotency_key = _non_empty(payload.get("idempotency_key"), "idempotency_key")
        input_id = _non_empty(payload.get("input_id"), "input_id")
        content = _non_empty(payload.get("content"), "content")
        if len(content.encode("utf-8")) > MAX_CONTENT_BYTES:
            raise ConversationBoundaryError(
                400,
                "busy_input_too_large",
                "busy input content exceeds 4000 bytes",
            )
        kind = str(payload.get("kind") or "prose").strip().lower()
        if kind not in ALLOWED_KINDS:
            raise ConversationBoundaryError(400, "invalid_busy_kind", "unsupported input kind")

        idem_pair = (record.session_id, idempotency_key)
        cached = self._idempotency.get(idem_pair)
        if cached is not None:
            if cached.content != content or cached.kind != kind:
                raise ConversationBoundaryError(
                    409,
                    "busy_input_idempotency_conflict",
                    "idempotency_key reused with different busy-input payload",
                )
            return {
                "session": self._project(record),
                "submitted": dict(cached.submitted),
                "duplicate": True,
                "execution_authority": "none",
            }

        if len(record.pending) >= MAX_PENDING_ITEMS:
            raise ConversationBoundaryError(
                429,
                "queue_capacity_exceeded",
                "busy-input pending queue capacity reached",
            )

        timestamp = now or datetime.now(UTC)
        expires = timestamp + timedelta(minutes=5)
        if kind == "emergency_stop":
            disposition = "interrupting"
        elif record.active_turn_id is None:
            disposition = "queued"
        elif record.mode == "interrupt":
            disposition = "interrupting"
        elif record.mode == "steer":
            disposition = "steered"
        else:
            disposition = "queued"

        item = BusyInputItemProjection(
            input_id=input_id,
            idempotency_key=idempotency_key,
            sequence=len(record.pending) + 1,
            content=content,
            kind=kind,
            disposition=disposition,
            status="pending",
            received_at=timestamp.isoformat(),
            expires_at=expires.isoformat(),
        )
        updated = replace(
            record,
            revision=record.revision + 1,
            active_turn_id=None if disposition == "interrupting" else record.active_turn_id,
            pending=(*record.pending, item),
        )
        self._sessions[record.session_id] = updated
        submitted_receipt: dict[str, object] = {
            "input_id": item.input_id,
            "idempotency_key": item.idempotency_key,
            "sequence": item.sequence,
            "disposition": item.disposition,
            "status": item.status,
        }
        response: dict[str, object] = {
            "session": self._project(updated),
            "submitted": submitted_receipt,
            "duplicate": False,
            "execution_authority": "none",
        }
        self._idempotency[idem_pair] = _IdempotentBusySubmission(
            content=content,
            kind=kind,
            submitted=submitted_receipt,
        )
        return response

    def cancel_current(
        self,
        *,
        session_id: str,
        principal_id: str,
        expected_revision: int,
    ) -> dict[str, object]:
        record = self._require_owned_session(session_id=session_id, principal_id=principal_id)
        if type(expected_revision) is not int or expected_revision != record.revision:
            raise ConversationBoundaryError(
                409,
                "busy_input_revision_conflict",
                "session revision conflict",
            )
        cancelled = record.active_turn_id is not None
        updated = replace(
            record,
            active_turn_id=None,
            revision=record.revision + (1 if cancelled else 0),
        )
        self._sessions[record.session_id] = updated
        return {
            "cancelled": cancelled,
            "session": self._project(updated),
            "execution_authority": "none",
        }

    def _require_owned_session(self, *, session_id: str, principal_id: str) -> BusySessionRecord:
        sid = _non_empty(session_id, "session_id")
        principal = _non_empty(principal_id, "principal_id")
        record = self._sessions.get(sid)
        if record is None or record.owner_principal_id != principal:
            raise ConversationBoundaryError(404, "session_not_found", "session not found")
        return record

    @staticmethod
    def _project(record: BusySessionRecord) -> dict[str, object]:
        return {
            "session_id": record.session_id,
            "mode": record.mode,
            "revision": record.revision,
            "active_turn_id": record.active_turn_id,
            "pending_count": len(record.pending),
            "pending": [
                {
                    "input_id": item.input_id,
                    "idempotency_key": item.idempotency_key,
                    "sequence": item.sequence,
                    "content": item.content,
                    "kind": item.kind,
                    "disposition": item.disposition,
                    "status": item.status,
                    "received_at": item.received_at,
                    "expires_at": item.expires_at,
                }
                for item in record.pending
            ],
            "read_only_projection": True,
            "execution_authority": "none",
        }


def _non_empty(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConversationBoundaryError(400, f"invalid_{name}", f"{name} must be non-empty")
    return value.strip()


__all__ = [
    "ALLOWED_KINDS",
    "ALLOWED_MODES",
    "BusyInputItemProjection",
    "BusyInputOperatorMaterializer",
    "BusySessionRecord",
]
