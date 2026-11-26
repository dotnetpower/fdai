"""Read complete retained analyzer history in bounded assessment pages.

The cursor binds a time-bounded receipt set, filters, principal and page size.
Receipts belonging to one assessment never split across pages. Changed retained
sets fail explicitly rather than mixing snapshots; cursors grant no authority.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, date, datetime
from typing import Any

from fdai_operator_service.analyzer_lifecycle_projection import project_analyzer_lifecycle
from fdai_operator_service.families.operations import ProjectionQuery, ProjectionUnavailableError

_SQL = """
WITH visible AS MATERIALIZED (
    SELECT key, value, updated_at FROM state_kv
    WHERE key LIKE 'runtime:analyzer-finding-receipt:%%' AND updated_at <= %s
), grouped AS (
    SELECT value->>'idempotency_key' AS identity,
           MAX((value->>'occurred_at')::timestamptz) AS occurred,
           encode(sha256(convert_to(
               (value->>'idempotency_key') || chr(10) || (value->>'occurred_at'), 'UTF8')),
               'hex') AS sort_key,
           (array_agg(value ORDER BY updated_at DESC, key DESC))[1] AS latest,
           jsonb_agg(jsonb_build_object('value', value)
                     ORDER BY updated_at DESC, key DESC) AS receipts
    FROM visible GROUP BY value->>'idempotency_key', value->>'occurred_at'
), filtered AS MATERIALIZED (
    SELECT * FROM grouped
    WHERE (%s = '' OR strpos(lower(latest::text), lower(%s)) > 0)
      AND (%s = 'all' OR latest->>'evidence_state' = %s)
      AND (%s = 'all' OR EXISTS (
          SELECT 1 FROM jsonb_array_elements(receipts) r
          WHERE r->'value'->>'publication' = %s))
      AND (%s = '' OR (occurred AT TIME ZONE 'UTC')::date >= NULLIF(%s, '')::date)
      AND (%s = '' OR (occurred AT TIME ZONE 'UTC')::date <= NULLIF(%s, '')::date)
), page AS (
    SELECT * FROM filtered
    WHERE (%s::timestamptz IS NULL OR (occurred, sort_key) < (%s::timestamptz, %s))
    ORDER BY occurred DESC, sort_key DESC LIMIT %s
)
SELECT (SELECT COUNT(*) FROM visible) AS snapshot_count,
       (SELECT md5(COALESCE(string_agg(
           md5(key || value::text || updated_at::text), '' ORDER BY key), ''))
           FROM visible) AS snapshot_revision,
       (SELECT COUNT(*) FROM filtered) AS total_assessments,
       (SELECT COALESCE(SUM(jsonb_array_length(receipts)), 0) FROM filtered) AS total_receipts,
       (SELECT COUNT(DISTINCT latest->>'resource_ref') FROM filtered) AS total_targets,
       (SELECT MIN(r->'value'->>'recorded_at') FROM filtered,
           LATERAL jsonb_array_elements(receipts) r) AS retained_from,
       (SELECT MAX(r->'value'->>'recorded_at') FROM filtered,
           LATERAL jsonb_array_elements(receipts) r) AS observed_at,
       (SELECT COUNT(*) FROM filtered WHERE latest->>'evidence_state' = 'complete') AS complete,
       (SELECT COUNT(*) FROM filtered WHERE latest->>'evidence_state' = 'incomplete') AS incomplete,
       (SELECT COUNT(*) FROM filtered
           WHERE latest->>'evidence_state' = 'conflicting') AS conflicting,
       (SELECT COUNT(*) FROM filtered WHERE latest->>'evidence_state' = 'missed') AS missed,
       COALESCE((SELECT jsonb_agg(jsonb_build_object(
           'identity', sort_key, 'occurred', occurred, 'receipts', receipts)
           ORDER BY occurred DESC, sort_key DESC) FROM page), '[]'::jsonb) AS items
"""
_EVIDENCE = {"all", "complete", "incomplete", "conflicting", "missed"}
_DELIVERY = {
    "all",
    "published",
    "published_receipt_unrecorded",
    "duplicate_suppressed",
    "reconciled_duplicate",
    "publish_uncertain",
    "awaiting_reconciliation",
    "failed",
}


async def read_analyzer_history(
    fetch_all: Callable[[str, tuple[object, ...]], Awaitable[list[dict[str, Any]]]],
    query: ProjectionQuery,
) -> Mapping[str, object]:
    """Return one page and full filtered totals from a single SQL snapshot."""
    filters = {
        name: query.params.get(name, (default,))[-1]
        for name, default in (
            ("q", ""),
            ("evidence", "all"),
            ("delivery", "all"),
            ("from", ""),
            ("to", ""),
        )
    }
    if (
        len(filters["q"]) > 256
        or filters["evidence"] not in _EVIDENCE
        or filters["delivery"] not in _DELIVERY
    ):
        raise ValueError("invalid analyzer history filters")
    for name in ("from", "to"):
        if filters[name]:
            try:
                if date.fromisoformat(filters[name]).isoformat() != filters[name]:
                    raise ValueError("noncanonical date")
            except ValueError as exc:
                raise ValueError("history dates must use YYYY-MM-DD") from exc
    if filters["from"] and filters["to"] and filters["from"] > filters["to"]:
        raise ValueError("history start date must not follow the end date")
    limit = min(max(query.limit, 1), 100)
    binding = hashlib.sha256(
        json.dumps(
            [query.principal_id, sorted(role.value for role in query.roles), filters, limit],
            sort_keys=True,
        ).encode()
    ).hexdigest()
    cursor = _cursor(query.cursor, binding)
    cutoff = datetime.fromisoformat(cursor["at"]) if cursor else datetime.now(UTC)
    offset = cursor["offset"] if cursor else 0
    after_time, after_id = (cursor["time"], cursor["id"]) if cursor else (None, "")
    rows = await fetch_all(
        _SQL,
        (
            cutoff,
            filters["q"],
            filters["q"],
            filters["evidence"],
            filters["evidence"],
            filters["delivery"],
            filters["delivery"],
            filters["from"],
            filters["from"],
            filters["to"],
            filters["to"],
            after_time,
            after_time,
            after_id,
            limit + 1,
        ),
    )
    if len(rows) != 1 or not isinstance(rows[0].get("items"), list):
        raise ProjectionUnavailableError("analyzer history returned an invalid page")
    row = rows[0]
    snapshot_count = _count(row, "snapshot_count")
    snapshot_revision = row.get("snapshot_revision")
    if not isinstance(snapshot_revision, str) or len(snapshot_revision) != 32:
        raise ProjectionUnavailableError("analyzer history snapshot identity is malformed")
    if cursor and (
        snapshot_count != cursor["count"] or snapshot_revision != cursor.get("revision")
    ):
        raise ValueError("analyzer history snapshot changed; refresh history")
    items = row["items"]
    if len(items) > limit + 1:
        raise ProjectionUnavailableError("analyzer history page exceeded its bound")
    page = items[:limit]
    receipts: list[Mapping[str, object]] = []
    for item in page:
        if not isinstance(item, dict) or not isinstance(item.get("receipts"), list):
            raise ProjectionUnavailableError("analyzer history assessment is malformed")
        if not 1 <= len(item["receipts"]) <= 7:
            raise ProjectionUnavailableError("analyzer history publication bound exceeded")
        receipts.extend(item["receipts"])
    lifecycle = project_analyzer_lifecycle(receipts, receipt_limit=limit * 7)
    total = _count(row, "total_assessments")
    counts = {state: _count(row, state) for state in _EVIDENCE - {"all"}}
    if (
        sum(counts.values()) != total
        or lifecycle["assessment_count"] != len(page)
        or offset + len(page) > total
        or (not page and offset != total)
    ):
        raise ProjectionUnavailableError("analyzer history totals do not reconcile")
    next_cursor = None
    if len(items) > limit:
        last = page[-1]
        next_cursor = (
            base64.urlsafe_b64encode(
                json.dumps(
                    {
                        "binding": binding,
                        "at": cutoff.isoformat(),
                        "count": snapshot_count,
                        "revision": snapshot_revision,
                        "offset": offset + len(page),
                        "time": last["occurred"],
                        "id": last["identity"],
                    },
                    separators=(",", ":"),
                ).encode()
            )
            .decode()
            .rstrip("=")
        )
    return {
        "lifecycle": lifecycle,
        "pagination": {
            "total_receipts": _count(row, "total_receipts"),
            "total_assessments": total,
            "total_targets": _count(row, "total_targets"),
            "evidence_counts": counts,
            "observed_at": row["observed_at"],
            "retained_from": row["retained_from"],
            "snapshot_at": cutoff.isoformat(),
            "offset": offset,
            "page_size": limit,
            "next_cursor": next_cursor,
        },
        "execution_authority": False,
    }


def _count(row: Mapping[str, object], name: str) -> int:
    value = row.get(name)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ProjectionUnavailableError("analyzer history count is malformed")
    return value


def _cursor(raw: str | None, binding: str) -> dict[str, Any] | None:
    if raw is None:
        return None
    try:
        value = json.loads(
            base64.b64decode(raw + "=" * (-len(raw) % 4), altchars=b"-_", validate=True)
        )
        if not isinstance(value, dict) or value.get("binding") != binding:
            raise ValueError("history cursor binding mismatch")
        at = datetime.fromisoformat(value["at"])
        if (
            at.tzinfo is None
            or at > datetime.now(UTC)
            or (datetime.now(UTC) - at).total_seconds() > 900
        ):
            raise ValueError("history cursor expired")
        if any(type(value.get(k)) is not int or value[k] < 0 for k in ("offset", "count")):
            raise ValueError("invalid history offset")
        if any(
            not isinstance(value.get(k), str) or not value[k] or len(value[k]) > 512
            for k in ("id", "time")
        ):
            raise ValueError("invalid history identity")
        if re.fullmatch(r"[a-f0-9]{64}", value["id"]) is None:
            raise ValueError("invalid history identity")
        if datetime.fromisoformat(value["time"]).tzinfo is None:
            raise ValueError("invalid history time")
        return value
    except (ValueError, KeyError, TypeError) as exc:
        raise ValueError("invalid or expired analyzer history cursor; refresh history") from exc
