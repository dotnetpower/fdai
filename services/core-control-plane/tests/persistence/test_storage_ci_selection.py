"""Actual Core-role checkpoint suites run after all service migrations, never before."""

from pathlib import Path

import pytest
import yaml

from tests.persistence.test_heimdall_sensing_persistence_postgres import (
    saga_database as sensing_database,
)
from tests.persistence.test_saga_compact_checkpoint import _database

_ROOT = Path(__file__).resolve().parents[4]


def test_core_role_checkpoint_suites_are_selected_by_the_service_migrated_step() -> None:
    workflow = yaml.safe_load((_ROOT / ".github/workflows/ci.yml").read_text())
    steps = workflow["jobs"]["db-integration"]["steps"]
    service_step = next(
        step for step in steps if step.get("name") == "Run service-owned database tests"
    )
    assert service_step["env"]["FDAI_SERVICE_MIGRATIONS_READY"] == "1"
    assert steps.index(
        next(step for step in steps if step.get("name") == "Run service-owned migrations")
    ) < steps.index(service_step)
    for suite in (
        "test_heimdall_sensing_persistence_postgres.py",
        "test_saga_compact_checkpoint.py",
    ):
        assert suite in service_step["run"]


async def test_core_role_fixtures_do_not_open_a_legacy_only_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("FDAI_SERVICE_MIGRATIONS_READY", raising=False)
    monkeypatch.delenv("FDAI_DATABASE_URL", raising=False)
    sensing = sensing_database.__wrapped__()
    try:
        with pytest.raises(pytest.skip.Exception, match="service-owned migrations"):
            await anext(sensing)
    finally:
        await sensing.aclose()
    with pytest.raises(pytest.skip.Exception, match="service-owned migrations"):
        async with _database():
            pytest.fail("unmigrated fixture unexpectedly entered")
