"""Tests for :mod:`fdai.core.verticals.db_dr_drill_cli`.

Cover the env-var contract, dry-run wire-up, injected live runner, and
fail-fast exit codes.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.verticals.resilience import db_dr_drill_cli
from fdai.core.verticals.resilience.db_dr_drill_cli import (
    _ENV_DRY_RUN,
    _ENV_LOCATION,
    _ENV_PITR_OFFSET,
    _ENV_RG_PREFIX,
    _ENV_SERVER_PREFIX,
    _ENV_SOURCE,
    _build_config,
    main,
)
from fdai.core.verticals.resilience.db_dr_verifier import DbDrOutcome, DbDrVerdict
from fdai.shared.providers.db_dr import DbRestoreConfig

_FIXED_NOW = datetime(2026, 7, 6, 15, 30, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        _ENV_SOURCE,
        _ENV_LOCATION,
        _ENV_RG_PREFIX,
        _ENV_SERVER_PREFIX,
        _ENV_PITR_OFFSET,
        _ENV_DRY_RUN,
    ):
        monkeypatch.delenv(key, raising=False)


# ---------------------------------------------------------------------------
# _build_config
# ---------------------------------------------------------------------------


def test_build_config_missing_source_returns_none() -> None:
    assert _build_config(_FIXED_NOW) is None


def test_build_config_missing_location_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(_ENV_SOURCE, "/subscriptions/x/resourceGroups/rg/servers/s")
    assert _build_config(_FIXED_NOW) is None


def test_build_config_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(_ENV_SOURCE, "/subscriptions/x/resourceGroups/rg/servers/s")
    monkeypatch.setenv(_ENV_LOCATION, "koreacentral")
    cfg = _build_config(_FIXED_NOW)
    assert cfg is not None
    assert cfg.target_location == "koreacentral"
    assert cfg.experiment_id.startswith("db-dr-drill-2026")
    assert cfg.target_resource_group.startswith("rg-fdai-dr-drill-2026")
    assert cfg.target_server_name.startswith("psql-drill-")
    assert cfg.point_in_time_utc == _FIXED_NOW - timedelta(minutes=30)


def test_build_config_prefix_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(_ENV_SOURCE, "/subscriptions/x/resourceGroups/rg/servers/s")
    monkeypatch.setenv(_ENV_LOCATION, "koreacentral")
    monkeypatch.setenv(_ENV_RG_PREFIX, "rg-custom-drill")
    monkeypatch.setenv(_ENV_SERVER_PREFIX, "psql-custom")
    cfg = _build_config(_FIXED_NOW)
    assert cfg is not None
    assert cfg.target_resource_group.startswith("rg-custom-drill-")
    assert cfg.target_server_name.startswith("psql-custom-")


def test_build_config_rejects_non_numeric_offset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(_ENV_SOURCE, "/subscriptions/x/resourceGroups/rg/servers/s")
    monkeypatch.setenv(_ENV_LOCATION, "koreacentral")
    monkeypatch.setenv(_ENV_PITR_OFFSET, "not-a-number")
    assert _build_config(_FIXED_NOW) is None


def test_build_config_rejects_non_positive_offset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(_ENV_SOURCE, "/subscriptions/x/resourceGroups/rg/servers/s")
    monkeypatch.setenv(_ENV_LOCATION, "koreacentral")
    monkeypatch.setenv(_ENV_PITR_OFFSET, "0")
    assert _build_config(_FIXED_NOW) is None


def test_build_config_rejects_server_name_over_63_chars(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(_ENV_SOURCE, "/subscriptions/x/resourceGroups/rg/servers/s")
    monkeypatch.setenv(_ENV_LOCATION, "koreacentral")
    # 63-char limit; the CLI appends "-MMDDHHMM" (9 chars) so a 55+ char
    # prefix already blows the ceiling.
    monkeypatch.setenv(_ENV_SERVER_PREFIX, "x" * 56)
    assert _build_config(_FIXED_NOW) is None


def test_build_config_custom_offset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(_ENV_SOURCE, "/subscriptions/x/resourceGroups/rg/servers/s")
    monkeypatch.setenv(_ENV_LOCATION, "koreacentral")
    monkeypatch.setenv(_ENV_PITR_OFFSET, "60")
    cfg = _build_config(_FIXED_NOW)
    assert cfg is not None
    assert cfg.point_in_time_utc == _FIXED_NOW - timedelta(minutes=60)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def test_main_returns_2_on_missing_source() -> None:
    assert main() == 2


def test_main_dry_run_returns_0(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(_ENV_SOURCE, "/subscriptions/x/resourceGroups/rg/servers/s")
    monkeypatch.setenv(_ENV_LOCATION, "koreacentral")
    monkeypatch.setenv(_ENV_DRY_RUN, "1")
    assert main() == 0


def test_main_dry_run_accepts_yes_and_true(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(_ENV_SOURCE, "/subscriptions/x/resourceGroups/rg/servers/s")
    monkeypatch.setenv(_ENV_LOCATION, "koreacentral")

    monkeypatch.setenv(_ENV_DRY_RUN, "yes")
    assert main() == 0
    monkeypatch.setenv(_ENV_DRY_RUN, "true")
    assert main() == 0


def test_main_without_dry_run_returns_2_upstream(monkeypatch: pytest.MonkeyPatch) -> None:
    """Upstream refuses to run a live drill.

    The upstream CLI has no fork-specific credential binding, so a
    live run cannot proceed. Exit 2 documents the missing binding
    without pretending a drill happened.
    """
    monkeypatch.setenv(_ENV_SOURCE, "/subscriptions/x/resourceGroups/rg/servers/s")
    monkeypatch.setenv(_ENV_LOCATION, "koreacentral")
    assert main() == 2


@pytest.mark.parametrize(
    ("outcome", "expected_exit"),
    [
        (DbDrOutcome.PASSED, 0),
        (DbDrOutcome.INTEGRITY_FAILED, 3),
        (DbDrOutcome.CLEANUP_FAILED, 3),
    ],
)
def test_main_runs_injected_live_drill(
    monkeypatch: pytest.MonkeyPatch,
    outcome: DbDrOutcome,
    expected_exit: int,
) -> None:
    monkeypatch.setenv(_ENV_SOURCE, "/subscriptions/x/resourceGroups/rg/servers/s")
    monkeypatch.setenv(_ENV_LOCATION, "koreacentral")
    seen_experiment_ids: list[str] = []

    async def run_drill(config: DbRestoreConfig) -> DbDrVerdict:
        experiment_id = config.experiment_id
        seen_experiment_ids.append(experiment_id)
        return DbDrVerdict(
            experiment_id=experiment_id,
            outcome=outcome,
            cleanup_succeeded=outcome is DbDrOutcome.PASSED,
        )

    assert main(run_drill) == expected_exit
    assert len(seen_experiment_ids) == 1
    assert seen_experiment_ids[0].startswith("db-dr-drill-")


def test_main_exception_returns_exit_4(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _boom() -> int:
        raise RuntimeError("simulated CLI crash")

    monkeypatch.setattr(db_dr_drill_cli, "_amain", _boom)
    assert main() == 4
