"""Tests for the service-owned T2 cache rotation command."""

from __future__ import annotations

import io
import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fdai.delivery import t2_cache_rotation_cli


async def test_run_executes_exact_rotation_and_emits_bounded_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class _Store:
        def __init__(self, *, config: object) -> None:
            captured["config"] = config

        async def rotate(self, **kwargs: object) -> object:
            captured.update(kwargs)
            return SimpleNamespace(
                dropped_catalog_versions=("catalog-a",),
                receipt_digest=f"sha256:{'f' * 64}",
            )

    monkeypatch.setattr(t2_cache_rotation_cli, "PostgresT2Cache", _Store)
    active = f"sha256:{'a' * 64}"
    rollback = f"sha256:{'b' * 64}"
    output = io.StringIO()

    result = await t2_cache_rotation_cli.run(
        (
            "--active",
            active,
            "--rollback",
            rollback,
            "--idempotency-key",
            "rotation-1",
            "--cutoff",
            "2026-08-31T02:00:00Z",
        ),
        env={"FDAI_DATABASE_URL": "postgresql://example.com/fdai"},
        output=output,
    )

    assert result == 0
    assert captured["active_catalog_version"] == active
    assert captured["rollback_catalog_version"] == rollback
    assert captured["idempotency_key"] == "rotation-1"
    assert captured["cutoff"] == datetime(2026, 8, 31, 2, tzinfo=UTC)
    assert json.loads(output.getvalue()) == {
        "dropped_count": 1,
        "receipt_digest": f"sha256:{'f' * 64}",
        "status": "completed",
    }


async def test_run_rejects_missing_database_url() -> None:
    with pytest.raises(ValueError, match="FDAI_DATABASE_URL"):
        await t2_cache_rotation_cli.run(
            (
                "--active",
                f"sha256:{'a' * 64}",
                "--rollback",
                f"sha256:{'b' * 64}",
                "--idempotency-key",
                "rotation-1",
            ),
            env={},
            output=io.StringIO(),
        )
