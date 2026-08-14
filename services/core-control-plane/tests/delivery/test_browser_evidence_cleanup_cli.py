from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Coroutine
from datetime import UTC, datetime, timedelta, timezone
from io import StringIO
from typing import Any

import fdai.delivery.browser_evidence_cleanup_cli as cleanup_cli
import pytest
from fdai.delivery.browser_evidence_cleanup_cli import (
    BrowserEvidenceCleanupConfig,
    run_once,
)


class _Output(StringIO):
    flushed = False

    def flush(self) -> None:
        self.flushed = True
        super().flush()


def test_cleanup_config_requires_database_url_and_bounded_limit() -> None:
    with pytest.raises(ValueError, match="FDAI_DATABASE_URL"):
        BrowserEvidenceCleanupConfig.from_env({})

    for raw_limit in ("invalid", "0", "501"):
        with pytest.raises(ValueError, match="CLEANUP_LIMIT"):
            BrowserEvidenceCleanupConfig.from_env(
                {
                    "FDAI_DATABASE_URL": "postgresql://example/db",
                    "FDAI_BROWSER_EVIDENCE_CLEANUP_LIMIT": raw_limit,
                }
            )


async def test_run_once_normalizes_dsn_and_emits_count_only() -> None:
    output = _Output()
    now = datetime(2026, 8, 15, tzinfo=UTC)
    seen: list[tuple[BrowserEvidenceCleanupConfig, datetime]] = []

    async def purge(
        config: BrowserEvidenceCleanupConfig,
        cutoff: datetime,
    ) -> tuple[str, ...]:
        seen.append((config, cutoff))
        return ("private-artifact-1", "private-artifact-2")

    result = await run_once(
        env={
            "FDAI_DATABASE_URL": "postgresql+psycopg://user:secret@example/db",
            "FDAI_BROWSER_EVIDENCE_CLEANUP_LIMIT": "2",
        },
        purge=purge,
        clock=lambda: now,
        output=output,
    )

    assert result == 0
    assert seen == [
        (BrowserEvidenceCleanupConfig(dsn="postgresql://user:secret@example/db", limit=2), now)
    ]
    assert json.loads(output.getvalue()) == {"purged_count": 2, "status": "completed"}
    assert output.flushed is True
    assert "artifact" not in output.getvalue()
    assert "secret" not in output.getvalue()


async def test_run_once_rejects_naive_clock_without_purge_or_output() -> None:
    output = StringIO()
    called = False

    async def purge(
        config: BrowserEvidenceCleanupConfig,
        cutoff: datetime,
    ) -> tuple[str, ...]:
        nonlocal called
        called = True
        return ()

    with pytest.raises(RuntimeError, match="timezone"):
        await run_once(
            env={"FDAI_DATABASE_URL": "postgresql://example/db"},
            purge=purge,
            clock=lambda: datetime(2026, 8, 15),
            output=output,
        )

    assert called is False
    assert output.getvalue() == ""


async def test_run_once_normalizes_aware_clock_to_utc() -> None:
    output = StringIO()
    seen: list[datetime] = []

    async def purge(
        config: BrowserEvidenceCleanupConfig,
        cutoff: datetime,
    ) -> tuple[str, ...]:
        seen.append(cutoff)
        return ()

    await run_once(
        env={"FDAI_DATABASE_URL": "postgresql://example/db"},
        purge=purge,
        clock=lambda: datetime(2026, 8, 15, 9, tzinfo=timezone(timedelta(hours=9))),
        output=output,
    )

    assert seen == [datetime(2026, 8, 15, tzinfo=UTC)]


async def test_run_once_rejects_oversized_provider_result_without_output() -> None:
    output = StringIO()

    async def purge(
        config: BrowserEvidenceCleanupConfig,
        cutoff: datetime,
    ) -> tuple[str, ...]:
        return ("artifact-1", "artifact-2")

    with pytest.raises(RuntimeError, match="configured limit"):
        await run_once(
            env={
                "FDAI_DATABASE_URL": "postgresql://example/db",
                "FDAI_BROWSER_EVIDENCE_CLEANUP_LIMIT": "1",
            },
            purge=purge,
            output=output,
        )

    assert output.getvalue() == ""


async def test_run_once_propagates_one_failure_without_retry_or_output() -> None:
    output = StringIO()
    attempts = 0

    async def purge(
        config: BrowserEvidenceCleanupConfig,
        cutoff: datetime,
    ) -> tuple[str, ...]:
        nonlocal attempts
        attempts += 1
        raise RuntimeError("private database endpoint must not be emitted")

    with pytest.raises(RuntimeError, match="private database"):
        await run_once(
            env={"FDAI_DATABASE_URL": "postgresql://user:secret@example/db"},
            purge=purge,
            output=output,
        )

    assert attempts == 1
    assert output.getvalue() == ""


def test_main_redacts_failure_details(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def fail(coroutine: Coroutine[Any, Any, int]) -> int:
        coroutine.close()
        raise RuntimeError("private database endpoint and credential")

    monkeypatch.setattr(asyncio, "run", fail)

    with caplog.at_level(logging.ERROR):
        result = cleanup_cli.main()

    assert result == 3
    assert len(caplog.records) == 1
    assert caplog.records[0].message == "browser_evidence_cleanup_failed"
    assert caplog.records[0].error_type == "RuntimeError"  # type: ignore[attr-defined]
    assert "private database" not in caplog.text
