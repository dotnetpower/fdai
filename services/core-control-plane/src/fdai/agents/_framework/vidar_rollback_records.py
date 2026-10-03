"""Rollback record contracts and durable state helpers for Vidar."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Awaitable, Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from fdai.agents._framework import vidar_rehearsal
from fdai.agents._framework.action_run_identity import is_action_run_identity

_ROLLBACK_STATE_PREFIX = "pantheon/vidar/rollback"
_DR_CONTRACT_DECISION_PREFIX = "pantheon/vidar/dr-contract-decisions/"
_REHEARSAL_STATE_PREFIX = "pantheon/vidar/rehearsal/"
_DEFAULT_CLAIM_LEASE = timedelta(minutes=5)
_MAX_CLAIM_LEASE = timedelta(hours=1)
_DEFAULT_REHEARSAL_TIMEOUT_SECONDS = 30.0
_MAX_ROLLBACK_REF_LENGTH = 2_048
_ROLLBACK_COMMAND_FIELDS = (
    "correlation_id",
    "action_run_identity",
    "idempotency_key",
    "action_idempotency_key",
    "action_id",
    "action_type",
    "resource_id",
    "state",
    "shadow_mode",
    "resolved_autonomy_ceiling",
    "outcome",
    "operational_success",
    "effect_verification_status",
    "verdict",
    "params",
    "quorum_required",
    "original_quorum_required",
    "effective_quorum_required",
    "development_authority",
    "initiator_principal",
    "rollback_contract",
    "rollback_ref",
    "decision_case",
    "operational_context",
    "workflow_action",
    "kinetic_proposal",
    "prospective_lineage",
    "execution_audit_receipt",
    "approval_expires_at",
)


def _kpi_ratio(numerator: int, denominator: int, *, unit: str = "ratio") -> dict[str, object]:
    if denominator <= 0:
        return {
            "value": None,
            "evidence_state": "insufficient_sample",
            "numerator": numerator,
            "denominator": denominator,
            "unit": unit,
        }
    return {
        "value": numerator / denominator,
        "evidence_state": "measured",
        "numerator": numerator,
        "denominator": denominator,
        "unit": unit,
    }


@dataclass(frozen=True, slots=True)
class RollbackRecord:
    correlation_id: str
    action_run_identity: str
    action_type: str
    resource_id: str | None
    contract: str
    state: str  # succeeded | failed | refused | execution_unknown
    notes: str = ""
    rollback_ref: str | None = None


RollbackExecutor = Callable[[dict[str, Any]], Awaitable[str | None]]
RollbackRehearsalPort = vidar_rehearsal.RollbackRehearsalPort


@dataclass(frozen=True, slots=True)
class _CachedRollback:
    request_digest: str
    record: RollbackRecord


@dataclass(slots=True)
class _RollbackLockEntry:
    lock: asyncio.Lock
    users: int = 0


class RollbackClaimInProgressError(RuntimeError):
    """Raised so transport retry or DLQ retains a still-leased rollback."""


def _resource_id(action_run: Mapping[str, Any]) -> str | None:
    value = action_run.get("resource_id")
    return value if isinstance(value, str) and value else None


def _rollback_idempotency_key(rec: RollbackRecord) -> str:
    return f"{rec.correlation_id}:{rec.action_run_identity[7:19]}:rollback:{rec.state}"


def _rollback_state_key(
    correlation_id: str,
    suffix: str,
    action_run_identity: str,
) -> str:
    digest = hashlib.sha256(correlation_id.encode("utf-8")).hexdigest()
    identity_scope = action_run_identity.removeprefix("sha256:")
    return f"{_ROLLBACK_STATE_PREFIX}/{digest}/{identity_scope}/{suffix}"


def _dr_contract_decision_key(action_run_identity: str) -> str:
    digest = hashlib.sha256(action_run_identity.encode("utf-8")).hexdigest()
    return f"{_DR_CONTRACT_DECISION_PREFIX}{digest}"


def _rollback_request_digest(action_run: Mapping[str, Any], *, contract: str) -> str:
    encoded = json.dumps(
        _rollback_command(action_run, contract=contract),
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _rollback_command(
    action_run: Mapping[str, Any],
    *,
    contract: str,
) -> dict[str, Any]:
    command = {
        field: deepcopy(action_run[field])
        for field in _ROLLBACK_COMMAND_FIELDS
        if field in action_run
    }
    if action_run.get("development_authority") is None:
        for field in (
            "original_quorum_required",
            "effective_quorum_required",
            "development_authority",
        ):
            command.pop(field, None)
    command["rollback_contract"] = contract
    return command


def _rollback_record_state(
    rec: RollbackRecord,
    *,
    request_digest: str,
    claim_owner_token: str,
    lease_expires_at: datetime,
    completed_by_owner_token: str,
) -> dict[str, Any]:
    if not _is_sha256_digest(request_digest):
        raise ValueError("rollback request_digest MUST be a sha256 digest")
    if not _is_owner_token(claim_owner_token) or not _is_owner_token(completed_by_owner_token):
        raise ValueError("rollback terminal owner token is malformed")
    if lease_expires_at.tzinfo is None or lease_expires_at.utcoffset() is None:
        raise ValueError("rollback terminal lease expiry MUST include timezone")
    if (
        not rec.correlation_id
        or len(rec.correlation_id) > 512
        or not rec.action_type
        or len(rec.action_type) > 256
        or not rec.contract
        or len(rec.contract) > 128
        or rec.resource_id is not None
        and (not rec.resource_id or len(rec.resource_id) > 2_048)
        or rec.state not in {"succeeded", "failed", "execution_unknown"}
        or len(rec.notes) > 1_024
        or (
            rec.state == "succeeded"
            and (
                rec.rollback_ref is None
                or _normalize_rollback_ref(rec.rollback_ref) != rec.rollback_ref
            )
        )
        or (rec.state != "succeeded" and rec.rollback_ref is not None)
    ):
        raise ValueError("rollback terminal record fields are malformed")
    return {
        "schema_version": "1.0.0",
        "revision": 2,
        "status": "terminal",
        "correlation_id": rec.correlation_id,
        "action_run_identity": rec.action_run_identity,
        "request_digest": request_digest,
        "claim_owner_token": claim_owner_token,
        "lease_expires_at": lease_expires_at.isoformat(),
        "completed_by_owner_token": completed_by_owner_token,
        "action_type": rec.action_type,
        "resource_id": rec.resource_id,
        "contract": rec.contract,
        "state": rec.state,
        "notes": rec.notes,
        "rollback_ref": rec.rollback_ref,
    }


def _execution_unknown_rollback_record(
    action_run: Mapping[str, Any],
    correlation_id: str,
    *,
    contract: str,
    action_run_identity: str,
    notes: str,
) -> RollbackRecord:
    return RollbackRecord(
        correlation_id=correlation_id,
        action_run_identity=action_run_identity,
        action_type=str(action_run.get("action_type", "")),
        resource_id=_resource_id(action_run),
        contract=contract,
        state="execution_unknown",
        notes=notes,
    )


def _validate_rollback_state_identity(
    stored: Mapping[str, Any],
    *,
    correlation_id: str,
    action_run_identity: str,
    request_digest: str,
) -> None:
    if (
        stored.get("correlation_id") != correlation_id
        or stored.get("action_run_identity") != action_run_identity
        or stored.get("request_digest") != request_digest
    ):
        raise ValueError("rollback correlation collides with different action identity")


def _rollback_claim_lease(stored: Mapping[str, Any]) -> tuple[str, datetime]:
    owner_token = stored.get("owner_token")
    lease_expires_at = stored.get("lease_expires_at")
    if (
        stored.get("schema_version") != "1.0.0"
        or stored.get("revision") != 1
        or stored.get("status") != "in_progress"
        or not _is_owner_token(owner_token)
        or not isinstance(lease_expires_at, str)
    ):
        raise RuntimeError("stored rollback claim is malformed")
    return str(owner_token), _parse_lease_expiry(lease_expires_at)


def _clock_now(clock: Callable[[], datetime]) -> datetime:
    value = clock()
    if value.tzinfo is None or value.utcoffset() is None:
        raise RuntimeError("Vidar clock MUST return a timezone-aware datetime")
    return value.astimezone(UTC)


def _is_owner_token(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 32
        and all(character in "0123456789abcdef" for character in value)
    )


def _is_sha256_digest(value: object) -> bool:
    return (
        isinstance(value, str)
        and value.startswith("sha256:")
        and len(value) == 71
        and all(character in "0123456789abcdef" for character in value[7:])
    )


def _normalize_rollback_ref(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if not normalized or len(normalized) > _MAX_ROLLBACK_REF_LENGTH:
        return None
    return normalized


def _parse_lease_expiry(value: str) -> datetime:
    try:
        parsed_expiry = datetime.fromisoformat(value)
    except ValueError as exc:
        raise RuntimeError("stored rollback state has invalid lease expiry") from exc
    if parsed_expiry.tzinfo is None or parsed_expiry.utcoffset() is None:
        raise RuntimeError("stored rollback state lease expiry MUST include timezone")
    return parsed_expiry.astimezone(UTC)


def _parse_rollback_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(UTC)


def _rollback_publication_receipt_matches(
    stored: Mapping[str, Any] | None,
    rec: RollbackRecord,
    *,
    status: str,
) -> bool:
    if stored is None:
        return False
    return (
        stored.get("correlation_id") == rec.correlation_id
        and stored.get("action_run_identity") == rec.action_run_identity
        and stored.get("idempotency_key") == _rollback_idempotency_key(rec)
        and stored.get("state") == rec.state
        and stored.get("status") == status
    )


def _rollback_record_from_state(stored: Mapping[str, Any]) -> RollbackRecord:
    correlation_id = stored.get("correlation_id")
    action_run_identity = stored.get("action_run_identity")
    action_type = stored.get("action_type")
    contract = stored.get("contract")
    notes = stored.get("notes")
    request_digest = stored.get("request_digest")
    claim_owner_token = stored.get("claim_owner_token")
    completed_by_owner_token = stored.get("completed_by_owner_token")
    lease_expires_at = stored.get("lease_expires_at")
    if (
        stored.get("schema_version") != "1.0.0"
        or stored.get("revision") != 2
        or stored.get("status") != "terminal"
        or not isinstance(correlation_id, str)
        or not is_action_run_identity(action_run_identity)
        or not isinstance(action_type, str)
        or not isinstance(contract, str)
        or not isinstance(notes, str)
        or not _is_sha256_digest(request_digest)
        or not _is_owner_token(claim_owner_token)
        or not _is_owner_token(completed_by_owner_token)
        or not isinstance(lease_expires_at, str)
    ):
        raise RuntimeError("stored rollback terminal record is malformed")
    resource_id = stored.get("resource_id")
    rollback_ref = stored.get("rollback_ref")
    rec = RollbackRecord(
        correlation_id=correlation_id,
        action_run_identity=str(action_run_identity),
        action_type=action_type,
        resource_id=resource_id if isinstance(resource_id, str) else None,
        contract=contract,
        state=str(stored["state"]),
        notes=notes,
        rollback_ref=rollback_ref if isinstance(rollback_ref, str) else None,
    )
    try:
        canonical = _rollback_record_state(
            rec,
            request_digest=str(request_digest),
            claim_owner_token=str(claim_owner_token),
            lease_expires_at=_parse_lease_expiry(lease_expires_at),
            completed_by_owner_token=str(completed_by_owner_token),
        )
    except (RuntimeError, ValueError) as exc:
        raise RuntimeError("stored rollback terminal record is malformed") from exc
    if dict(stored) != canonical:
        raise RuntimeError("stored rollback terminal record is malformed")
    return rec


__all__ = [
    "RollbackClaimInProgressError",
    "RollbackExecutor",
    "RollbackRecord",
    "RollbackRehearsalPort",
    "_CachedRollback",
    "_DEFAULT_CLAIM_LEASE",
    "_DEFAULT_REHEARSAL_TIMEOUT_SECONDS",
    "_DR_CONTRACT_DECISION_PREFIX",
    "_MAX_CLAIM_LEASE",
    "_MAX_ROLLBACK_REF_LENGTH",
    "_REHEARSAL_STATE_PREFIX",
    "_ROLLBACK_STATE_PREFIX",
    "_RollbackLockEntry",
    "_clock_now",
    "_dr_contract_decision_key",
    "_execution_unknown_rollback_record",
    "_normalize_rollback_ref",
    "_resource_id",
    "_rollback_claim_lease",
    "_rollback_command",
    "_rollback_idempotency_key",
    "_rollback_publication_receipt_matches",
    "_rollback_record_from_state",
    "_rollback_record_state",
    "_rollback_request_digest",
    "_rollback_state_key",
    "_validate_rollback_state_identity",
]
