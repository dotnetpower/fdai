"""Transactional source references for user-context ontology recovery."""

from __future__ import annotations

from typing import Any

import psycopg


async def enqueue_projection_upsert(
    connection: psycopg.AsyncConnection[Any],
    *,
    projection_kind: str,
    principal_id: str,
    record_id: str,
) -> None:
    await connection.execute(
        "INSERT INTO user_context_projection_upsert_queue "
        "(projection_kind, principal_id, record_id) VALUES (%s, %s, %s) "
        "ON CONFLICT (projection_kind, principal_id, record_id) DO UPDATE SET "
        "available_at = NOW(), attempts = 0, leased_until = NULL, last_error = NULL",
        (projection_kind, principal_id, record_id),
    )


__all__ = ["enqueue_projection_upsert"]
