"""Lease SQL for Operator proposal outbox families published by background bridges."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any
from uuid import uuid4

from fdai_operator_service.postgres_family_models import (
    IncidentInterventionProposalClaim,
    PoisonHaltClearProposalClaim,
    PostgresFamilyStoreUnavailableError,
    ReadInvestigationProposalClaim,
)

FetchAll = Callable[[str, Mapping[str, object]], Awaitable[list[dict[str, Any]]]]


async def claim_poison_halt_clear_proposal(
    fetch_all: FetchAll,
    *,
    key: str,
    worker_id: str,
    lease_seconds: int,
) -> PoisonHaltClearProposalClaim | None:
    """Lease one exact pending or expired ordered-poison-halt clear proposal row."""

    claim_id = str(uuid4())
    rows = await fetch_all(
        """
        UPDATE state_kv AS proposal
           SET value = proposal.value || jsonb_build_object(
               'dispatch_status', 'claimed',
               'claim_id', %(claim_id)s::text,
               'claim_worker_id', %(worker_id)s::text,
               'claim_expires_at', NOW() + make_interval(secs => %(lease_seconds)s),
               'attempt', COALESCE((proposal.value ->> 'attempt')::integer, 0) + 1
           ),
               updated_at = NOW()
         WHERE proposal.key = %(key)s
           AND value ->> 'family' = 'operations'
           AND value ->> 'operation' = 'bus.ordered-poison-halt.clear'
           AND (
                value ->> 'dispatch_status' = 'pending'
                OR (
                    value ->> 'dispatch_status' = 'claimed'
                    AND (value ->> 'claim_expires_at')::timestamptz <= NOW()
                )
           )
     RETURNING proposal.key, proposal.value
        """,
        {
            "claim_id": claim_id,
            "key": key,
            "worker_id": worker_id,
            "lease_seconds": lease_seconds,
        },
    )
    if not rows:
        return None
    value = _json_object(rows[0].get("value"), label="poison halt clear proposal claim")
    payload = value.get("payload")
    attempt = value.get("attempt")
    if (
        not isinstance(payload, Mapping)
        or not isinstance(attempt, int)
        or isinstance(attempt, bool)
    ):
        raise PostgresFamilyStoreUnavailableError("poison halt clear proposal claim is malformed")
    return PoisonHaltClearProposalClaim(
        key=key,
        claim_id=str(value.get("claim_id") or claim_id),
        payload=dict(payload),
        attempt=attempt,
    )


async def claim_read_investigation_proposal(
    fetch_all: FetchAll,
    *,
    worker_id: str,
    lease_seconds: int,
) -> ReadInvestigationProposalClaim | None:
    """Lease the oldest pending read-investigation proposal for publication."""

    _bounded_component("worker_id", worker_id)
    if not 1 <= lease_seconds <= 300:
        raise ValueError("lease_seconds MUST be in [1, 300]")
    claim_id = str(uuid4())
    rows = await fetch_all(
        """
        WITH candidate AS (
            SELECT key
              FROM state_kv
                             WHERE key LIKE %(proposal_prefix)s
               AND (
                    (
                        value ->> 'family' = 'operations'
                        AND value ->> 'operation' = 'read_investigation.start'
                    )
                    OR (
                        value ->> 'family' = 'conversation'
                        AND value ->> 'operation' = 'background.cancel'
                    )
               )
               AND (
                    value ->> 'dispatch_status' = 'pending'
                    OR (
                        value ->> 'dispatch_status' = 'claimed'
                        AND (value ->> 'claim_expires_at')::timestamptz <= NOW()
                    )
               )
             ORDER BY COALESCE((value ->> 'attempt')::integer, 0),
                      value ->> 'accepted_at', key
             FOR UPDATE SKIP LOCKED
             LIMIT 1
        )
        UPDATE state_kv AS proposal
           SET value = proposal.value || jsonb_build_object(
               'dispatch_status', 'claimed',
               'claim_id', %(claim_id)s::text,
               'claim_worker_id', %(worker_id)s::text,
               'claim_expires_at', NOW() + make_interval(secs => %(lease_seconds)s),
               'attempt', COALESCE((proposal.value ->> 'attempt')::integer, 0) + 1
           ),
               updated_at = NOW()
          FROM candidate
         WHERE proposal.key = candidate.key
     RETURNING proposal.key, proposal.value
        """,
        {
            "claim_id": claim_id,
            "proposal_prefix": "operator-proposal:%",
            "worker_id": worker_id,
            "lease_seconds": lease_seconds,
        },
    )
    if not rows:
        return None
    key = rows[0].get("key")
    value = _json_object(rows[0].get("value"), label="read investigation proposal claim")
    proposal_id = value.get("proposal_id")
    principal_id = value.get("principal_id")
    idempotency_key = value.get("idempotency_key")
    accepted_at = value.get("accepted_at")
    payload = value.get("payload")
    attempt = value.get("attempt")
    if (
        not isinstance(key, str)
        or not isinstance(proposal_id, str)
        or not isinstance(principal_id, str)
        or not isinstance(idempotency_key, str)
        or not isinstance(accepted_at, str)
        or not isinstance(payload, Mapping)
        or not isinstance(attempt, int)
        or isinstance(attempt, bool)
    ):
        raise PostgresFamilyStoreUnavailableError("read investigation proposal claim is malformed")
    correlation_id = payload.get("correlation_id")
    if correlation_id is not None and not isinstance(correlation_id, str):
        raise PostgresFamilyStoreUnavailableError("read investigation correlation is malformed")
    return ReadInvestigationProposalClaim(
        key=key,
        claim_id=str(value.get("claim_id") or claim_id),
        request_id=proposal_id,
        principal_id=principal_id,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        payload=dict(payload),
        accepted_at=accepted_at,
        attempt=attempt,
    )


async def claim_incident_intervention_proposal(
    fetch_all: FetchAll,
    *,
    worker_id: str,
    lease_seconds: int,
) -> IncidentInterventionProposalClaim | None:
    """Lease the oldest pending Incident intervention for publication."""

    _bounded_component("worker_id", worker_id)
    if not 1 <= lease_seconds <= 300:
        raise ValueError("lease_seconds MUST be in [1, 300]")
    claim_id = str(uuid4())
    rows = await fetch_all(
        """
        WITH candidate AS (
            SELECT key
              FROM state_kv
             WHERE key LIKE %(proposal_prefix)s
               AND value ->> 'operation' = 'incident.intervention'
               AND (
                    value ->> 'dispatch_status' = 'pending'
                    OR (
                        value ->> 'dispatch_status' = 'claimed'
                        AND (value ->> 'claim_expires_at')::timestamptz <= NOW()
                    )
               )
             ORDER BY COALESCE((value ->> 'attempt')::integer, 0),
                      value ->> 'accepted_at', key
             FOR UPDATE SKIP LOCKED
             LIMIT 1
        )
        UPDATE state_kv AS proposal
           SET value = proposal.value || jsonb_build_object(
               'dispatch_status', 'claimed',
               'claim_id', %(claim_id)s::text,
               'claim_worker_id', %(worker_id)s::text,
               'claim_expires_at', NOW() + make_interval(secs => %(lease_seconds)s),
               'attempt', COALESCE((proposal.value ->> 'attempt')::integer, 0) + 1
           ),
               updated_at = NOW()
          FROM candidate
         WHERE proposal.key = candidate.key
     RETURNING proposal.key, proposal.value
        """,
        {
            "claim_id": claim_id,
            "proposal_prefix": "operator-proposal:%",
            "worker_id": worker_id,
            "lease_seconds": lease_seconds,
        },
    )
    if not rows:
        return None
    key = rows[0].get("key")
    value = _json_object(rows[0].get("value"), label="Incident intervention claim")
    request_id = value.get("proposal_id")
    principal_id = value.get("principal_id")
    idempotency_key = value.get("idempotency_key")
    accepted_at = value.get("accepted_at")
    payload = value.get("payload")
    attempt = value.get("attempt")
    if (
        not isinstance(key, str)
        or not isinstance(request_id, str)
        or not isinstance(principal_id, str)
        or not isinstance(idempotency_key, str)
        or not isinstance(accepted_at, str)
        or not isinstance(payload, Mapping)
        or not isinstance(attempt, int)
        or isinstance(attempt, bool)
    ):
        raise PostgresFamilyStoreUnavailableError("Incident intervention claim is malformed")
    correlation_id = payload.get("correlation_id")
    if not isinstance(correlation_id, str):
        raise PostgresFamilyStoreUnavailableError("Incident intervention correlation is malformed")
    return IncidentInterventionProposalClaim(
        key=key,
        claim_id=str(value.get("claim_id") or claim_id),
        request_id=request_id,
        principal_id=principal_id,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        payload=dict(payload),
        accepted_at=accepted_at,
        attempt=attempt,
    )


def _bounded_component(name: str, value: str) -> None:
    if not value.strip() or len(value) > 128:
        raise ValueError(f"{name} MUST be a bounded non-empty string")


def _json_object(value: object, *, label: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise PostgresFamilyStoreUnavailableError(f"{label} is not a JSON object")
    return {str(key): item for key, item in value.items()}


__all__ = [
    "FetchAll",
    "claim_incident_intervention_proposal",
    "claim_poison_halt_clear_proposal",
    "claim_read_investigation_proposal",
]
