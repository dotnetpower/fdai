from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fdai.delivery import analyzer_tick_cli as analyzer_tick_cli_module
from fdai.delivery.analyzer_run_receipt import resolve_analyzer_run_id
from fdai.delivery.analyzer_targets import AnalyzerTargetResolution
from fdai.delivery.analyzer_tick import AnalyzerTarget, AnalyzerTickReport
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
        "prometheus": "15_seconds_plus_ingestion",
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
    assert "service=local-analyzer event=ready" in capsys.readouterr().out


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


async def test_local_loop_stops_on_publish_failure_without_sleeping(
    capsys: pytest.CaptureFixture[str],
) -> None:
    slept = False

    async def sleep(_seconds: float) -> None:
        nonlocal slept
        slept = True

    result = await run_loop(
        interval_seconds=5,
        max_ticks=2,
        tick=lambda: _async_report(_job_report(publish_failed=True)),
        sleep=sleep,
    )

    assert result == 1
    assert slept is False
    output = capsys.readouterr().out
    assert "service=local-analyzer event=failed" in output
    assert "service=local-analyzer event=ready" not in output


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


async def _async_report(report: AnalyzerJobReport) -> AnalyzerJobReport:
    return report


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
