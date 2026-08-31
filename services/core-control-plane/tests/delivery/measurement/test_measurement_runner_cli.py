"""Measurement composition-root CLI tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fdai.delivery import measurement_runner_cli
from fdai.shared.providers.testing.state_store import InMemoryStateStore

_NOW = datetime(2026, 8, 31, 1, tzinfo=UTC)


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


def _phase4_batch(
    batch_id: str,
    *,
    observed_at: datetime = _NOW,
    complete: bool = True,
    rollback_of: str | None = None,
) -> dict[str, object]:
    return {
        "schema_version": "1.0.0",
        "batch_id": batch_id,
        "observed_at": observed_at.isoformat(),
        "complete": complete,
        "rollback_of": rollback_of,
        "incumbent": {
            "model_id": "model-a",
            "scenario_set_version": "v2026.07",
            "quality_score": 0.7,
            "cost_per_verified_answer": 1.0,
            "verifier_abstain_rate": 0.05,
            "mixed_model_disagreement_rate": 0.05,
        },
        "challenger": {
            "model_id": "model-b",
            "scenario_set_version": "v2026.07",
            "quality_score": 0.8,
            "cost_per_verified_answer": 0.8,
            "verifier_abstain_rate": 0.05,
            "mixed_model_disagreement_rate": 0.05,
        },
        "latency": [
            {
                "tier": tier,
                "budget_p95_ms": 1000,
                "sample_size": 100,
                "p50_ms": 10,
                "p95_ms": 20,
                "p99_ms": 30,
            }
            for tier in ("T0", "T1", "T2")
        ],
    }


async def test_policy_cli_composition_is_restart_and_duplicate_safe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = InMemoryStateStore()
    await store.write_state(
        "measurement:phase4:evidence:batch-1",
        _phase4_batch("batch-1"),
    )
    runner_type = measurement_runner_cli.MeasuredPolicyRunner
    monkeypatch.setattr(
        measurement_runner_cli,
        "MeasuredPolicyRunner",
        lambda **kwargs: runner_type(**kwargs, clock=lambda: _NOW),
    )

    first = await measurement_runner_cli._run_measured_policy(store)
    restarted = await measurement_runner_cli._run_measured_policy(store)

    assert first.processed_count == 1
    assert restarted.processed_count == 0
    assert restarted.duplicate_count == 1


async def test_policy_cli_composition_handles_partial_stale_and_rollback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = InMemoryStateStore()
    for batch in (
        _phase4_batch("partial", complete=False),
        _phase4_batch("stale", observed_at=_NOW - timedelta(days=2)),
        _phase4_batch("rollback", rollback_of="prior-batch"),
    ):
        await store.write_state(
            f"measurement:phase4:evidence:{batch['batch_id']}",
            batch,
        )
    runner_type = measurement_runner_cli.MeasuredPolicyRunner
    monkeypatch.setattr(
        measurement_runner_cli,
        "MeasuredPolicyRunner",
        lambda **kwargs: runner_type(**kwargs, clock=lambda: _NOW),
    )

    report = await measurement_runner_cli._run_measured_policy(store)

    assert report.processed_count == 3
    assert report.rejected_count == 2
    assert report.rollback_count == 1
