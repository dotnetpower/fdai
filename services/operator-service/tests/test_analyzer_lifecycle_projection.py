from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit

import psycopg
import pytest
from fdai_operator_service.analyzer_history_projection import read_analyzer_history
from fdai_operator_service.analyzer_lifecycle_projection import (
    project_analyzer_lifecycle,
)
from fdai_operator_service.families.operations import ProjectionQuery, ProjectionUnavailableError
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

NOW = datetime(2026, 8, 31, 7, 0, tzinfo=UTC)


def _row(
    key: str,
    *,
    resource_ref: str = "cluster/example/pod/orders",
    signal: str = "pod_replacement",
    current_state: str = "running",
    evidence_state: str = "complete",
    publication: str = "published",
    recovery_closed: bool | None = True,
    occurred_at: str = "2026-08-31T06:59:50+00:00",
    recorded_at: str = "2026-08-31T07:00:00+00:00",
) -> dict[str, object]:
    return {
        "updated_at": NOW,
        "value": {
            "schema_version": "1.0.0",
            "idempotency_key": key,
            "resource_ref": resource_ref,
            "resource_kind": "kubernetes_pod",
            "signal": signal,
            "occurred_at": occurred_at,
            "recorded_at": recorded_at,
            "current_state": current_state,
            "detection_latency_seconds": 10.0,
            "evidence_complete": evidence_state == "complete",
            "evidence_state": evidence_state,
            "publication": publication,
            "recovery_closed": recovery_closed,
            "evidence_refs": ["pod-old", "pod-new"],
            "cause_claim_supported": False,
            "execution_authority": False,
        },
    }


def test_projection_separates_current_history_and_duplicate_publication() -> None:
    rows = [
        _row(
            "analyzer:current",
            publication="duplicate_suppressed",
            recorded_at="2026-08-31T07:00:01+00:00",
        ),
        _row("analyzer:current"),
        _row(
            "analyzer:history",
            signal="container_restart",
            current_state="failed",
            recovery_closed=False,
            occurred_at="2026-08-31T06:55:00+00:00",
            recorded_at="2026-08-31T06:55:05+00:00",
        ),
    ]

    result = project_analyzer_lifecycle(rows)

    assert result["target_count"] == 1
    target = result["targets"][0]  # type: ignore[index]
    assert target["current"]["signal"] == "pod_replacement"  # type: ignore[index]
    assert target["current"]["publication"] == {  # type: ignore[index]
        "current": "duplicate_suppressed",
        "attempts": ["published", "duplicate_suppressed"],
        "duplicate_observed": True,
    }
    assert target["history"][0]["signal"] == "container_restart"  # type: ignore[index]
    assert target["history"][0]["recovery_state"] == "open"  # type: ignore[index]


def test_projection_keeps_missed_conflicting_and_incomplete_states_explicit() -> None:
    rows = [
        _row("missed", resource_ref="pod/missed", evidence_state="missed"),
        _row("conflict", resource_ref="pod/conflict", evidence_state="conflicting"),
        _row("incomplete", resource_ref="pod/incomplete", evidence_state="incomplete"),
    ]

    result = project_analyzer_lifecycle(rows)

    assert result["evidence_counts"] == {
        "complete": 0,
        "incomplete": 1,
        "conflicting": 1,
        "missed": 1,
    }
    assert all(
        target["current"]["cause_claim_supported"] is False  # type: ignore[index]
        and target["current"]["execution_authority"] is False  # type: ignore[index]
        for target in result["targets"]  # type: ignore[union-attr]
    )


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("evidence_state", "invented"),
        ("cause_claim_supported", True),
        ("execution_authority", True),
    ),
)
def test_projection_rejects_widened_or_unknown_receipts(field: str, value: object) -> None:
    row = _row("invalid")
    row["value"][field] = value  # type: ignore[index]

    with pytest.raises(ProjectionUnavailableError):
        project_analyzer_lifecycle([row])


@pytest.mark.integration
async def test_complete_history_pages_group_publications_and_preserve_snapshot() -> None:
    dsn = os.environ.get("FDAI_DATABASE_URL", "")
    if not dsn:
        pytest.skip("FDAI_DATABASE_URL is unset; use with-local-test-database.py")
    parts = urlsplit(dsn)
    assert parts.hostname in {"localhost", "127.0.0.1", "::1"} and parts.port == 5433
    query = ProjectionQuery("detection.readiness", "reader-a", {}, {}, 50, None)
    async with await psycopg.AsyncConnection.connect(
        dsn.replace("postgresql+psycopg://", "postgresql://"), row_factory=dict_row
    ) as connection:
        await connection.execute(
            "CREATE TEMP TABLE state_kv (key text PRIMARY KEY, value jsonb NOT NULL, "
            "updated_at timestamptz NOT NULL)"
        )
        for index in range(603):
            for publication in ("published", "duplicate_suppressed"):
                row = _row(
                    f"history-{index:04}",
                    resource_ref=f"resource-{index % 6}",
                    publication=publication,
                    occurred_at=(NOW + timedelta(seconds=index // 2)).isoformat(),
                )
                await connection.execute(
                    "INSERT INTO state_kv VALUES (%s,%s,%s)",
                    (
                        f"runtime:analyzer-finding-receipt:{index}-{publication}",
                        Jsonb(row["value"]),
                        NOW + timedelta(microseconds=publication == "duplicate_suppressed"),
                    ),
                )

        async def fetch(statement: str, parameters: tuple[object, ...]) -> list[dict[str, Any]]:
            return list(await (await connection.execute(statement, parameters)).fetchall())

        seen: set[str] = set()
        cursor = None
        pages = 0
        first: Mapping[str, Any] | None = None
        while True:
            page = await read_analyzer_history(fetch, replace(query, cursor=cursor))
            if first is None:
                first = page
                # Appended records are outside the pinned time-bound set.
                await connection.execute(
                    "INSERT INTO state_kv VALUES (%s,%s,clock_timestamp())",
                    ("runtime:analyzer-finding-receipt:new", Jsonb(_row("new")["value"])),
                )
            meta = page["pagination"]
            lifecycle = page["lifecycle"]
            assert meta["total_assessments"] == 603
            assert meta["total_receipts"] == 1206
            assert meta["total_targets"] == 6
            assert meta["offset"] == len(seen)
            for target in lifecycle["targets"]:
                for assessment in [target["current"], *target["history"]]:
                    identity = assessment["idempotency_key"]
                    assert identity not in seen
                    seen.add(identity)
                    assert assessment["publication"]["attempts"] == [
                        "published",
                        "duplicate_suppressed",
                    ]
            pages += 1
            cursor = meta["next_cursor"]
            if cursor is None:
                break
        assert len(seen) == 603 and pages == 13
        assert first is not None
        next_cursor = first["pagination"]["next_cursor"]
        with pytest.raises(ValueError, match="cursor"):
            await read_analyzer_history(
                fetch, replace(query, cursor=next_cursor, principal_id="reader-b")
            )
        with pytest.raises(ValueError, match="cursor"):
            await read_analyzer_history(
                fetch, replace(query, cursor=next_cursor, params={"q": ("other",)})
            )
        with pytest.raises(ValueError, match="cursor"):
            await read_analyzer_history(fetch, replace(query, cursor=next_cursor, limit=25))
        filtered = await read_analyzer_history(
            fetch, replace(query, params={"q": ("history-0000",)})
        )
        assert filtered["pagination"]["total_assessments"] == 1
        assert filtered["pagination"]["next_cursor"] is None
        excluded = await read_analyzer_history(
            fetch, replace(query, params={"evidence": ("missed",), "from": ("2026-09-01",)})
        )
        assert excluded["pagination"]["total_assessments"] == 0
        assert excluded["pagination"]["next_cursor"] is None
        # Equal-count edits to retained content also invalidate an old cursor.
        await connection.execute(
            "UPDATE state_kv SET value = jsonb_set(value, '{current_state}', '\"changed\"') "
            "WHERE key = %s",
            ("runtime:analyzer-finding-receipt:1-published",),
        )
        with pytest.raises(ValueError, match="snapshot changed"):
            await read_analyzer_history(fetch, replace(query, cursor=next_cursor))
        await connection.execute(
            "DELETE FROM state_kv WHERE key = %s", ("runtime:analyzer-finding-receipt:0-published",)
        )
        with pytest.raises(ValueError, match="snapshot changed"):
            await read_analyzer_history(fetch, replace(query, cursor=next_cursor))


@pytest.mark.parametrize(
    "params",
    [
        {"evidence": ("invented",)},
        {"delivery": ("invented",)},
        {"from": ("yesterday",)},
        {"q": ("x" * 257,)},
    ],
)
async def test_history_rejects_invalid_filters_before_sql(
    params: dict[str, tuple[str, ...]],
) -> None:
    async def fetch(_sql: str, _params: tuple[object, ...]) -> list[dict[str, Any]]:
        pytest.fail("invalid filters must not reach SQL")

    with pytest.raises(ValueError):
        await read_analyzer_history(
            fetch, ProjectionQuery("detection.readiness", "reader-a", {}, params, 50, None)
        )
