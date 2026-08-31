from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fdai.delivery import analyzer_tick_cli as analyzer_tick_cli_module
from fdai.delivery.analyzer_targets import AnalyzerTargetResolution
from fdai.delivery.analyzer_tick import AnalyzerTarget, AnalyzerTickReport
from fdai.delivery.analyzer_tick_cli import (
    BUDGET_ENV,
    INGRESS_TOPIC_ENV,
    LOOP_INTERVAL_ENV,
    TOPIC_ENV,
    TRACE_WINDOW_ENV,
    AnalyzerJobReport,
    build_publication_ledger,
    metric_source_delays,
    parse_loop_interval,
    parse_tick_budget,
    resolve_finding_topic,
    resolve_scheduling_mode,
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


def test_trace_window_defaults_to_the_analyzer_window() -> None:
    assert resolve_trace_window_seconds({}, 300) == 300


def test_trace_window_can_be_shortened_independently() -> None:
    assert resolve_trace_window_seconds({TRACE_WINDOW_ENV: "60"}, 300) == 60


def test_non_positive_trace_window_fails_closed() -> None:
    with pytest.raises(ValueError):
        resolve_trace_window_seconds({TRACE_WINDOW_ENV: "0"}, 300)


def _job_report(*, publish_failed: bool = False) -> AnalyzerJobReport:
    return AnalyzerJobReport(
        analyzer=AnalyzerTickReport(
            targets=1,
            findings=1,
            published=0 if publish_failed else 1,
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


async def test_local_loop_runs_serial_ticks_and_stops_after_the_bound(
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls = 0
    sleeps: list[float] = []

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
    )

    assert result == 0
    assert calls == 2
    assert sleeps == [5.0]
    assert "service=local-analyzer event=ready" in capsys.readouterr().out


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
    script = (_REPO_ROOT / "scripts/deployment/local/run-analyzer-loop.sh").read_text(
        encoding="utf-8"
    )

    assert '"label": "analyzer: run continuously (local)"' in tasks
    assert "console: prepare full stack" in tasks
    assert "fdai.delivery.analyzer_tick_cli --loop" in script
    assert ".fdai/local-runtime.env" in script
