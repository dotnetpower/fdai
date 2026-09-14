"""Lease one exact Operator-owned alert request using existing state_kv primitives."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any
from uuid import uuid4


async def claim_alert_quality(
    fetch: Callable[..., Awaitable[list[dict[str, Any]]]],
) -> tuple[str, str, Mapping[str, Any]] | None:
    """Atomically claim oldest due request; a reclaimed lease never changes request identity."""
    claim_id = str(uuid4())
    rows = await fetch(
        """
        WITH candidate AS (
            SELECT key FROM state_kv
            WHERE key LIKE 'operator-proposal:operations:%'
              AND value ->> 'operation' IN ('alert_noise.assess', 'alert_noise.propose')
              AND (value ->> 'dispatch_status' = 'pending' OR
                   (value ->> 'dispatch_status' = 'claimed'
                    AND (value ->> 'claim_expires_at')::timestamptz <= NOW()))
            ORDER BY value ->> 'accepted_at', key
            FOR UPDATE SKIP LOCKED LIMIT 1
        )
        UPDATE state_kv AS proposal SET value = proposal.value || jsonb_build_object(
            'dispatch_status', 'claimed', 'claim_id', %(claim_id)s::text,
            'claim_expires_at', NOW() + interval '120 seconds',
            'attempt', COALESCE((proposal.value ->> 'attempt')::integer, 0) + 1
        ), updated_at = NOW()
        FROM candidate WHERE proposal.key = candidate.key
        RETURNING proposal.key, proposal.value
        """,
        {"claim_id": claim_id},
    )
    if not rows:
        return None
    row = rows[0]
    if not isinstance(row.get("key"), str) or not isinstance(row.get("value"), Mapping):
        raise ValueError("alert proposal claim is malformed")
    return row["key"], claim_id, row["value"]
