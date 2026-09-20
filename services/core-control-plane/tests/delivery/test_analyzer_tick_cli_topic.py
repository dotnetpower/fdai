from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fdai.delivery import analyzer_run_receipt as analyzer_run_receipt_module
from fdai.delivery import analyzer_tick_cli as analyzer_tick_cli_module
from fdai.delivery import analyzer_tick_cli_composition as analyzer_composition
from fdai.delivery.analyzer_run_receipt import (
    AnalyzerRunReceiptPersistenceError,
    record_analyzer_run_receipt,
    resolve_analyzer_run_id,
)
from fdai.delivery.analyzer_targets import (
    AnalyzerResourceTypeResolution,
    AnalyzerTargetResolution,
    AnalyzerTargetResolutionError,
)
from fdai.delivery.analyzer_tick import (
    AnalyzerFindingReceipt,
    AnalyzerPublicationStatus,
    AnalyzerTarget,
    AnalyzerTickReport,
)
from fdai.delivery.analyzer_tick_cli import (
    BUDGET_ENV,
    INGRESS_TOPIC_ENV,
    LOOP_INTERVAL_ENV,
    TOPIC_ENV,
    TRACE_WINDOW_ENV,
    AnalyzerJobReport,
    build_decision_evidence_admission_provider,
    build_publication_ledger,
    metric_source_delays,
    parse_loop_interval,
    parse_tick_budget,
    resolve_finding_topic,
    resolve_scheduling_mode,
    resolve_trace_lookback_seconds,
    resolve_trace_window_seconds,
    run_loop,
)
from fdai.delivery.trace_continuity_tick import TraceContinuityTickReport
from fdai.runtime.venue import ExecutionVenue

_REPO_ROOT = Path(__file__).resolve().parents[4]


def test_findings_default_to_the_raw_ingress_topic() -> None:
    assert resolve_finding_topic({INGRESS_TOPIC_ENV: "fdai.change.events"}) == "fdai.change.events"


def test_explicit_analyzer_topic_overrides_the_ingress_topic() -> None:
    environ = {TOPIC_ENV: "fdai.custom.events", INGRESS_TOPIC_ENV: "fdai.change.events"}

    assert resolve_finding_topic(environ) == "fdai.custom.events"


def test_missing_ingress_topic_is_a_configuration_error() -> None:
    with pytest.raises(RuntimeError):
        resolve_finding_topic({TOPIC_ENV: "   "})


def test_publication_ledger_requires_the_shared_state_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("FDAI_STATE_STORE_DSN", raising=False)

    with pytest.raises(RuntimeError, match="duplicate-safe analyzer publication"):
        build_publication_ledger()


def test_publication_ledger_accepts_the_shared_psycopg_dsn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FDAI_STATE_STORE_DSN", "postgresql+psycopg://localhost/fdai")

    assert build_publication_ledger().__class__.__name__ == "PostgresAnalyzerPublicationLedger"


def test_missing_state_store_leaves_target_admission_unbound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("FDAI_STATE_STORE_DSN", raising=False)

    assert build_decision_evidence_admission_provider() is None


async def test_target_admission_provider_closes_analyzer_owned_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = SimpleNamespace(aclose=AsyncMock())
    monkeypatch.setenv("FDAI_STATE_STORE_DSN", "postgresql://example/fdai")
    monkeypatch.setattr(analyzer_composition, "PostgresStateStore", lambda **_: store)

    provider = build_decision_evidence_admission_provider()
    assert provider is not None

    await provider.aclose()

    store.aclose.assert_awaited_once_with()


def test_run_receipts_prefer_explicit_then_platform_execution_identity() -> None:
    assert (
        resolve_analyzer_run_id(
            {
                "FDAI_ANALYZER_RUN_ID": "manual-run-1",
                "CONTAINER_APP_JOB_EXECUTION_NAME": "platform-run-1",
            }
        )
        == "manual-run-1"
    )
    assert (
        resolve_analyzer_run_id({"CONTAINER_APP_JOB_EXECUTION_NAME": "platform-run-1"})
        == "platform-run-1"
    )
    assert resolve_analyzer_run_id({}) is None


def test_run_receipts_reject_unstable_whitespace_identity() -> None:
    with pytest.raises(ValueError, match="run identity"):
        resolve_analyzer_run_id({"FDAI_ANALYZER_RUN_ID": "run 1"})


async def test_run_receipt_wraps_only_the_persistence_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    closed = False

    class FailingStore:
        async def record(self, **_values: object) -> None:
            raise ConnectionError("database unavailable")

        async def aclose(self) -> None:
            nonlocal closed
            closed = True

    monkeypatch.setattr(
        analyzer_run_receipt_module,
        "build_analyzer_run_receipt_store",
        lambda _environment: FailingStore(),
    )

    with pytest.raises(
        AnalyzerRunReceiptPersistenceError,
        match="ConnectionError",
    ):
        await record_analyzer_run_receipt(
            environment={"FDAI_ANALYZER_RUN_ID": "run-1"},
            tick_id="0",
            recorded_at=datetime(2026, 9, 14, tzinfo=UTC),
            report={"failed": False},
        )
    assert closed is True


def test_trace_window_defaults_to_the_analyzer_window() -> None:
    assert resolve_trace_window_seconds({}, 300) == 300


def test_trace_window_can_be_shortened_independently() -> None:
    assert resolve_trace_window_seconds({TRACE_WINDOW_ENV: "60"}, 300) == 60


def test_non_positive_trace_window_fails_closed() -> None:
    with pytest.raises(ValueError):
        resolve_trace_window_seconds({TRACE_WINDOW_ENV: "0"}, 300)


def test_trace_lookback_covers_the_ingestion_floor() -> None:
    assert resolve_trace_lookback_seconds({}, 60) == 900
    assert (
        resolve_trace_lookback_seconds(
            {"FDAI_TRACE_CONTINUITY_LOOKBACK_SECONDS": "1200"},
            60,
        )
        == 1200
    )


def test_trace_lookback_cannot_shrink_below_detection_window() -> None:
    with pytest.raises(ValueError, match="MUST be at least"):
        resolve_trace_lookback_seconds(
            {"FDAI_TRACE_CONTINUITY_LOOKBACK_SECONDS": "60"},
            300,
        )


def _job_report(
    *,
    publish_failed: bool = False,
    analyzer_failed: bool = False,
    unsupported: bool = False,
) -> AnalyzerJobReport:
    return AnalyzerJobReport(
        analyzer=AnalyzerTickReport(
            targets=1,
            findings=1,
            published=0 if publish_failed else 1,
            unsupported_targets=("resource-a",) if unsupported else (),
            analyzer_errors=(("resource-a", "provider_error"),) if analyzer_failed else (),
            publish_errors=(("key", "RuntimeError:failed"),) if publish_failed else (),
        ),
        trace_continuity=TraceContinuityTickReport(
            targets=0,
            scenarios=0,
            continuous=0,
            unknown=0,
            findings=0,
            published=0,
        ),
        target_resolution=AnalyzerTargetResolution(
            targets=(AnalyzerTarget(resource_ref="resource-a", resource_kind="aks"),),
            configured=0,
            discovered=1,
            inventory_consulted=True,
        ),
    )


def test_job_report_builds_strict_cross_resource_coverage() -> None:
    report = AnalyzerJobReport(
        analyzer=AnalyzerTickReport(targets=2, findings=0, published=0),
        trace_continuity=TraceContinuityTickReport(
            targets=0,
            scenarios=0,
            continuous=0,
            unknown=0,
            findings=0,
            published=0,
        ),
        target_resolution=AnalyzerTargetResolution(
            targets=(
                AnalyzerTarget(
                    resource_ref="resource-api",
                    resource_kind="api_management",
                    resource_type="api-gateway",
                ),
                AnalyzerTarget(
                    resource_ref="resource-db",
                    resource_kind="mysql_flexible_server",
                    resource_type="mysql-server",
                ),
            ),
            configured=0,
            discovered=2,
            inventory_consulted=True,
            candidate_count=3,
            resource_types=(
                AnalyzerResourceTypeResolution(
                    resource_type="api-gateway",
                    candidate_count=2,
                    selected_count=1,
                    held_count=1,
                    held_reason_counts=(("unverified_state_fact", 1),),
                ),
                AnalyzerResourceTypeResolution(
                    resource_type="mysql-server",
                    candidate_count=1,
                    selected_count=1,
                    held_count=0,
                ),
            ),
        ),
    )

    coverage = report.coverage()

    assert coverage["status"] == "available"
    assert coverage["candidate_count"] == 3
    assert coverage["selected_count"] == 2
    assert coverage["evaluated_count"] == 2
    assert coverage["held_count"] == 1
    assert [row["resource_type"] for row in coverage["resource_types"]] == [  # type: ignore[index]
        "api-gateway",
        "mysql-server",
    ]
    assert {
        row["evaluation_state"]
        for row in coverage["resources"]  # type: ignore[index]
    } == {"evaluated_no_finding"}


def test_job_report_withholds_coverage_when_inventory_discovery_is_truncated() -> None:
    report = AnalyzerJobReport(
        analyzer=AnalyzerTickReport(targets=1, findings=0, published=0),
        trace_continuity=TraceContinuityTickReport(
            targets=0,
            scenarios=0,
            continuous=0,
            unknown=0,
            findings=0,
            published=0,
        ),
        target_resolution=AnalyzerTargetResolution(
            targets=(
                AnalyzerTarget(
                    resource_ref="resource-api",
                    resource_kind="api_management",
                    resource_type="api-gateway",
                ),
            ),
            configured=0,
            discovered=1,
            inventory_consulted=True,
            candidate_count=2,
            truncated=True,
            source_complete=True,
            resource_types=(
                AnalyzerResourceTypeResolution(
                    resource_type="api-gateway",
                    candidate_count=2,
                    selected_count=1,
                    held_count=1,
                    held_reason_counts=(("selection_limit", 1),),
                ),
            ),
        ),
    )

    assert report.failed is True
    assert report.readiness(scheduling="one_shot")["target_discovery"] == "unavailable"
    assert report.coverage() == {
        "schema_version": "1.1.0",
        "status": "unavailable",
        "unavailable_reason": "resource_discovery_truncated",
        "cause_claim_supported": False,
        "execution_authority": False,
    }


def test_job_report_preserves_verified_targets_from_incomplete_inventory() -> None:
    report = AnalyzerJobReport(
        analyzer=AnalyzerTickReport(targets=1, findings=0, published=0),
        trace_continuity=TraceContinuityTickReport(
            targets=0,
            scenarios=0,
            continuous=0,
            unknown=0,
            findings=0,
            published=0,
        ),
        target_resolution=AnalyzerTargetResolution(
            targets=(
                AnalyzerTarget(
                    resource_ref="resource-api",
                    resource_kind="api_management",
                    resource_type="api-gateway",
                ),
            ),
            configured=0,
            discovered=1,
            inventory_consulted=True,
            candidate_count=2,
            source_complete=False,
            skipped_reasons=("unverified_state_fact",),
            skipped_reason_counts=(("unverified_state_fact", 1),),
            resource_types=(
                AnalyzerResourceTypeResolution(
                    resource_type="api-gateway",
                    candidate_count=2,
                    selected_count=1,
                    held_count=1,
                    held_reason_counts=(("unverified_state_fact", 1),),
                ),
            ),
        ),
    )

    assert report.failed is False
    assert report.readiness(scheduling="local_loop")["target_discovery"] == "available"
    assert report.coverage()["status"] == "available"
    assert report.coverage()["selected_count"] == 1
    assert report.coverage()["held_count"] == 1


def test_job_report_degrades_duplicate_target_identity_without_crashing() -> None:
    report = AnalyzerJobReport(
        analyzer=AnalyzerTickReport(targets=2, findings=0, published=0),
        trace_continuity=TraceContinuityTickReport(
            targets=0,
            scenarios=0,
            continuous=0,
            unknown=0,
            findings=0,
            published=0,
        ),
        target_resolution=AnalyzerTargetResolution(
            targets=(
                AnalyzerTarget(
                    resource_ref="resource-duplicate",
                    resource_kind="aks_cluster",
                    resource_type="kubernetes-cluster",
                ),
                AnalyzerTarget(
                    resource_ref="resource-duplicate",
                    resource_kind="mysql_flexible_server",
                    resource_type="mysql-server",
                ),
            ),
            configured=0,
            discovered=2,
            inventory_consulted=True,
        ),
    )

    assert report.coverage() == {
        "schema_version": "1.1.0",
        "status": "unavailable",
        "unavailable_reason": "selected_resource_identity_duplicate",
        "cause_claim_supported": False,
        "execution_authority": False,
    }


def test_job_report_preserves_exact_finding_publication_state() -> None:
    receipt = AnalyzerFindingReceipt(
        idempotency_key="analyzer:resource-aks:cpu",
        signal="cpu_pressure",
        detection_latency_seconds=4.0,
        evidence_complete=True,
        publication=AnalyzerPublicationStatus.DUPLICATE_SUPPRESSED,
        recovery_closed=None,
        evidence_refs=("node_cpu_usage_percentage",),
        resource_ref="resource-aks",
        resource_kind="aks_cluster",
        occurred_at=datetime(2026, 9, 14, 3, 29, 56, tzinfo=UTC),
    )
    report = AnalyzerJobReport(
        analyzer=AnalyzerTickReport(
            targets=1,
            findings=1,
            published=0,
            duplicates_suppressed=1,
            receipts=(receipt,),
        ),
        trace_continuity=TraceContinuityTickReport(
            targets=0,
            scenarios=0,
            continuous=0,
            unknown=0,
            findings=0,
            published=0,
        ),
        target_resolution=AnalyzerTargetResolution(
            targets=(
                AnalyzerTarget(
                    resource_ref="resource-aks",
                    resource_kind="aks_cluster",
                    resource_type="kubernetes-cluster",
                ),
            ),
            configured=0,
            discovered=1,
            inventory_consulted=True,
            candidate_count=1,
            resource_types=(
                AnalyzerResourceTypeResolution(
                    resource_type="kubernetes-cluster",
                    candidate_count=1,
                    selected_count=1,
                    held_count=0,
                ),
            ),
        ),
    )

    coverage = report.coverage()

    assert coverage["finding_count"] == 1
    assert coverage["publication_counts"]["duplicate_suppressed"] == 1  # type: ignore[index]
    assert coverage["resources"][0]["evaluation_state"] == "finding"  # type: ignore[index]


@pytest.mark.parametrize(
    ("analyzer_error", "expected_code"),
    (
        ("timeout", "analyzer_timeout"),
        ("provider_error", "analyzer_failure"),
    ),
)
def test_job_report_exposes_bounded_analyzer_error_codes(
    analyzer_error: str,
    expected_code: str,
) -> None:
    report = AnalyzerJobReport(
        analyzer=AnalyzerTickReport(
            targets=1,
            findings=0,
            published=0,
            analyzer_errors=(("resource-aks", analyzer_error),),
        ),
        trace_continuity=TraceContinuityTickReport(
            targets=0,
            scenarios=0,
            continuous=0,
            unknown=0,
            findings=0,
            published=0,
        ),
        target_resolution=AnalyzerTargetResolution(
            targets=(
                AnalyzerTarget(
                    resource_ref="resource-aks",
                    resource_kind="aks_cluster",
                    resource_type="kubernetes-cluster",
                ),
            ),
            configured=0,
            discovered=1,
            inventory_consulted=True,
            resource_types=(
                AnalyzerResourceTypeResolution(
                    resource_type="kubernetes-cluster",
                    candidate_count=1,
                    selected_count=1,
                    held_count=0,
                ),
            ),
        ),
    )

    coverage = report.coverage()

    assert coverage["error_count"] == 1
    assert coverage["resources"][0]["error_codes"] == [expected_code]  # type: ignore[index]
    assert coverage["resource_types"][0]["error_codes"] == [expected_code]  # type: ignore[index]


def test_job_report_attributes_publication_failure_to_finding_resource() -> None:
    receipt = AnalyzerFindingReceipt(
        idempotency_key="analyzer:resource-aks:cpu",
        signal="cpu_pressure",
        detection_latency_seconds=4.0,
        evidence_complete=True,
        publication=AnalyzerPublicationStatus.FAILED,
        recovery_closed=None,
        evidence_refs=("node_cpu_usage_percentage",),
        resource_ref="resource-aks",
        resource_kind="aks_cluster",
        occurred_at=datetime(2026, 9, 14, 3, 29, 56, tzinfo=UTC),
    )
    report = AnalyzerJobReport(
        analyzer=AnalyzerTickReport(
            targets=1,
            findings=1,
            published=0,
            publish_errors=((receipt.idempotency_key, "RuntimeError:failed"),),
            receipts=(receipt,),
        ),
        trace_continuity=TraceContinuityTickReport(
            targets=0,
            scenarios=0,
            continuous=0,
            unknown=0,
            findings=0,
            published=0,
        ),
        target_resolution=AnalyzerTargetResolution(
            targets=(
                AnalyzerTarget(
                    resource_ref="resource-aks",
                    resource_kind="aks_cluster",
                    resource_type="kubernetes-cluster",
                ),
            ),
            configured=0,
            discovered=1,
            inventory_consulted=True,
            resource_types=(
                AnalyzerResourceTypeResolution(
                    resource_type="kubernetes-cluster",
                    candidate_count=1,
                    selected_count=1,
                    held_count=0,
                ),
            ),
        ),
    )

    coverage = report.coverage()

    assert coverage["error_count"] == 1
    assert coverage["unattributed_error_count"] == 0
    assert coverage["resources"][0]["error_codes"] == ["publication_failure"]  # type: ignore[index]


def test_loop_interval_uses_one_bounded_contract() -> None:
    assert parse_loop_interval("") == 60
    assert parse_loop_interval("15") == 15
    for value in ("0", "86401", "invalid"):
        with pytest.raises(ValueError, match=LOOP_INTERVAL_ENV):
            parse_loop_interval(value)


def test_tick_budget_matches_the_deployed_job_ceiling() -> None:
    assert parse_tick_budget("") == 300
    assert parse_tick_budget("45") == 45
    for value in ("0", "301", "invalid"):
        with pytest.raises(ValueError, match=BUDGET_ENV):
            parse_tick_budget(value)


def test_local_finding_bus_uses_plaintext_without_workload_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class _Bus:
        def __init__(self, *, identity: object, config: object) -> None:
            captured["identity"] = identity
            captured["config"] = config

    monkeypatch.setattr(analyzer_tick_cli_module, "EventHubsKafkaBus", _Bus)
    analyzer_tick_cli_module._build_finding_bus(  # type: ignore[arg-type]
        identity=object(),  # type: ignore[arg-type]
        bootstrap_servers="127.0.0.1:9092",
        venue=ExecutionVenue.LOCAL,
    )

    assert captured["identity"] is None
    assert captured["config"].security_protocol == "PLAINTEXT"  # type: ignore[union-attr]


def test_readiness_separates_scheduling_discovery_metrics_and_publication() -> None:
    readiness = _job_report().readiness(
        scheduling="local_loop",
        metric_delays={"log_analytics": "120-300_seconds", "prometheus": "unbound"},
    )

    assert readiness == {
        "scheduling": "local_loop",
        "target_discovery": "available",
        "metric_access": "available",
        "event_publication": "verified",
        "metric_source_delays": {
            "log_analytics": "120-300_seconds",
            "prometheus": "unbound",
        },
    }


def test_suppressed_duplicate_retains_verified_publication_readiness() -> None:
    report = _job_report()
    report = AnalyzerJobReport(
        analyzer=AnalyzerTickReport(
            targets=report.analyzer.targets,
            findings=report.analyzer.findings,
            published=0,
            duplicates_suppressed=1,
        ),
        trace_continuity=report.trace_continuity,
        target_resolution=report.target_resolution,
    )

    assert report.readiness(scheduling="local_loop")["event_publication"] == "verified"


@pytest.mark.parametrize(
    "report",
    (
        _job_report(analyzer_failed=True),
        _job_report(unsupported=True),
    ),
)
def test_analyzer_coverage_failure_is_not_a_successful_job(
    report: AnalyzerJobReport,
) -> None:
    assert report.failed
    assert report.readiness(scheduling="local_loop")["metric_access"] == "unavailable"


@pytest.mark.parametrize(
    "resolution",
    (
        AnalyzerTargetResolution(
            targets=(),
            configured=0,
            discovered=200,
            inventory_consulted=True,
            truncated=True,
        ),
        AnalyzerTargetResolution(
            targets=(),
            configured=0,
            discovered=1,
            inventory_consulted=True,
            source_complete=False,
        ),
    ),
)
def test_incomplete_target_coverage_fails_job_and_readiness(
    resolution: AnalyzerTargetResolution,
) -> None:
    report = _job_report()
    report = AnalyzerJobReport(
        analyzer=report.analyzer,
        trace_continuity=report.trace_continuity,
        target_resolution=resolution,
    )

    assert report.failed
    assert report.readiness(scheduling="local_loop")["target_discovery"] == "unavailable"


def test_scheduling_mode_and_metric_delays_are_explicit() -> None:
    assert resolve_scheduling_mode("") == "one_shot"
    assert resolve_scheduling_mode("container_apps_job") == "container_apps_job"
    with pytest.raises(ValueError, match="SCHEDULING"):
        resolve_scheduling_mode("implicit")
    assert metric_source_delays({}) == {
        "log_analytics": "unbound",
        "prometheus": "unbound",
    }
    assert metric_source_delays(
        {
            "FDAI_MONITOR_WORKSPACE_ID": "configured",
            "FDAI_PROMETHEUS_ENDPOINT": "https://metrics.example",
        }
    ) == {
        "log_analytics": "120-300_seconds",
        "prometheus": "unbound_exact_resource_identity",
    }


async def test_persisted_receipt_uses_the_exact_operational_report_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    async def record_receipt(**values: object) -> None:
        captured.update(values)

    monkeypatch.setenv("FDAI_ANALYZER_RUN_ID", "test-run-1")
    monkeypatch.setenv("FDAI_MONITOR_WORKSPACE_ID", "configured")
    monkeypatch.setenv("FDAI_PROMETHEUS_ENDPOINT", "https://metrics.example")
    monkeypatch.setattr(analyzer_tick_cli_module, "record_analyzer_run_receipt", record_receipt)
    report = _job_report()

    await analyzer_tick_cli_module._record_run_receipt(
        report,
        scheduling="local_loop",
        tick_id="7",
    )

    assert captured["environment"]["FDAI_ANALYZER_RUN_ID"] == "test-run-1"  # type: ignore[index]
    assert captured["tick_id"] == "7"
    assert captured["report"] == analyzer_tick_cli_module._report_body(
        report,
        scheduling="local_loop",
    )


async def test_local_loop_runs_serial_ticks_and_stops_after_the_bound(
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls = 0
    sleeps: list[float] = []
    monotonic = iter((10.0, 12.0, 15.0))

    async def tick() -> AnalyzerJobReport:
        nonlocal calls
        calls += 1
        return _job_report()

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)

    result = await run_loop(
        interval_seconds=5,
        max_ticks=2,
        tick=tick,
        sleep=sleep,
        monotonic=lambda: next(monotonic),
    )

    assert result == 0
    assert calls == 2
    assert sleeps == [3.0]
    assert capsys.readouterr().out.count("service=local-analyzer event=ready") == 2


async def test_local_loop_does_not_add_delay_after_a_slow_tick() -> None:
    calls = 0
    sleeps: list[float] = []
    monotonic = iter((10.0, 17.0, 17.0))

    async def tick() -> AnalyzerJobReport:
        nonlocal calls
        calls += 1
        return _job_report()

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)

    result = await run_loop(
        interval_seconds=5,
        max_ticks=2,
        tick=tick,
        sleep=sleep,
        monotonic=lambda: next(monotonic),
    )

    assert result == 0
    assert calls == 2
    assert sleeps == [0.0]


async def test_bounded_local_loop_returns_failure_for_its_final_tick(
    capsys: pytest.CaptureFixture[str],
) -> None:
    slept = False

    async def sleep(_seconds: float) -> None:
        nonlocal slept
        slept = True

    result = await run_loop(
        interval_seconds=5,
        max_ticks=1,
        tick=lambda: _async_report(_job_report(publish_failed=True)),
        sleep=sleep,
    )

    assert result == 1
    assert slept is False
    output = capsys.readouterr().out
    assert "service=local-analyzer event=failed" in output
    assert "service=local-analyzer event=ready" not in output


async def test_local_loop_retries_a_failed_tick_until_ready(
    capsys: pytest.CaptureFixture[str],
) -> None:
    reports = iter((_job_report(publish_failed=True), _job_report()))
    monotonic = iter((10.0, 11.0, 15.0))
    sleeps: list[float] = []

    result = await run_loop(
        interval_seconds=5,
        max_ticks=2,
        tick=lambda: _async_report(next(reports)),
        sleep=lambda seconds: _record_sleep(sleeps, seconds),
        monotonic=lambda: next(monotonic),
    )

    assert result == 0
    assert sleeps == [4.0]
    output = capsys.readouterr().out
    assert output.index("event=waiting reason=tick_failed") < output.index("event=ready")
    assert "event=failed" not in output


async def test_local_loop_retries_target_resolution_failure_until_ready(
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls = 0
    monotonic = iter((10.0, 11.0, 15.0))
    sleeps: list[float] = []

    async def tick() -> AnalyzerJobReport:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise AnalyzerTargetResolutionError("active snapshot unavailable")
        return _job_report()

    result = await run_loop(
        interval_seconds=60,
        max_ticks=2,
        tick=tick,
        sleep=lambda seconds: _record_sleep(sleeps, seconds),
        monotonic=lambda: next(monotonic),
    )

    assert result == 0
    assert calls == 2
    assert sleeps == [4.0]
    output = capsys.readouterr().out
    assert output.index("reason=target_resolution_unavailable") < output.index("event=ready")
    assert "event=failed" not in output


async def test_local_loop_retries_run_receipt_failure_until_ready(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    receipt_calls = 0
    monotonic = iter((10.0, 11.0, 15.0))
    sleeps: list[float] = []

    async def record_receipt(
        _report: AnalyzerJobReport,
        *,
        scheduling: str,
        tick_id: str,
    ) -> None:
        del scheduling, tick_id
        nonlocal receipt_calls
        receipt_calls += 1
        if receipt_calls == 1:
            raise AnalyzerRunReceiptPersistenceError("state store unavailable")

    monkeypatch.setattr(analyzer_tick_cli_module, "_record_run_receipt", record_receipt)

    result = await run_loop(
        interval_seconds=5,
        max_ticks=2,
        tick=lambda: _async_report(_job_report()),
        sleep=lambda seconds: _record_sleep(sleeps, seconds),
        monotonic=lambda: next(monotonic),
    )

    assert result == 0
    assert receipt_calls == 2
    assert sleeps == [4.0]
    output = capsys.readouterr().out
    assert output.index("reason=run_receipt_unavailable") < output.index("event=ready")
    assert output.count('"scheduling": "local_loop"') == 1


async def test_local_loop_does_not_hide_unexpected_tick_errors() -> None:
    async def broken_tick() -> AnalyzerJobReport:
        raise RuntimeError("programming defect")

    with pytest.raises(RuntimeError, match="programming defect"):
        await run_loop(
            interval_seconds=5,
            max_ticks=2,
            tick=broken_tick,
        )


async def test_local_loop_stops_when_one_tick_exceeds_the_deployed_deadline(
    capsys: pytest.CaptureFixture[str],
) -> None:
    async def stalled_tick() -> AnalyzerJobReport:
        await asyncio.sleep(1)
        return _job_report()

    result = await run_loop(
        interval_seconds=5,
        max_ticks=1,
        tick_timeout_seconds=0.01,
        tick=stalled_tick,
    )

    assert result == 1
    assert "reason=tick_deadline" in capsys.readouterr().out


async def test_local_loop_retries_a_tick_deadline_until_ready(
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls = 0

    async def tick() -> AnalyzerJobReport:
        nonlocal calls
        calls += 1
        if calls == 1:
            await asyncio.sleep(1)
        return _job_report()

    result = await run_loop(
        interval_seconds=1,
        max_ticks=2,
        tick_timeout_seconds=0.01,
        tick=tick,
        sleep=lambda _seconds: asyncio.sleep(0),
    )

    assert result == 0
    assert calls == 2
    output = capsys.readouterr().out
    assert output.index("reason=tick_deadline") < output.index("event=ready")
    assert "event=failed" not in output


async def _async_report(report: AnalyzerJobReport) -> AnalyzerJobReport:
    return report


async def _record_sleep(sleeps: list[float], seconds: float) -> None:
    sleeps.append(seconds)


def test_vscode_task_reuses_the_deployed_analyzer_cli() -> None:
    tasks = (_REPO_ROOT / ".vscode/tasks.json").read_text(encoding="utf-8")
    launcher = (_REPO_ROOT / "scripts/deployment/local/run-console-service.sh").read_text(
        encoding="utf-8"
    )
    supervisor = (_REPO_ROOT / "scripts/deployment/local/start-console-services.sh").read_text(
        encoding="utf-8"
    )
    compatibility_launcher = (
        _REPO_ROOT / "scripts/deployment/local/run-analyzer-loop.sh"
    ).read_text(encoding="utf-8")

    assert '"label": "analyzer: run continuously (local)"' in tasks
    assert "console: prepare full stack" in tasks
    assert (
        "bash scripts/deployment/local/run-console-service.sh local-analyzer --wait-ready" in tasks
    )
    assert "fdai.delivery.analyzer_tick_cli --loop" in launcher
    assert "  local-analyzer\n" in supervisor
    assert 'run-console-service.sh" local-analyzer' in compatibility_launcher
    assert 'FDAI_ANALYZER_RUN_ID="$local_analyzer_run_id"' in launcher
    assert "local-analyzer-$(date -u +%s)-$$" in launcher
