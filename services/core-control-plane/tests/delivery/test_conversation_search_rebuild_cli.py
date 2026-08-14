from __future__ import annotations

import json
from collections.abc import Mapping
from io import StringIO

import pytest
from fdai.delivery.conversation_search_rebuild_cli import (
    ConversationSearchRebuildConfig,
    run_once,
)


def test_rebuild_config_requires_server_owned_database_url() -> None:
    with pytest.raises(ValueError, match="FDAI_DATABASE_URL"):
        ConversationSearchRebuildConfig.from_env({})


async def test_run_once_normalizes_dsn_and_emits_bounded_json() -> None:
    output = StringIO()
    seen: list[ConversationSearchRebuildConfig] = []

    async def rebuild(
        config: ConversationSearchRebuildConfig,
    ) -> Mapping[str, int | float]:
        seen.append(config)
        return {"index_rows": 12, "index_bytes": 345, "duration_ms": 6.5}

    result = await run_once(
        env={"FDAI_DATABASE_URL": "postgresql+psycopg://user:secret@example/db"},
        rebuild=rebuild,
        output=output,
    )

    assert result == 0
    assert seen == [ConversationSearchRebuildConfig(dsn="postgresql://user:secret@example/db")]
    assert json.loads(output.getvalue()) == {
        "duration_ms": 6.5,
        "index_bytes": 345,
        "index_rows": 12,
        "status": "completed",
    }
    assert "secret" not in output.getvalue()


@pytest.mark.parametrize(
    "metrics",
    (
        {},
        {"index_rows": -1, "index_bytes": 1, "duration_ms": 1},
        {"index_rows": True, "index_bytes": 1, "duration_ms": 1},
        {"index_rows": 1, "index_bytes": 1, "duration_ms": float("nan")},
        {"index_rows": 1, "index_bytes": 1, "duration_ms": float("inf")},
    ),
)
async def test_run_once_rejects_invalid_metrics_without_output(
    metrics: Mapping[str, int | float],
) -> None:
    output = StringIO()

    async def rebuild(
        config: ConversationSearchRebuildConfig,
    ) -> Mapping[str, int | float]:
        return metrics

    with pytest.raises(RuntimeError, match="invalid metrics"):
        await run_once(
            env={"FDAI_DATABASE_URL": "postgresql://example/db"},
            rebuild=rebuild,
            output=output,
        )

    assert output.getvalue() == ""


async def test_run_once_propagates_failure_without_retry_or_output() -> None:
    output = StringIO()
    attempts = 0

    async def rebuild(
        config: ConversationSearchRebuildConfig,
    ) -> Mapping[str, int | float]:
        nonlocal attempts
        attempts += 1
        raise RuntimeError("database endpoint and credential must stay private")

    with pytest.raises(RuntimeError, match="credential must stay private"):
        await run_once(
            env={"FDAI_DATABASE_URL": "postgresql://user:secret@example/db"},
            rebuild=rebuild,
            output=output,
        )

    assert attempts == 1
    assert output.getvalue() == ""
