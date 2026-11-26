"""Offline proof of typed canaries, independent evidence, and no global activation."""

from __future__ import annotations

import importlib.util
import io
import json
import subprocess
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from email.message import Message
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Self
from unittest.mock import MagicMock, Mock
from urllib.error import HTTPError

import pytest
from scripts.quality.ci import ci_pool_canary as canary

BASE = datetime(2026, 1, 1, tzinfo=UTC)
SHA = "a" * 40
SLO = {"warm_queue_p95_seconds": 15, "burst_queue_p99_seconds": 90, "maximum_queue_seconds": 120}


@pytest.fixture
def environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in canary.FORBIDDEN_ENV:
        monkeypatch.delenv(key, raising=False)
    values = {
        "GITHUB_EVENT_NAME": "workflow_dispatch",
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_SHA": SHA,
        "GITHUB_RUN_ID": "303",
        "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_REPOSITORY": "example/project",
        "GITHUB_REPOSITORY_ID": "101",
        "CANARY_TARGET_SHA": SHA,
        "CANARY_ENABLED": "true",
        "CANARY_POOL": "general",
        "CANARY_COUNT": "1",
        "CANARY_HOLD_SECONDS": "120",
        "CANARY_KIND": "warm",
        "RUNNER_ENVIRONMENT": "self-hosted",
        "RUNNER_OS": "Linux",
        "RUNNER_ARCH": "X64",
        "RUNNER_NAME": "example-runner",
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("FDAI_CI_POOLS_ENABLED", raising=False)


def evidence(
    pool: str = "general",
    count: int = 8,
) -> tuple[canary.Canary, list[dict[str, Any]], list[dict[str, Any]]]:
    scope = canary.Canary(pool, count, 120, "warm", 303, 1, SHA)
    jobs = [
        {
            "id": 1,
            "name": canary.PLAN_NAME,
            "status": "completed",
            "conclusion": "success",
            "completed_at": BASE.isoformat(),
            "run_id": 303,
            "head_sha": SHA,
        },
        {
            "id": 2,
            "name": "collect pool canary",
            "status": "in_progress",
            "conclusion": None,
            "run_id": 303,
            "head_sha": SHA,
        },
    ]
    observations = []
    for slot in range(1, count + 1):
        started = BASE + timedelta(seconds=3)
        finished = started + timedelta(seconds=120)
        jobs.append(
            {
                "id": 100 + slot,
                "name": f"pool canary / {pool} / {slot}",
                "status": "completed",
                "conclusion": "success",
                "runner_id": 500 + slot,
                "runner_name": f"example-runner-{slot}",
                "run_id": 303,
                "head_sha": SHA,
                "labels": ["self-hosted", "Linux", "X64", f"fdai-ci-{pool}"],
                "started_at": (BASE + timedelta(seconds=2)).isoformat(),
                "completed_at": finished.isoformat(),
                "steps": [
                    {"name": canary.CHECK_NAME, "status": "completed", "conclusion": "success"},
                    {
                        "name": canary.HOLD_NAME,
                        "status": "completed",
                        "conclusion": "success",
                        "started_at": started.isoformat(),
                        "completed_at": finished.isoformat(),
                    },
                ],
            }
        )
        observations.append(
            {
                **scope.record(slot),
                "credential_env_absent": True,
                "docker_verified": pool == "docker",
                "credential_env_keys_checked": list(canary.FORBIDDEN_ENV),
                "elapsed_seconds": 120.0,
                "hold_started_at": started.isoformat(),
                "hold_completed_at": finished.isoformat(),
            }
        )
    return scope, jobs, observations


@pytest.mark.usefixtures("environment")
@pytest.mark.parametrize(("pool", "count"), [("control", 4), ("general", 64), ("docker", 16)])
def test_canary_can_plan_before_any_global_flag(
    monkeypatch: pytest.MonkeyPatch, pool: str, count: int
) -> None:
    monkeypatch.setenv("CANARY_POOL", pool)
    monkeypatch.setenv("CANARY_COUNT", str(count))
    assert canary.Canary.from_env().count == count
    monkeypatch.setenv("CANARY_COUNT", str(count + 1))
    with pytest.raises(canary.CanaryError):
        canary.Canary.from_env()


@pytest.mark.usefixtures("environment")
def test_planner_emits_exact_matrix_without_global_activation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.setenv("CANARY_COUNT", "8")
    monkeypatch.setattr("sys.argv", ["ci_pool_canary.py", "plan"])
    assert canary.main() == 0
    values = dict(line.split("=", 1) for line in output.read_text().splitlines())
    assert values["pool"] == "general" and values["count"] == "8"
    assert json.loads(values["matrix_general"]) == {"slot": list(range(1, 9))}
    assert json.loads(values["matrix_control"]) == {"slot": [0]}
    assert json.loads(values["matrix_docker"]) == {"slot": [0]}
    assert "FDAI_CI_POOLS_ENABLED" not in values


@pytest.mark.usefixtures("environment")
@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("CANARY_COUNT", "0"),
        ("CANARY_COUNT", "1.0"),
        ("CANARY_COUNT", "-1"),
        ("CANARY_COUNT", "true"),
        ("CANARY_HOLD_SECONDS", "119"),
        ("CANARY_HOLD_SECONDS", "181"),
        ("CANARY_HOLD_SECONDS", "120.0"),
        ("CANARY_POOL", "other"),
        ("CANARY_KIND", "unknown"),
        ("CANARY_ENABLED", "false"),
        ("GITHUB_EVENT_NAME", "pull_request"),
        ("GITHUB_REF", "refs/heads/other"),
        ("CANARY_TARGET_SHA", "b" * 40),
    ],
)
def test_invalid_or_unapproved_dispatch_denies(
    monkeypatch: pytest.MonkeyPatch, key: str, value: str
) -> None:
    monkeypatch.setenv(key, value)
    with pytest.raises(canary.CanaryError):
        canary.Canary.from_env()


@pytest.mark.usefixtures("environment")
@pytest.mark.parametrize("key", canary.FORBIDDEN_ENV)
def test_credential_presence_denies_without_logging_values(
    monkeypatch: pytest.MonkeyPatch, key: str
) -> None:
    monkeypatch.setenv(key, "never-log-this-value")
    with pytest.raises(canary.CanaryError) as failure:
        canary.assert_isolation()
    assert "never-log-this-value" not in str(failure.value)
    monkeypatch.setenv(key, "")
    with pytest.raises(canary.CanaryError):
        canary.assert_isolation()


@pytest.mark.usefixtures("environment")
def test_real_hold_uses_monotonic_time_and_redacted_observation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(canary, "ARTIFACTS", tmp_path)
    scope = canary.Canary.from_env()
    canary.check_worker(scope, 1)
    clock_values = iter([BASE, BASE + timedelta(seconds=120)])

    class Clock(datetime):
        @classmethod
        def now(cls, tz: Any = None) -> Self:
            return cls.fromtimestamp(next(clock_values).timestamp(), tz=UTC)

    monkeypatch.setattr(canary, "datetime", Clock)
    sleep = Mock()
    monkeypatch.setattr(
        canary,
        "time",
        SimpleNamespace(
            monotonic=Mock(side_effect=[10.0, 130.0]),
            sleep=sleep,
        ),
    )
    canary.hold_worker(scope, 1)
    sleep.assert_called_once_with(120)
    observation = canary.read_json(tmp_path / "observation-general-1.json")
    assert observation["elapsed_seconds"] == 120
    assert observation["credential_env_absent"] is True
    assert "example-runner" not in json.dumps(observation)
    assert "scaled_to_reserve" not in observation


def test_docker_smoke_uses_local_scratch_image_and_no_registry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scope, _, _ = evidence("docker", 1)
    monkeypatch.setattr(canary, "ARTIFACTS", tmp_path)
    commands: list[list[str]] = []
    monkeypatch.setattr(canary, "command", lambda args, **kwargs: commands.append(args))
    canary.docker_smoke(scope, 1)
    assert any("info" in args for args in commands)
    assert any(args[0] == "/usr/bin/cc" and "-static" in args for args in commands)
    assert any(
        "run" in args and "--pull=never" in args and "--network=none" in args for args in commands
    )
    assert all("push" not in args and "login" not in args for args in commands)
    assert commands[-1][-3:] == ["image", "rm", "fdai-ci-canary:303-1-1"]
    assert (tmp_path / "smoke-303-1-1/Dockerfile").read_text().startswith("FROM scratch")


@pytest.mark.parametrize("count", [1, 4, 8, 16, 32, 64])
def test_real_acceptance_counts_have_exact_once_success_and_concurrency(count: int) -> None:
    scope, jobs, observations = evidence(count=count)
    jobs.append(
        {
            "id": 999999,
            "name": "pool canary / control / ${{ matrix.slot }}",
            "status": "completed",
            "conclusion": "skipped",
        }
    )
    receipt = {**canary.build_receipt(scope, jobs, observations, SLO), "github_run_verified": True}
    assert receipt["passed"] is True
    assert receipt["peak_concurrency"] == count
    assert receipt["all_jobs_overlap_seconds"] == 120
    assert receipt["queue_p95_seconds"] == receipt["queue_p99_seconds"] == 2
    assert canary.validate_receipt(receipt, SLO)["activation_ready"] is False
    assert "scaled_to_reserve" not in receipt
    assert "busy_jobs_interrupted" not in receipt


@pytest.mark.parametrize(
    "violation",
    [
        "missing",
        "duplicate-observation",
        "wrong-sha",
        "old-attempt",
        "short-hold",
        "credential",
        "wrong-labels",
        "duplicate-runner",
        "duplicate-job",
        "failed",
        "missing-proof-step",
        "publisher-ran",
        "unselected-pool-ran",
        "wrong-clock",
    ],
)
def test_independent_canary_evidence_rejects_bad_observations(violation: str) -> None:
    scope, jobs, observations = evidence(count=2)
    if violation == "missing":
        observations.pop()
    elif violation == "duplicate-observation":
        observations[1] = deepcopy(observations[0])
    elif violation == "wrong-sha":
        observations[0]["sha"] = "b" * 40
    elif violation == "old-attempt":
        observations[0]["attempt"] = 2
    elif violation == "short-hold":
        observations[0]["elapsed_seconds"] = 119
    elif violation == "credential":
        observations[0]["credential_env_absent"] = False
    elif violation == "wrong-labels":
        jobs[2]["labels"] = ["self-hosted", "fdai-deploy"]
    elif violation == "duplicate-runner":
        jobs[3]["runner_id"] = jobs[2]["runner_id"]
    elif violation == "duplicate-job":
        jobs[3]["id"] = jobs[2]["id"]
    elif violation == "failed":
        jobs[2]["conclusion"] = "failure"
    elif violation == "missing-proof-step":
        jobs[2]["steps"] = []
    elif violation == "publisher-ran":
        jobs.append({"name": "build-scan-attest", "conclusion": "success"})
    elif violation == "unselected-pool-ran":
        jobs.append({"name": "pool canary / docker / 1", "conclusion": "success"})
    else:
        observations[0]["hold_started_at"] = BASE.isoformat()
    with pytest.raises(canary.CanaryError):
        canary.build_receipt(scope, jobs, observations, SLO)


def test_successful_but_serial_jobs_do_not_prove_concurrency() -> None:
    scope, jobs, observations = evidence(count=2)
    late_start = BASE + timedelta(seconds=125)
    late_end = late_start + timedelta(seconds=120)
    observations[1].update(
        hold_started_at=late_start.isoformat(), hold_completed_at=late_end.isoformat()
    )
    jobs[3]["steps"][1].update(started_at=late_start.isoformat(), completed_at=late_end.isoformat())
    jobs[3]["completed_at"] = late_end.isoformat()
    receipt = canary.build_receipt(scope, jobs, observations, SLO)
    assert receipt["peak_concurrency"] == 1
    assert receipt["passed"] is False


def test_queue_slo_is_not_a_population_claim_and_tampering_denies() -> None:
    scope, jobs, observations = evidence(count=1)
    jobs[2]["started_at"] = (BASE + timedelta(seconds=20)).isoformat()
    start, end = BASE + timedelta(seconds=21), BASE + timedelta(seconds=141)
    jobs[2]["completed_at"] = end.isoformat()
    jobs[2]["steps"][1].update(started_at=start.isoformat(), completed_at=end.isoformat())
    observations[0].update(hold_started_at=start.isoformat(), hold_completed_at=end.isoformat())
    receipt = {**canary.build_receipt(scope, jobs, observations, SLO), "github_run_verified": True}
    assert receipt["passed"] is False
    assert "not a population guarantee" in receipt["statistical_limit"]
    receipt["passed"] = True
    with pytest.raises(canary.CanaryError, match="metrics were modified"):
        canary.validate_receipt(receipt, SLO)


@pytest.mark.usefixtures("environment")
@pytest.mark.parametrize("status", [403, 429, 503])
def test_collector_provider_failure_is_redacted_and_never_retried(
    monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    monkeypatch.setenv("CANARY_GITHUB_TOKEN", "example-token")
    opener = Mock()
    opener.open.side_effect = HTTPError(
        "https://api.github.com", status, "private-provider-body", Message(), io.BytesIO()
    )
    monkeypatch.setattr(
        "scripts.quality.ci.ci_pool_canary.urllib.request.build_opener", Mock(return_value=opener)
    )
    with pytest.raises(canary.CanaryError) as failure:
        canary.collect(canary.Canary.from_env())
    assert opener.open.call_count == 1
    assert "private-provider-body" not in str(failure.value)
    assert "example-token" not in str(failure.value)


@pytest.mark.usefixtures("environment")
def test_collector_reads_exact_attempt_once_then_checks_observations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CANARY_GITHUB_TOKEN", "example-token")
    scope, jobs, observations = evidence(count=1)
    Path("canary-observations").mkdir()
    canary.write_json(Path("canary-observations/observation-general-1.json"), observations[0])
    canary.write_json(Path("config/ci-runner-pools.json"), {"slo": SLO})
    run = {
        "id": 303,
        "run_attempt": 1,
        "event": "workflow_dispatch",
        "head_branch": "main",
        "head_sha": SHA,
        "path": canary.WORKFLOW,
        "repository": {"id": 101, "full_name": "example/project"},
    }
    opener = Mock()
    responses = []
    for data in (run, {"total_count": len(jobs), "jobs": jobs}):
        response = MagicMock(status=200)
        response.__enter__.return_value = response
        response.read.return_value = json.dumps(data).encode()
        responses.append(response)
    opener.open.side_effect = responses
    monkeypatch.setattr(
        "scripts.quality.ci.ci_pool_canary.urllib.request.build_opener", Mock(return_value=opener)
    )
    receipt = canary.collect(scope)
    assert receipt["passed"] is True
    assert opener.open.call_count == 2
    urls = [call.args[0].full_url for call in opener.open.call_args_list]
    assert all("/303/attempts/1" in url for url in urls)
    assert urls[-1].endswith("/jobs?per_page=100&page=1")
    assert "example-token" not in json.dumps(receipt)


@pytest.mark.usefixtures("environment")
@pytest.mark.parametrize("violation", ["duplicate", "changed-total", "incomplete", "wrong-sha"])
def test_collector_never_uses_partial_or_mismatched_api_evidence(
    monkeypatch: pytest.MonkeyPatch, violation: str
) -> None:
    monkeypatch.setenv("CANARY_GITHUB_TOKEN", "example-token")
    run = {
        "id": 303,
        "run_attempt": 1,
        "event": "workflow_dispatch",
        "head_branch": "main",
        "head_sha": SHA,
        "path": canary.WORKFLOW,
        "repository": {"id": 101, "full_name": "example/project"},
    }
    rows = [{"id": n, "run_id": 303, "head_sha": SHA} for n in range(1, 101)]
    last = {"id": 101, "run_id": 303, "head_sha": SHA}
    if violation == "duplicate":
        last["id"] = 1
    elif violation == "incomplete":
        rows = rows[:1]
    elif violation == "wrong-sha":
        run["head_sha"] = "b" * 40
    bodies = [
        run,
        {"total_count": 101, "jobs": rows},
        {"total_count": 102 if violation == "changed-total" else 101, "jobs": [last]},
    ]
    responses = []
    for body in bodies:
        response = MagicMock(status=200)
        response.__enter__.return_value = response
        response.read.return_value = json.dumps(body).encode()
        responses.append(response)
    opener = Mock()
    opener.open.side_effect = responses
    monkeypatch.setattr(
        "scripts.quality.ci.ci_pool_canary.urllib.request.build_opener", Mock(return_value=opener)
    )
    with pytest.raises(canary.CanaryError):
        canary.collect(canary.Canary.from_env())
    assert opener.open.call_count == (
        1 if violation == "wrong-sha" else 2 if violation == "incomplete" else 3
    )


def test_no_provider_body_or_subprocess_output_is_printed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "scripts.quality.ci.ci_pool_canary.subprocess.run",
        Mock(return_value=subprocess.CompletedProcess([], 1, b"private-stdout", b"private-stderr")),
    )
    with pytest.raises(canary.CanaryError, match="Docker smoke failed") as failure:
        canary.command(["/usr/bin/docker", "info"])
    assert "private" not in str(failure.value)


def test_pre_cutover_queue_gate_does_not_require_flag_or_invent_drain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = Path(__file__).resolve().parents[3]
    script = root / "scripts/quality/ci/runner-pool-readiness.py"
    spec = importlib.util.spec_from_file_location("canary_queue_gate", script)
    assert spec is not None and spec.loader is not None
    gate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gate)
    scope, jobs, observations = evidence(count=1)
    receipt = {**canary.build_receipt(scope, jobs, observations, SLO), "github_run_verified": True}
    path = tmp_path / "receipt.json"
    canary.write_json(path, receipt)
    monkeypatch.delenv("FDAI_CI_POOLS_ENABLED", raising=False)
    monkeypatch.chdir(root)
    assert gate.main(["--canary-receipt", str(path)]) == 0
    checked = json.loads(capsys.readouterr().out)
    assert checked["passed"] is True and checked["activation_ready"] is False
    assert checked["remaining_evidence"]
    assert gate.main(["--burst-receipt", str(path)]) == 2
