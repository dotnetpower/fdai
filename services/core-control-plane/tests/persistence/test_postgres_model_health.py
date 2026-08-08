"""PostgreSQL model health transition persistence tests."""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fdai.delivery.azure.llm.latency_routed_cross_check import (
    ModelFailureKind,
    ModelHealthTransition,
)
from fdai.delivery.persistence import (
    PostgresModelHealthTransitionSink,
    PostgresModelHealthTransitionSinkConfig,
)

REPO_ROOT = Path(__file__).resolve().parents[4]
_NOW = datetime(2026, 7, 17, 9, 30, tzinfo=UTC)


def test_config_rejects_empty_dsn_or_bad_timeout() -> None:
    with pytest.raises(ValueError, match="dsn"):
        PostgresModelHealthTransitionSinkConfig(dsn="")
    with pytest.raises(ValueError, match="timeouts"):
        PostgresModelHealthTransitionSinkConfig(dsn="postgresql://x", connect_timeout_s=0)


def _requires_live_db() -> str:
    url = os.environ.get("FDAI_DATABASE_URL")
    if not url:
        pytest.skip("FDAI_DATABASE_URL is unset")
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def _upgrade_head() -> None:
    result = subprocess.run(  # noqa: S603 - controlled subprocess
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.integration
async def test_role_scoped_transition_survives_restart() -> None:
    dsn = _requires_live_db()
    _upgrade_head()
    deployment = f"model-{uuid.uuid4().hex[:8]}"
    config = PostgresModelHealthTransitionSinkConfig(dsn=dsn)
    sink = PostgresModelHealthTransitionSink(config=config)
    transition = ModelHealthTransition(
        model_role="narrator",
        deployment=deployment,
        status="unhealthy",
        failure_kind=ModelFailureKind.RATE_LIMIT,
        failure_count=1,
        cooldown_seconds=60,
        recorded_at=_NOW,
    )
    await sink.append(transition)

    restarted = PostgresModelHealthTransitionSink(config=config)
    assert await restarted.list_for(model_role="narrator", deployment=deployment) == (transition,)
