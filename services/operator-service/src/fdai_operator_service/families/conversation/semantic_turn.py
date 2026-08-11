"""Build versioned semantic-turn envelopes from authorized conversation proposals."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid5

from fdai_operator_service.families.conversation.contracts import ConversationProposal
from fdai_service_contracts import (
    JsonSchemaContractValidator,
    OperatorRole,
    PackageResourceSchemaRegistry,
    SemanticPriorTurn,
    SemanticTurnPrincipal,
    SemanticTurnRequest,
)

_IDENTITY_NAMESPACE = UUID("00000000-0000-0000-0000-000000000000")
_DEFAULT_DEADLINE_SECONDS = 90

Clock = Callable[[], datetime]


class SemanticTurnEnvelopeBuilder:
    """Construct no-authority v1.2 requests with retry-stable identities."""

    def __init__(self, *, clock: Clock | None = None) -> None:
        self._clock = clock or (lambda: datetime.now(UTC))
        self._validator = JsonSchemaContractValidator(PackageResourceSchemaRegistry())

    def build(self, proposal: ConversationProposal) -> dict[str, object]:
        """Validate one authorized ``chat.stream`` proposal as a v1.2 wire envelope."""
        if proposal.operation != "chat.stream":
            raise ValueError("semantic turn builder accepts only chat.stream proposals")
        requested_at = _aware_utc(self._clock())
        identity_seed = f"{proposal.scope.subject_id}\0{proposal.idempotency_key}"
        request_id = str(uuid5(_IDENTITY_NAMESPACE, f"request\0{identity_seed}"))
        session_id = _session_id(proposal, identity_seed)
        turn_id = str(uuid5(_IDENTITY_NAMESPACE, f"turn\0{identity_seed}"))
        semantic_turn = SemanticTurnRequest(
            utterance=_required_text(proposal.body, "prompt"),
            principal=SemanticTurnPrincipal(
                subject_id=proposal.scope.subject_id,
                roles=_authorized_roles(proposal),
            ),
            session_id=session_id,
            turn_id=turn_id,
            turn_sequence=_turn_sequence(proposal.body),
            locale=_optional_text(proposal.body, "locale", default="en"),
            purpose=_optional_text(proposal.body, "purpose", default="operations-review"),
            deadline_at=_deadline(proposal.body, requested_at),
            view_context_digest=_optional_digest(proposal.body.get("view_context")),
            prior_turns=_prior_turns(proposal.body.get("history")),
            cancelled=proposal.cancellation,
        )
        envelope: dict[str, object] = {
            "schema_version": "1.2.0",
            "request_id": request_id,
            "correlation_id": f"semantic-turn:{request_id}",
            "idempotency_key": proposal.idempotency_key,
            "resource_ref": f"operator-conversation:{_digest_text(session_id)[:32]}",
            "request_kind": "semantic_query",
            "requested_at": requested_at.isoformat(),
            "semantic_turn": semantic_turn.model_dump(mode="json", exclude_none=True),
        }
        self._validator.validate("operator-core-request", envelope, version="1.2.0")
        return envelope


def _authorized_roles(proposal: ConversationProposal) -> tuple[OperatorRole, ...]:
    try:
        roles = {OperatorRole(role) for role in proposal.scope.roles}
    except ValueError as exc:
        raise ValueError("principal scope contains an unsupported Operator role") from exc
    if not roles:
        raise ValueError("principal scope MUST contain an authorized Operator role")
    order = {role: index for index, role in enumerate(OperatorRole)}
    return tuple(sorted(roles, key=order.__getitem__))


def _session_id(proposal: ConversationProposal, identity_seed: str) -> str:
    supplied = proposal.body.get("conversation_id")
    if isinstance(supplied, str) and supplied.strip():
        return supplied.strip()
    return str(uuid5(_IDENTITY_NAMESPACE, f"session\0{identity_seed}"))


def _turn_sequence(body: Mapping[str, object]) -> int:
    value = body.get("turn_sequence", 0)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError("turn_sequence MUST be a non-negative integer")
    return value


def _deadline(body: Mapping[str, object], requested_at: datetime) -> datetime:
    value = body.get("deadline_at")
    if value is None:
        return requested_at + timedelta(seconds=_DEFAULT_DEADLINE_SECONDS)
    if not isinstance(value, str):
        raise ValueError("deadline_at MUST be an RFC 3339 string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("deadline_at MUST be an RFC 3339 string") from exc
    deadline = _aware_utc(parsed)
    if deadline <= requested_at:
        raise ValueError("deadline_at MUST be later than requested_at")
    return deadline


def _prior_turns(value: object) -> tuple[SemanticPriorTurn, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ValueError("history MUST be an array")
    turns: list[SemanticPriorTurn] = []
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("history items MUST be objects")
        turns.append(SemanticPriorTurn.model_validate(item))
    return tuple(turns)


def _required_text(body: Mapping[str, object], key: str) -> str:
    value = body.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} MUST be a non-empty string")
    return value.strip()


def _optional_text(body: Mapping[str, object], key: str, *, default: str) -> str:
    value = body.get(key, default)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} MUST be a non-empty string")
    return value.strip()


def _optional_digest(value: object) -> str | None:
    if value is None:
        return None
    encoded = json.dumps(value, allow_nan=False, separators=(",", ":"), sort_keys=True).encode()
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _digest_text(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("semantic turn clock values MUST be timezone-aware")
    return value.astimezone(UTC)


__all__ = ["SemanticTurnEnvelopeBuilder"]
