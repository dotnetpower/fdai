"""Remote plan-only submission orchestration tests."""

from __future__ import annotations

import io
import json
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from fdai.deployment_cli.cli import main
from fdai.deployment_cli.doctor import DoctorCheck, DoctorReport
from fdai.deployment_cli.plan_submission import (
    ApplySubmissionResult,
    PlanStatusResult,
    PlanSubmissionError,
    PlanSubmissionResult,
    _effective_status,
    get_github_plan_status,
    submit_github_apply,
    submit_github_plan,
)
from fdai.deployment_cli.remote import (
    DeploymentPlanRecord,
    PlanStatus,
)


def _write_environment(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": "fdai.deployment.environment.v1",
                "environment": "dev",
                "azure": {
                    "subscription_id": "00000000-0000-0000-0000-000000000001",
                    "tenant_id": "00000000-0000-0000-0000-000000000002",
                    "region": "koreacentral",
                },
                "execution_target": "remote-runner",
                "autonomy_mode_default": "shadow",
            }
        ),
        encoding="utf-8",
    )


def _doctor(*, ready: bool) -> DoctorReport:
    return DoctorReport(
        checks=(
            DoctorCheck(
                check_id="azure.target",
                status="pass" if ready else "fail",
                summary="target checked",
            ),
        )
    )


async def test_submit_requires_ready_doctor_before_http(tmp_path: Path) -> None:
    path = tmp_path / "environment.json"
    _write_environment(path)

    def handle(_request: httpx.Request) -> httpx.Response:  # pragma: no cover - must not run
        raise AssertionError("no dispatch expected")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(PlanSubmissionError, match="doctor checks failed"):
            await submit_github_plan(
                config_path=path,
                repository="example/fdai",
                workflow_id="deploy-dev.yml",
                ref="main",
                bundle_digest="a" * 64,
                commit_sha="b" * 40,
                doctor_report=_doctor(ready=False),
                environ={"FDAI_GITHUB_TOKEN": "test-token"},
                http_client=client,
            )


async def test_submit_returns_only_opaque_workflow_metadata(tmp_path: Path) -> None:
    path = tmp_path / "environment.json"
    _write_environment(path)

    def handle(request: httpx.Request) -> httpx.Response:
        inputs = json.loads(request.read())["inputs"]
        assert inputs["deploy_console"] is True
        assert inputs["deploy_read_api"] is True
        assert inputs["deploy_dev_operations_gateway"] is True
        assert inputs["deploy_document_ingestion"] is True
        return httpx.Response(
            200,
            json={
                "workflow_run_id": 456,
                "html_url": "https://github.com/example/fdai/actions/runs/456",
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        result = await submit_github_plan(
            config_path=path,
            repository="example/fdai",
            workflow_id="deploy-dev.yml",
            ref="main",
            bundle_digest="a" * 64,
            commit_sha="b" * 40,
            doctor_report=_doctor(ready=True),
            deploy_console=True,
            deploy_read_api=True,
            deploy_dev_operations_gateway=True,
            deploy_document_ingestion=True,
            environ={"FDAI_GITHUB_TOKEN": "test-token"},
            http_client=client,
        )

    payload = result.to_json()
    assert result.submission_id == "456"
    assert set(json.loads(payload)) == {
        "schema_version",
        "submission_id",
        "plan_id",
        "workflow_url",
    }
    assert "00000000-0000-0000-0000-000000000001" not in payload


async def test_missing_token_is_sanitized(tmp_path: Path) -> None:
    path = tmp_path / "environment.json"
    _write_environment(path)
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _request: httpx.Response(200))
    ) as client:
        with pytest.raises(PlanSubmissionError, match="token is unavailable"):
            await submit_github_plan(
                config_path=path,
                repository="example/fdai",
                workflow_id="deploy-dev.yml",
                ref="main",
                bundle_digest="a" * 64,
                commit_sha="b" * 40,
                doctor_report=_doctor(ready=True),
                environ={},
                http_client=client,
            )


async def test_status_requires_environment_token_before_http() -> None:
    def handle(_request: httpx.Request) -> httpx.Response:  # pragma: no cover - must not run
        raise AssertionError("no metadata request expected")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(PlanSubmissionError, match="token is unavailable"):
            await get_github_plan_status(
                repository="example/fdai",
                plan_id="plan-789-1",
                environ={},
                http_client=client,
            )


def test_cli_plan_emits_opaque_json_after_doctor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "environment.json"
    _write_environment(config_path)
    captured: dict[str, object] = {}

    async def fake_submit(**kwargs: object) -> PlanSubmissionResult:
        captured.update(kwargs)
        return PlanSubmissionResult(
            submission_id="789",
            plan_id="plan-789-1",
            workflow_url="https://github.com/example/fdai/actions/runs/789",
        )

    monkeypatch.setattr("fdai.deployment_cli.cli.run_doctor", lambda **_: _doctor(ready=True))
    monkeypatch.setattr("fdai.deployment_cli.cli.submit_github_plan", fake_submit)
    stdout = io.StringIO()

    exit_code = main(
        [
            "deploy",
            "plan",
            "--config",
            str(config_path),
            "--repository",
            "example/fdai",
            "--bundle-digest",
            "a" * 64,
            "--commit-sha",
            "b" * 40,
            "--output",
            "json",
        ],
        stdout=stdout,
    )

    assert exit_code == 0
    assert captured["config_path"] == config_path
    assert set(json.loads(stdout.getvalue())) == {
        "schema_version",
        "submission_id",
        "plan_id",
        "workflow_url",
    }


def test_cli_status_emits_sanitized_plan_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_status(**_: object) -> PlanStatusResult:
        return PlanStatusResult(
            plan_id="plan-789-1",
            plan_digest="c" * 64,
            created_at="2026-07-17T08:00:00Z",
            expires_at="2026-07-17T09:00:00Z",
            status="ready",
            workflow_url="https://github.com/example/fdai/actions/runs/789",
        )

    monkeypatch.setattr("fdai.deployment_cli.cli.get_github_plan_status", fake_status)
    stdout = io.StringIO()

    exit_code = main(
        [
            "deploy",
            "status",
            "--repository",
            "example/fdai",
            "--plan-id",
            "plan-789-1",
            "--output",
            "json",
        ],
        stdout=stdout,
    )

    payload = json.loads(stdout.getvalue())
    assert exit_code == 0
    assert payload["plan_id"] == "plan-789-1"
    assert payload["status"] == "ready"


def test_effective_status_marks_logically_expired_ready_plan() -> None:
    now = datetime(2026, 7, 17, 10, 0, tzinfo=UTC)
    record = DeploymentPlanRecord(
        plan_id="plan-789-1",
        plan_digest="c" * 64,
        context=None,
        context_digest="d" * 64,
        created_at=now - timedelta(hours=2),
        expires_at=now - timedelta(hours=1),
        status=PlanStatus.READY,
        workflow_url="https://github.com/example/fdai/actions/runs/789",
    )

    assert _effective_status(record, now=now) is PlanStatus.EXPIRED


def test_cli_apply_emits_opaque_submission(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "environment.json"
    _write_environment(config_path)

    async def fake_apply(**_: object) -> ApplySubmissionResult:
        return ApplySubmissionResult(
            plan_id="plan-789-1",
            submission_id="790",
            workflow_url="https://github.com/example/fdai/actions/runs/790",
        )

    monkeypatch.setattr("fdai.deployment_cli.cli.run_doctor", lambda **_: _doctor(ready=True))
    monkeypatch.setattr("fdai.deployment_cli.cli.submit_github_apply", fake_apply)
    stdout = io.StringIO()

    exit_code = main(
        [
            "deploy",
            "apply",
            "--config",
            str(config_path),
            "--repository",
            "example/fdai",
            "--plan-id",
            "plan-789-1",
            "--bundle-digest",
            "a" * 64,
            "--commit-sha",
            "b" * 40,
            "--output",
            "json",
        ],
        stdout=stdout,
    )

    payload = json.loads(stdout.getvalue())
    assert exit_code == 0
    assert set(payload) == {
        "schema_version",
        "plan_id",
        "submission_id",
        "workflow_url",
    }


async def test_apply_expired_metadata_never_dispatches(tmp_path: Path) -> None:
    config_path = tmp_path / "environment.json"
    _write_environment(config_path)
    now = datetime(2026, 7, 17, 10, 0, tzinfo=UTC)
    metadata = {
        "schema_version": "fdai.deployment-plan.v1",
        "plan_id": "plan-789-1",
        "plan_digest": "c" * 64,
        "context_digest": "d" * 64,
        "commit_sha": "b" * 40,
        "request_id": "plan-request",
        "created_at": (now - timedelta(hours=2)).isoformat(),
        "expires_at": (now - timedelta(hours=1)).isoformat(),
        "status": "ready",
        "workflow_run_id": "789",
    }
    archive_buffer = io.BytesIO()
    with zipfile.ZipFile(archive_buffer, "w") as archive:
        archive.writestr("plan-metadata.json", json.dumps(metadata))
    dispatches = 0

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal dispatches
        if request.method == "POST":
            dispatches += 1
            return httpx.Response(500)
        if request.url.path.endswith("/actions/runs/789/artifacts"):
            return httpx.Response(
                200,
                json={
                    "artifacts": [
                        {
                            "id": 42,
                            "name": "deployment-plan-plan-789-1",
                            "expired": False,
                        }
                    ]
                },
            )
        if request.url.path.endswith("/actions/artifacts/42/zip"):
            return httpx.Response(200, content=archive_buffer.getvalue())
        if request.url.path.endswith("/actions/artifacts"):
            return httpx.Response(200, json={"artifacts": []})
        return httpx.Response(404)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(PlanSubmissionError, match="expired"):
            await submit_github_apply(
                config_path=config_path,
                repository="example/fdai",
                plan_id="plan-789-1",
                bundle_digest="a" * 64,
                commit_sha="b" * 40,
                doctor_report=_doctor(ready=True),
                now=now,
                environ={"FDAI_GITHUB_TOKEN": "test-token"},
                http_client=client,
            )

    assert dispatches == 0
