"""Atomic PostgreSQL persistence for one exact human HIL decision."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

import psycopg
from fdai_service_contracts import OperatorRole
from psycopg.rows import dict_row

from fdai_operator_service.postgres_family_store import (
    PostgresFamilyStoreConfig,
    PostgresFamilyStoreUnavailable,
    PostgresProposalConflict,
    StoredProposal,
)


class PostgresHilDecisionExpiredError(RuntimeError):
    """A pending human approval expired before its guarded decision commit."""


class PostgresHilDecisionNotFoundError(RuntimeError):
    """The exact pending human approval does not exist."""


class PostgresHilDecisionPermissionError(RuntimeError):
    """The guarded approval context rejects the authenticated human."""


class HilDecisionStore(Protocol):
    """Persist one exact HIL decision and its outbox in a single commit."""

    async def append_hil_decision(
        self,
        *,
        approval_id: str,
        idempotency_key: str,
        action_hash: str,
        decision: str,
        approver_oid: str,
        approver_roles: frozenset[OperatorRole],
        justification: str,
        decided_at: datetime,
        expected_expires_at: datetime,
        expected_submitter_oid: str,
        expected_decision_route: str,
        expected_required_role: str,
    ) -> StoredProposal: ...


@dataclass(frozen=True, slots=True)
class PostgresHilDecisionStore:
    """Commit the approval decision receipt and durable outbox in one transaction."""

    config: PostgresFamilyStoreConfig

    async def append_hil_decision(
        self,
        *,
        approval_id: str,
        idempotency_key: str,
        action_hash: str,
        decision: str,
        approver_oid: str,
        approver_roles: frozenset[OperatorRole],
        justification: str,
        decided_at: datetime,
        expected_expires_at: datetime,
        expected_submitter_oid: str,
        expected_decision_route: str,
        expected_required_role: str,
    ) -> StoredProposal:
        """Fence one pending approval and atomically retain its decision plus outbox."""
        if decided_at.tzinfo is None or expected_expires_at.tzinfo is None:
            raise ValueError("HIL decision timestamps MUST be timezone-aware")
        decision_payload = {
            "approval_id": approval_id,
            "idempotency_key": idempotency_key,
            "decision": decision,
            "approver_oid": approver_oid.strip().casefold(),
            "justification_digest": "sha256:"
            + hashlib.sha256(justification.strip().encode("utf-8")).hexdigest(),
        }
        decision_key, decision_proposal = _operator_proposal_record(
            family="iam",
            operation="hil.decision.record",
            principal_id=None,
            idempotency_key=idempotency_key,
            payload=decision_payload,
        )
        receipt_key = f"operator-hil-decision:{approval_id}"
        park_key = f"hil_park:{approval_id}"
        try:
            async with await psycopg.AsyncConnection.connect(
                _psycopg_dsn(self.config.dsn),
                row_factory=dict_row,
                connect_timeout=self.config.connect_timeout_s,
            ) as connection:
                async with connection.transaction():
                    await _set_statement_timeout(connection, self.config.statement_timeout_ms)
                    park_cursor = await connection.execute(
                        """
                        SELECT value
                          FROM state_kv
                         WHERE key = %s
                         FOR UPDATE
                        """,
                        (park_key,),
                    )
                    park_row = await park_cursor.fetchone()
                    existing_cursor = await connection.execute(
                        "SELECT value FROM state_kv WHERE key = %s FOR UPDATE",
                        (receipt_key,),
                    )
                    existing_row = await existing_cursor.fetchone()
                    existing_receipt = (
                        _json_object(existing_row["value"], label=receipt_key)
                        if existing_row is not None
                        else None
                    )
                    if existing_receipt is None:
                        if park_row is None:
                            raise PostgresHilDecisionNotFoundError("pending HIL item was not found")
                        parked = _json_object(park_row["value"], label=park_key)
                        clock_cursor = await connection.execute(
                            "SELECT clock_timestamp() AS database_now"
                        )
                        clock_row = await clock_cursor.fetchone()
                        if clock_row is None:
                            raise PostgresFamilyStoreUnavailable("database clock is unavailable")
                        _validate_hil_decision_park(
                            parked,
                            approval_id=approval_id,
                            idempotency_key=idempotency_key,
                            action_hash=action_hash,
                            approver_oid=approver_oid,
                            approver_roles=approver_roles,
                            database_now=clock_row["database_now"],
                            expected_expires_at=expected_expires_at,
                            expected_submitter_oid=expected_submitter_oid,
                            expected_decision_route=expected_decision_route,
                            expected_required_role=expected_required_role,
                        )

                    stored_decision, decision_inserted = await _insert_operator_proposal(
                        connection,
                        key=decision_key,
                        record=decision_proposal,
                    )
                    receipt_ref = str(stored_decision["proposal_id"])
                    receipt = {
                        "approval_id": approval_id,
                        "idempotency_key": idempotency_key,
                        "decision": decision,
                        "approver_oid": approver_oid.strip().casefold(),
                        "decided_at": decided_at.isoformat(),
                        "receipt_ref": receipt_ref,
                        "justification": justification,
                        "already_recorded": False,
                        "delivered": bool(
                            existing_receipt is not None
                            and existing_receipt.get("delivered") is True
                        ),
                    }
                    if existing_receipt is not None:
                        _validate_existing_hil_receipt(existing_receipt, receipt)
                        receipt = existing_receipt
                    else:
                        await connection.execute(
                            "INSERT INTO state_kv (key, value) VALUES (%s, %s::jsonb)",
                            (
                                receipt_key,
                                json.dumps(receipt, separators=(",", ":"), sort_keys=True),
                            ),
                        )

                    outbox_receipt = {
                        key: receipt[key]
                        for key in (
                            "approval_id",
                            "idempotency_key",
                            "decision",
                            "approver_oid",
                            "justification",
                            "decided_at",
                            "receipt_ref",
                        )
                    }
                    outbox_key, outbox_proposal = _operator_proposal_record(
                        family="iam",
                        operation="hil.decision.enqueue",
                        principal_id=None,
                        idempotency_key=_hil_decision_delivery_key(idempotency_key),
                        payload={"receipt": outbox_receipt},
                    )
                    await _insert_operator_proposal(
                        connection,
                        key=outbox_key,
                        record=outbox_proposal,
                    )
                    return StoredProposal(
                        proposal_id=receipt_ref,
                        accepted_at=str(stored_decision["accepted_at"]),
                        duplicate=existing_receipt is not None or not decision_inserted,
                        record=stored_decision,
                    )
        except (
            PostgresFamilyStoreUnavailable,
            PostgresHilDecisionExpiredError,
            PostgresHilDecisionNotFoundError,
            PostgresHilDecisionPermissionError,
            PostgresProposalConflict,
        ):
            raise
        except psycopg.Error as exc:
            raise PostgresFamilyStoreUnavailable(
                "authoritative HIL decision store is unavailable"
            ) from exc


def _operator_proposal_record(
    *,
    family: str,
    operation: str,
    principal_id: str | None,
    idempotency_key: str,
    payload: Mapping[str, object],
) -> tuple[str, dict[str, object]]:
    request = {
        "family": family,
        "operation": operation,
        "principal_id": principal_id,
        "idempotency_key": idempotency_key,
        "payload": dict(payload),
    }
    request_digest = _digest(request)
    return (
        _proposal_key(family, idempotency_key),
        {
            "kind": "operator.proposal",
            "proposal_id": f"operator-{request_digest[:32]}",
            "request_digest": request_digest,
            "dispatch_status": "pending",
            "mode": "shadow",
            "accepted_at": datetime.now(UTC).isoformat(),
            **request,
        },
    )


async def _insert_operator_proposal(
    connection: psycopg.AsyncConnection[dict[str, Any]],
    *,
    key: str,
    record: Mapping[str, object],
) -> tuple[dict[str, object], bool]:
    inserted = await connection.execute(
        """
        INSERT INTO state_kv (key, value)
        VALUES (%s, %s::jsonb)
        ON CONFLICT (key) DO NOTHING
        RETURNING value
        """,
        (key, json.dumps(dict(record), separators=(",", ":"), sort_keys=True)),
    )
    inserted_row = await inserted.fetchone()
    if inserted_row is not None:
        return _json_object(inserted_row["value"], label=key), True
    existing_cursor = await connection.execute(
        "SELECT value FROM state_kv WHERE key = %s FOR UPDATE",
        (key,),
    )
    existing_row = await existing_cursor.fetchone()
    if existing_row is None:
        raise PostgresFamilyStoreUnavailable("stored Operator proposal disappeared")
    existing = _json_object(existing_row["value"], label=key)
    if existing.get("request_digest") != record.get("request_digest"):
        raise PostgresProposalConflict(
            "idempotency key conflicts with a different durable Operator proposal"
        )
    return existing, False


def _validate_hil_decision_park(
    parked: Mapping[str, object],
    *,
    approval_id: str,
    idempotency_key: str,
    action_hash: str,
    approver_oid: str,
    approver_roles: frozenset[OperatorRole],
    database_now: object,
    expected_expires_at: datetime,
    expected_submitter_oid: str,
    expected_decision_route: str,
    expected_required_role: str,
) -> None:
    if parked.get("status") != "pending":
        raise PostgresProposalConflict("HIL approval is no longer pending")
    if (
        parked.get("approval_id") != approval_id
        or parked.get("idempotency_key") != idempotency_key
        or parked.get("request_fingerprint") != action_hash
    ):
        raise PostgresProposalConflict("HIL approval identity changed before decision")
    submitter = parked.get("submitter_oid")
    if not isinstance(submitter, str) or not submitter.strip():
        raise PostgresFamilyStoreUnavailable("HIL approval submitter identity is unavailable")
    if submitter.strip().casefold() != expected_submitter_oid.strip().casefold():
        raise PostgresProposalConflict("HIL approval submitter changed before decision")
    if submitter.strip().casefold() == approver_oid.strip().casefold():
        raise PostgresHilDecisionPermissionError("requester MUST NOT approve their own request")

    context = parked.get("approval_context")
    if not isinstance(context, Mapping):
        raise PostgresFamilyStoreUnavailable("HIL approval context is malformed")
    raw_expires_at = context.get("expires_at")
    if not isinstance(raw_expires_at, str):
        raise PostgresFamilyStoreUnavailable("HIL approval expiry is unavailable")
    try:
        expires_at = datetime.fromisoformat(raw_expires_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PostgresFamilyStoreUnavailable("HIL approval expiry is malformed") from exc
    if expires_at.tzinfo is None or expires_at != expected_expires_at:
        raise PostgresProposalConflict("HIL approval expiry changed before decision")
    if not isinstance(database_now, datetime):
        raise PostgresFamilyStoreUnavailable("database clock is unavailable")
    if expires_at <= database_now:
        raise PostgresHilDecisionExpiredError("HIL approval expired before decision commit")

    if "metadata" not in parked:
        decision_route = "action"
        required_role = ""
    elif isinstance(metadata := parked["metadata"], Mapping):
        decision_route = str(metadata.get("decision_route") or "")
        required_role = str(metadata.get("required_role") or "")
    else:
        raise PostgresFamilyStoreUnavailable("HIL approval metadata is malformed")
    if decision_route != expected_decision_route or required_role != expected_required_role:
        raise PostgresProposalConflict("HIL approval role policy changed before decision")
    if decision_route not in {"action", "workflow"}:
        raise PostgresFamilyStoreUnavailable("HIL approval decision route is unavailable")
    if decision_route == "workflow" and not _operator_roles_meet(
        approver_roles,
        required_role,
    ):
        raise PostgresHilDecisionPermissionError(
            "approver does not satisfy the workflow approval role"
        )


def _validate_existing_hil_receipt(
    existing: Mapping[str, object],
    expected: Mapping[str, object],
) -> None:
    fields = (
        "approval_id",
        "idempotency_key",
        "decision",
        "approver_oid",
        "receipt_ref",
        "justification",
    )
    if any(existing.get(field) != expected.get(field) for field in fields):
        raise PostgresProposalConflict(
            "recorded HIL decision conflicts with the concurrent durable receipt"
        )


def _operator_roles_meet(
    roles: frozenset[OperatorRole],
    required_role: str,
) -> bool:
    rank = {
        OperatorRole.READER: 0,
        OperatorRole.CONTRIBUTOR: 1,
        OperatorRole.APPROVER: 2,
        OperatorRole.OWNER: 3,
    }
    try:
        required = OperatorRole(required_role)
    except ValueError:
        return False
    return any(rank.get(role, -1) >= rank.get(required, 99) for role in roles)


def _hil_decision_delivery_key(idempotency_key: str) -> str:
    digest = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()
    return f"hil-decision:{digest}:delivery"


def _proposal_key(family: str, idempotency_key: str) -> str:
    if not family or len(family) > 256:
        raise ValueError("family MUST be a bounded non-empty string")
    if not idempotency_key.strip() or len(idempotency_key) > 256:
        raise ValueError("idempotency_key MUST be a bounded non-empty string")
    digest = hashlib.sha256(idempotency_key.encode()).hexdigest()
    return f"operator-proposal:{family}:{digest}"


def _digest(value: Mapping[str, object]) -> str:
    canonical = json.dumps(value, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(canonical.encode()).hexdigest()


def _json_object(value: object, *, label: str) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise PostgresFamilyStoreUnavailable(f"{label} is malformed")
    return {str(key): item for key, item in value.items()}


def _psycopg_dsn(value: str) -> str:
    prefix = "postgresql+psycopg://"
    normalized = f"postgresql://{value[len(prefix) :]}" if value.startswith(prefix) else value
    if normalized in {"postgres://", "postgresql://"}:
        raise ValueError("PostgreSQL DSN MUST include a connection target")
    return normalized


async def _set_statement_timeout(
    connection: psycopg.AsyncConnection[object],
    timeout_ms: int,
) -> None:
    await connection.execute(
        "SELECT set_config('statement_timeout', %s, true)",
        (str(timeout_ms),),
    )


__all__ = [
    "HilDecisionStore",
    "PostgresHilDecisionExpiredError",
    "PostgresHilDecisionNotFoundError",
    "PostgresHilDecisionPermissionError",
    "PostgresHilDecisionStore",
]
