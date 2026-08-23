"""Measurement composition-root CLI tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from fdai.delivery import measurement_runner_cli


def test_invalid_mode_returns_two() -> None:
    assert measurement_runner_cli.main(["invalid"]) == 2


def test_baseline_missing_required_env_returns_three(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("FDAI_STATE_STORE_DSN", raising=False)
    monkeypatch.delenv("FDAI_SCENARIO_SET_VERSION", raising=False)
    assert measurement_runner_cli.main(["baseline"]) == 3


def test_baseline_success_returns_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _success() -> int:
        return 0

    monkeypatch.setattr(measurement_runner_cli, "_run_baseline", _success)
    assert measurement_runner_cli.main(["baseline"]) == 0


def test_growth_unwired_fails_nonzero() -> None:
    assert measurement_runner_cli.main(["growth"]) == 3


def test_growth_success_returns_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _success() -> int:
        return 0

    monkeypatch.setattr(measurement_runner_cli, "_run_growth", _success)
    assert measurement_runner_cli.main(["growth"]) == 0


def test_operational_promotion_missing_required_env_returns_three(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("FDAI_STATE_STORE_DSN", raising=False)
    monkeypatch.delenv("FDAI_REVISION", raising=False)
    monkeypatch.delenv("FDAI_SCENARIO_SET_VERSION", raising=False)
    monkeypatch.delenv("FDAI_OPERATIONAL_PROMOTION_MANIFEST", raising=False)
    assert measurement_runner_cli.main(["operational-promotion"]) == 3


def test_operational_promotion_success_returns_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _success() -> int:
        return 0

    monkeypatch.setattr(measurement_runner_cli, "_run_operational_promotion", _success)
    assert measurement_runner_cli.main(["operational-promotion"]) == 0


def test_operational_promotion_manifest_cannot_escape_evidence_root(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside-manifest.json"
    outside.write_text("{}", encoding="utf-8")

    with pytest.raises(ValueError, match="escapes its configured root"):
        measurement_runner_cli._bounded_evidence_path(
            root=tmp_path.resolve(),
            value="../outside-manifest.json",
        )


def test_catalog_root_does_not_require_test_scenarios(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog = tmp_path / "rule-catalog"
    catalog.mkdir()
    monkeypatch.chdir(tmp_path)

    assert measurement_runner_cli._catalog_root() == catalog
