from __future__ import annotations

from pathlib import Path

from fdai_deployment_cli import cli
from fdai_deployment_cli.source_changed_update import deploy_changed_source


def _plan(lane: str, services: list[str]) -> dict[str, object]:
    return {
        "schema_version": "fdai.source-change-plan.v1",
        "lane": lane,
        "reason_code": "fixture",
        "plan_digest": "a" * 64,
        "base_commit": "b" * 40,
        "head_commit": "c" * 40,
        "services": services,
        "mutation_performed": False,
        "deployment_ready": False,
    }


def test_no_deploy_and_higher_lane_never_call_service_update(tmp_path: Path, monkeypatch) -> None:
    called = False

    def update(**_kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(
        "fdai_deployment_cli.source_changed_update.deploy_source_service_update",
        update,
    )
    monkeypatch.setattr(
        "fdai_deployment_cli.source_changed_update.plan_git_changes",
        lambda *_args: _plan("no-deploy", []),
    )
    result = deploy_changed_source(
        source_root=tmp_path,
        base="HEAD~1",
        application_work_dir=tmp_path / "application",
        work_dir=tmp_path / "work",
        timeout_seconds=60,
    )
    assert result["state"] == "no-deploy"
    assert result["mutation_performed"] is False
    assert called is False

    monkeypatch.setattr(
        "fdai_deployment_cli.source_changed_update.plan_git_changes",
        lambda *_args: _plan("higher-lane-required", []),
    )
    result = deploy_changed_source(
        source_root=tmp_path,
        base="HEAD~1",
        application_work_dir=tmp_path / "application",
        work_dir=tmp_path / "work",
        timeout_seconds=60,
    )
    assert result["state"] == "review"
    assert called is False


def test_multi_service_update_runs_existing_guarded_updates_serially(
    tmp_path: Path, monkeypatch
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    application = tmp_path / "application"
    application.mkdir()
    services = ["operator-service", "isolated-executor"]
    monkeypatch.setattr(
        "fdai_deployment_cli.source_changed_update.plan_git_changes",
        lambda *_args: _plan("multi-service-update", services),
    )
    calls = []

    def update(**kwargs):
        calls.append(kwargs)
        service = kwargs["service"]
        return {
            "receipt_digest": service[0] * 64,
            "image_digest": "sha256:" + service[-1] * 64,
        }

    monkeypatch.setattr(
        "fdai_deployment_cli.source_changed_update.deploy_source_service_update",
        update,
    )

    result = deploy_changed_source(
        source_root=source,
        base="HEAD~1",
        application_work_dir=application,
        work_dir=tmp_path / "work",
        timeout_seconds=60,
    )

    assert result["state"] == "applied"
    assert result["services"] == services
    assert [call["service"] for call in calls] == services
    assert calls[0]["work_dir"] == (tmp_path / "work/operator-service").absolute()
    assert calls[1]["work_dir"] == (tmp_path / "work/isolated-executor").absolute()
    assert all(call["expected_source_commit"] == "c" * 40 for call in calls)
    assert result["effect_verified"] is True


def test_cli_returns_review_exit_for_non_service_lane(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        "fdai_deployment_cli.cli.deploy_changed_source",
        lambda **_kwargs: {
            **_plan("console-update", []),
            "state": "review",
        },
    )

    result = cli.main(
        [
            "provision",
            "source-changed-update",
            "--source",
            str(tmp_path),
            "--base",
            "HEAD~1",
            "--application-work-dir",
            str(tmp_path / "application"),
            "--work-dir",
            str(tmp_path / "work"),
            "--output",
            "json",
        ]
    )

    assert result == 2
    assert '"state":"review"' in capsys.readouterr().out
