"""Measurement composition-root CLI tests."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fdai.core.measurement.runners import PatternGrowthReport
from fdai.delivery import measurement_runner_cli
from fdai.delivery.measurement.cohort_inventory import CohortEvidenceInventory
from fdai.shared.providers.testing.state_store import InMemoryStateStore

_NOW = datetime(2026, 8, 31, 1, tzinfo=UTC)
_REPO_ROOT = Path(__file__).resolve().parents[5]


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


def test_cohort_inventory_missing_required_env_returns_three(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("FDAI_STATE_STORE_DSN", raising=False)
    monkeypatch.delenv("FDAI_COHORT_REVISION", raising=False)
    assert measurement_runner_cli.main(["cohort-inventory"]) == 3


def test_cohort_inventory_success_returns_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _success() -> int:
        return 0

    monkeypatch.setattr(measurement_runner_cli, "_run_cohort_inventory", _success)
    assert measurement_runner_cli.main(["cohort-inventory"]) == 0


def test_cohort_inventory_not_ready_returns_three(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Source:
        def __init__(self, **_: object) -> None:
            pass

        async def inventory(self, *, evaluated_at: datetime) -> CohortEvidenceInventory:
            return CohortEvidenceInventory(
                window_start=evaluated_at - timedelta(days=90),
                window_end=evaluated_at,
                candidate_action_outcomes=0,
                candidate_resolved_incidents=0,
                candidate_changes=0,
                candidate_cost_units=0,
                metric_counts={"baseline": {}, "treatment": {}},
                guard_counts={"baseline": {}, "treatment": {}},
                minimum_sample_size=30,
                ready=False,
                missing=("baseline:metric:auto_resolution_rate:0/30",),
            )

    monkeypatch.setenv("FDAI_STATE_STORE_DSN", "postgresql://example")
    monkeypatch.setenv(
        "FDAI_COHORT_REVISION",
        "0123456789abcdef0123456789abcdef01234567",
    )
    monkeypatch.setattr(measurement_runner_cli, "_repo_root", lambda: _REPO_ROOT)
    monkeypatch.setattr(
        measurement_runner_cli,
        "PostgresCohortEvidenceInventorySource",
        _Source,
    )

    assert measurement_runner_cli.main(["cohort-inventory"]) == 3


def test_growth_unwired_fails_nonzero(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FDAI_STATE_STORE_DSN", raising=False)
    assert measurement_runner_cli.main(["growth"]) == 3


def test_growth_success_returns_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _success() -> int:
        return 0

    monkeypatch.setattr(measurement_runner_cli, "_run_growth", _success)
    assert measurement_runner_cli.main(["growth"]) == 0


def test_dynamic_learning_mode_has_no_azure_or_embedding_prerequisites(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FDAI_STATE_STORE_DSN", "postgresql://example")
    monkeypatch.delenv("FDAI_LLM_ENDPOINT", raising=False)
    store = InMemoryStateStore()

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("scalar learning must not compose an Azure/embedding runtime")

    class Runner:
        def __init__(self, **kwargs: Any) -> None:
            assert kwargs["audit_store"] is store

        async def run_once(self) -> Any:
            return SimpleNamespace(total_outcomes=0, accepted_count=0, rejected_count=0)

    monkeypatch.setattr(measurement_runner_cli, "default_container_from_env", forbidden)
    monkeypatch.setattr(measurement_runner_cli, "wire_azure_container", forbidden)
    monkeypatch.setattr(measurement_runner_cli, "PostgresStateStore", lambda **_: store)
    monkeypatch.setattr(measurement_runner_cli, "DynamicLearningRunner", Runner)
    assert measurement_runner_cli.main(["dynamic-learning"]) == 0


async def test_legacy_growth_commits_scalar_before_pattern_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    completed: list[str] = []

    async def scalar() -> int:
        completed.append("scalar")
        return 0

    async def pattern() -> int:
        assert completed == ["scalar"]
        raise RuntimeError("embedding unavailable")

    async def graph() -> int:
        completed.append("graph")
        return 0

    monkeypatch.setattr(measurement_runner_cli, "_run_dynamic_learning", scalar)
    monkeypatch.setattr(measurement_runner_cli, "_run_pattern_growth", pattern)
    monkeypatch.setattr(measurement_runner_cli, "_run_graph_dynamic", graph)
    assert await measurement_runner_cli._amain(["growth"]) == 3
    assert completed == ["scalar", "graph"]


async def test_deletion_fence_refusal_keeps_other_consumers_independent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    completed: list[str] = []

    async def scalar() -> int:
        completed.append("scalar")
        return 0

    async def refused() -> int:
        raise PermissionError("source deletion fence holds pattern write")

    async def graph() -> int:
        completed.append("graph")
        return 0

    monkeypatch.setattr(measurement_runner_cli, "_run_dynamic_learning", scalar)
    monkeypatch.setattr(measurement_runner_cli, "_run_pattern_growth", refused)
    monkeypatch.setattr(measurement_runner_cli, "_run_graph_dynamic", graph)
    assert await measurement_runner_cli._run_growth() == 3
    assert completed == ["scalar", "graph"]


@pytest.mark.parametrize("configured", [True, False])
async def test_growth_writer_uses_exact_configured_pattern_dsn(
    monkeypatch: pytest.MonkeyPatch,
    configured: bool,
) -> None:
    state_dsn = "postgresql://example/state"
    pattern_dsn = "postgresql://example/patterns"
    monkeypatch.setenv("FDAI_STATE_STORE_DSN", state_dsn)
    if configured:
        monkeypatch.setenv("FDAI_T1_PATTERN_LIBRARY_DSN", pattern_dsn)
    else:
        monkeypatch.delenv("FDAI_T1_PATTERN_LIBRARY_DSN", raising=False)
    store = InMemoryStateStore()
    writes: list[str] = []

    @asynccontextmanager
    async def container() -> Any:
        yield SimpleNamespace(
            require_llm_bindings=lambda: SimpleNamespace(embedding_model=SimpleNamespace(dim=384))
        )

    class Writer:
        def __init__(self, *, config: Any) -> None:
            writes.append(config.dsn)

    class Runner:
        def __init__(self, **kwargs: Any) -> None:
            assert kwargs["outcome_source"]._dsn == state_dsn
            assert kwargs["pattern_builder"]._delegate._dsn == state_dsn

        async def run_once(self) -> PatternGrowthReport:
            return PatternGrowthReport()

    monkeypatch.setattr(measurement_runner_cli, "_azure_learning_container", container)
    monkeypatch.setattr(measurement_runner_cli, "PostgresStateStore", lambda **_: store)
    monkeypatch.setattr(measurement_runner_cli, "PostgresShadowPatternWriter", Writer)
    monkeypatch.setattr(measurement_runner_cli, "PatternGrowthIntakeRunner", Runner)
    steps: list[str] = []

    class StatisticsWriter:
        def __init__(self, *, config: Any) -> None:
            writes.append(config.dsn)

    class EvidenceSource:
        def __init__(self, *, dsn: str) -> None:
            assert dsn == state_dsn

    class Producer:
        def __init__(self, **kwargs: Any) -> None:
            assert kwargs["state_store"] is store

        async def publish_holdout_evidence(self) -> Any:
            steps.append("holdout")
            return SimpleNamespace(outcomes=0, envelopes_written=0, complete_envelopes=0)

        async def apply_measured_statistics(self) -> Any:
            steps.append("statistics")
            return SimpleNamespace(patterns_updated=0)

    monkeypatch.setattr(measurement_runner_cli, "PostgresPatternStatisticsWriter", StatisticsWriter)
    monkeypatch.setattr(measurement_runner_cli, "PostgresPatternEvidenceSource", EvidenceSource)
    monkeypatch.setattr(measurement_runner_cli, "PatternEvidenceProducer", Producer)
    assert await measurement_runner_cli._run_pattern_growth() == 0
    expected = pattern_dsn if configured else state_dsn
    assert writes == [expected, expected]
    assert steps == ["holdout", "statistics"]


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


def test_repo_root_uses_the_service_owned_frozen_scenarios(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "rule-catalog").mkdir()
    (tmp_path / measurement_runner_cli.FROZEN_SCENARIO_ASSET_ROOT).mkdir(parents=True)
    monkeypatch.chdir(tmp_path)

    assert measurement_runner_cli._repo_root() == tmp_path


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


@pytest.mark.parametrize(("venue", "developer"), [("local", True), ("deployed", False)])
async def test_learning_container_uses_the_developer_identity_only_on_the_local_venue(
    monkeypatch: pytest.MonkeyPatch,
    venue: str,
    developer: bool,
) -> None:
    monkeypatch.setenv("FDAI_EXECUTION_VENUE", venue)
    monkeypatch.setenv("FDAI_LLM_ENDPOINT", "https://account.openai.azure.com")
    seen: list[type] = []

    resolvers: list[Any] = []

    async def wire(container: Any, *, identity: Any, overrides: Any, **_: Any) -> Any:
        seen.append(type(identity))
        resolvers.append(overrides.model_endpoint_resolver)
        return container

    class _Managed:
        def __init__(self, *, http_client: Any) -> None:
            pass

    monkeypatch.setattr(
        measurement_runner_cli,
        "default_container_from_env",
        lambda: SimpleNamespace(config=SimpleNamespace(llm=SimpleNamespace(mode="azure"))),
    )
    monkeypatch.setattr(measurement_runner_cli, "wire_azure_container", wire)
    monkeypatch.setattr(measurement_runner_cli, "ManagedIdentityWorkloadIdentity", _Managed)
    async with measurement_runner_cli._azure_learning_container():  # noqa: SLF001
        pass
    expected = measurement_runner_cli.AsyncAzureCliWorkloadIdentity if developer else _Managed
    assert seen == [expected]
    # Resolved endpoint bindings need a resolver, or the job cannot bind any model.
    assert resolvers[0]("azure-openai:account") == "https://account.openai.azure.com"
