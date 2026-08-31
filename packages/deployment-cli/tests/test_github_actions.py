from __future__ import annotations

import json

import pytest

from fdai_deployment_cli.github_actions import (
    CommandResult,
    DeploymentSelection,
    deployment_context_digest,
    dispatch_apply,
    dispatch_plan,
    workflow_status,
)
from fdai_deployment_cli.cli import main
from fdai_deployment_cli.contracts import ProvisionProfile
from fdai_deployment_cli.doctor import ToolCheck
from fdai_deployment_cli.profile import write_profile
from fdai_deployment_cli.target import compute_target_binding

_COMMIT = "a" * 40
_TARGET = "e" * 64
_REGION = "koreacentral"


class RecordingRunner:
    def __init__(self, result: CommandResult | None = None) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.result = result or CommandResult(0, "")

    def __call__(self, arguments: tuple[str, ...]) -> CommandResult:
        self.calls.append(arguments)
        if arguments[:1] == ("api",):
            return CommandResult(
                0,
                json.dumps(
                    {
                        "can_admins_bypass": False,
                        "protection_rules": [
                            {
                                "type": "required_reviewers",
                                "prevent_self_review": True,
                                "reviewers": [
                                    {"reviewer": {"id": 1}},
                                    {"reviewer": {"id": 2}},
                                ],
                            }
                        ],
                    }
                ),
            )
        return self.result


def _fields(call: tuple[str, ...]) -> dict[str, str]:
    return {
        value.split("=", 1)[0]: value.split("=", 1)[1]
        for index, value in enumerate(call)
        if index > 0 and call[index - 1] == "--field"
    }


def test_plan_and_apply_share_one_context_and_exact_feature_inputs() -> None:
    runner = RecordingRunner()
    selection = DeploymentSelection(deploy_document_ingestion=True)

    plan = dispatch_plan(
        repository="example/fdai",
        environment="dev",
        commit_sha=_COMMIT,
        target_binding=_TARGET,
        region=_REGION,
        run_id="run.example",
        selection=selection,
        run=runner,
    )
    apply = dispatch_apply(
        repository="example/fdai",
        environment="dev",
        commit_sha=_COMMIT,
        target_binding=_TARGET,
        region=_REGION,
        approval_quorum=1,
        run_id="run.example",
        plan_id="plan-123-1",
        plan_digest="c" * 64,
        resume_verification=False,
        selection=selection,
        run=runner,
    )

    assert plan.context_digest == apply.context_digest
    workflow_calls = [call for call in runner.calls if call[:2] == ("workflow", "run")]
    plan_fields, apply_fields = map(_fields, workflow_calls)
    assert plan_fields["apply"] == "false"
    assert apply_fields["apply"] == "true"
    assert apply_fields["plan_id"] == "plan-123-1"
    assert apply_fields["plan_digest"] == "c" * 64
    assert plan_fields["deploy_document_ingestion"] == "true"
    assert plan_fields["context_digest"] == apply_fields["context_digest"]
    assert "expected_target_binding" not in plan_fields
    assert "expected_target_binding" not in apply_fields


def test_resume_dispatch_uses_exact_apply_with_verification_only_flag() -> None:
    runner = RecordingRunner()

    receipt = dispatch_apply(
        repository="example/fdai",
        environment="staging",
        commit_sha=_COMMIT,
        target_binding=_TARGET,
        region=_REGION,
        approval_quorum=1,
        run_id="run.resume",
        plan_id="plan-99-2",
        plan_digest="d" * 64,
        resume_verification=True,
        selection=DeploymentSelection(),
        run=runner,
    )

    assert receipt.mode == "resume-verification"
    workflow_call = next(call for call in runner.calls if call[:2] == ("workflow", "run"))
    fields = _fields(workflow_call)
    assert fields["apply"] == "true"
    assert fields["resume_verification"] == "true"


def test_apply_and_resume_use_distinct_request_ids() -> None:
    runner = RecordingRunner()
    common = {
        "repository": "example/fdai",
        "environment": "dev",
        "commit_sha": _COMMIT,
        "target_binding": _TARGET,
        "region": _REGION,
        "approval_quorum": 1,
        "run_id": "run.same",
        "plan_id": "plan-99-2",
        "plan_digest": "d" * 64,
        "selection": DeploymentSelection(),
        "run": runner,
    }

    apply = dispatch_apply(**common, resume_verification=False)
    resume = dispatch_apply(**common, resume_verification=True)

    assert apply.request_id != resume.request_id


def test_replan_attempts_use_distinct_request_ids() -> None:
    common = {
        "repository": "example/fdai",
        "environment": "dev",
        "commit_sha": _COMMIT,
        "target_binding": _TARGET,
        "region": _REGION,
        "run_id": "run.replan",
        "selection": DeploymentSelection(),
    }

    first = dispatch_plan(**common, attempt=1, run=RecordingRunner())
    second = dispatch_plan(**common, attempt=2, run=RecordingRunner())

    assert first.request_id != second.request_id


def test_apply_rejects_unsupported_quorum_or_self_reviewable_environment() -> None:
    class EnvironmentRunner(RecordingRunner):
        def __init__(
            self,
            *,
            reviewer_count: int,
            prevent_self_review: bool,
            admin_bypass: bool = False,
        ) -> None:
            super().__init__()
            self.reviewer_count = reviewer_count
            self.prevent_self_review = prevent_self_review
            self.admin_bypass = admin_bypass

        def __call__(self, arguments: tuple[str, ...]) -> CommandResult:
            self.calls.append(arguments)
            if arguments[:1] == ("api",):
                return CommandResult(
                    0,
                    json.dumps(
                        {
                            "can_admins_bypass": self.admin_bypass,
                            "protection_rules": [
                                {
                                    "type": "required_reviewers",
                                    "prevent_self_review": self.prevent_self_review,
                                    "reviewers": [
                                        {"reviewer": {"id": index + 1}}
                                        for index in range(self.reviewer_count)
                                    ],
                                }
                            ],
                        }
                    ),
                )
            return CommandResult(0, "")

    common = {
        "repository": "example/fdai",
        "environment": "staging",
        "commit_sha": _COMMIT,
        "target_binding": _TARGET,
        "region": _REGION,
        "approval_quorum": 1,
        "run_id": "run.quorum",
        "plan_id": "plan-99-2",
        "plan_digest": "d" * 64,
        "resume_verification": False,
        "selection": DeploymentSelection(),
    }
    with pytest.raises(ValueError, match="exactly one"):
        dispatch_apply(
            **{**common, "approval_quorum": 2},
            run=EnvironmentRunner(reviewer_count=2, prevent_self_review=True),
        )
    with pytest.raises(ValueError, match="required_reviewers_missing"):
        dispatch_apply(**common, run=EnvironmentRunner(reviewer_count=0, prevent_self_review=True))
    with pytest.raises(ValueError, match="self_review"):
        dispatch_apply(**common, run=EnvironmentRunner(reviewer_count=2, prevent_self_review=False))
    with pytest.raises(ValueError, match="admin_bypass"):
        dispatch_apply(
            **common,
            run=EnvironmentRunner(
                reviewer_count=1,
                prevent_self_review=True,
                admin_bypass=True,
            ),
        )


def test_status_requires_one_exact_run_title() -> None:
    context_digest = deployment_context_digest(
        environment="dev",
        commit_sha=_COMMIT,
        selection=DeploymentSelection(),
    )
    request = dispatch_plan(
        repository="example/fdai",
        environment="dev",
        commit_sha=_COMMIT,
        target_binding=_TARGET,
        region=_REGION,
        run_id="run.status",
        selection=DeploymentSelection(),
        run=RecordingRunner(),
    ).request_id

    class ArtifactRunner(RecordingRunner):
        def __call__(self, arguments: tuple[str, ...]) -> CommandResult:
            self.calls.append(arguments)
            if arguments[:2] == ("run", "download"):
                directory = arguments[arguments.index("--dir") + 1]
                with open(f"{directory}/plan-metadata.json", "w", encoding="utf-8") as stream:
                    json.dump(
                        {
                            "schema_version": "fdai.deployment-plan.v1",
                            "request_id": request,
                            "commit_sha": _COMMIT,
                            "status": "ready",
                            "plan_id": "plan-123-1",
                            "plan_digest": "c" * 64,
                            "context_digest": context_digest,
                            "expires_at": "2026-08-31T12:00:00Z",
                        },
                        stream,
                    )
                return CommandResult(0, "")
            return CommandResult(
                0,
                json.dumps(
                    [
                        {
                            "databaseId": 123,
                            "displayTitle": f"deploy-{request}",
                            "status": "completed",
                            "conclusion": "success",
                            "url": "https://example.com/run/123",
                            "headSha": "f" * 40,
                        }
                    ]
                ),
            )

    runner = ArtifactRunner()

    status = workflow_status(
        repository="example/fdai",
        request_id_value=request,
        expected_commit=_COMMIT,
        expected_context_digest=context_digest,
        target_binding=_TARGET,
        expected_region=_REGION,
        run=runner,
    )

    assert status["workflow_run_id"] == 123
    assert status["plan"]["plan_id"] == "plan-123-1"
    assert status["dispatch_ref_sha"] == "f" * 40
    assert status["requested_commit"] == _COMMIT
    assert status["mutation_performed"] is False


def test_status_rejects_absent_or_ambiguous_runs() -> None:
    context_digest = deployment_context_digest(
        environment="dev",
        commit_sha=_COMMIT,
        selection=DeploymentSelection(),
    )
    request = dispatch_plan(
        repository="example/fdai",
        environment="dev",
        commit_sha=_COMMIT,
        target_binding=_TARGET,
        region=_REGION,
        run_id="run.status",
        selection=DeploymentSelection(),
        run=RecordingRunner(),
    ).request_id
    with pytest.raises(ValueError, match="not_found"):
        workflow_status(
            repository="example/fdai",
            request_id_value=request,
            expected_commit=_COMMIT,
            expected_context_digest=context_digest,
            target_binding=_TARGET,
            expected_region=_REGION,
            run=RecordingRunner(CommandResult(0, "[]")),
        )
    duplicate = {
        "databaseId": 1,
        "displayTitle": f"deploy-{request}",
        "status": "queued",
        "conclusion": None,
        "url": "https://example.com/run/1",
        "headSha": _COMMIT,
    }
    with pytest.raises(ValueError, match="ambiguous"):
        workflow_status(
            repository="example/fdai",
            request_id_value=request,
            expected_commit=_COMMIT,
            expected_context_digest=context_digest,
            target_binding=_TARGET,
            expected_region=_REGION,
            run=RecordingRunner(CommandResult(0, json.dumps([duplicate, duplicate]))),
        )


def test_context_changes_when_any_feature_selection_changes() -> None:
    baseline = deployment_context_digest(
        environment="dev",
        commit_sha=_COMMIT,
        selection=DeploymentSelection(),
    )
    changed = deployment_context_digest(
        environment="dev",
        commit_sha=_COMMIT,
        selection=DeploymentSelection(
            deploy_console=False,
            deploy_operator_api=False,
            deploy_monitoring=True,
        ),
    )

    assert baseline != changed


def test_cli_dispatches_plan_only_after_target_and_tool_checks(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    target = compute_target_binding(
        tenant_id="00000000-0000-0000-0000-000000000000",
        subscription_id="00000000-0000-0000-0000-000000000001",
    )
    profile = ProvisionProfile(
        environment="dev",
        region="koreacentral",
        target_binding=target,
        connectivity="online",
        host="managed-vm",
        transport="github-actions",
        access_method="github_actions",
        shadow_only=True,
        approval_quorum=1,
        monthly_cost_ceiling=100,
    )
    profile_path = tmp_path / "private" / "profile.json"
    profile_path.parent.mkdir(mode=0o700)
    write_profile(profile_path, profile)
    monkeypatch.setattr(
        "fdai_deployment_cli.cli.inspect_tools",
        lambda names: tuple(ToolCheck(name=name, available=True, version="test") for name in names),
    )
    monkeypatch.setattr("fdai_deployment_cli.cli.azure_cli_authenticated", lambda: True)
    monkeypatch.setattr("fdai_deployment_cli.cli.azure_active_target_binding", lambda: target)
    dispatched: list[dict[str, object]] = []

    def fake_dispatch(**kwargs):
        dispatched.append(kwargs)
        return dispatch_plan(**kwargs, run=RecordingRunner())

    monkeypatch.setattr("fdai_deployment_cli.cli.dispatch_plan", fake_dispatch)

    result = main(
        [
            "deploy",
            "plan",
            "--profile",
            str(profile_path),
            "--repository",
            "example/fdai",
            "--commit-sha",
            _COMMIT,
            "--run-id",
            "run.example",
            "--deploy-document-ingestion",
            "--output",
            "json",
        ]
    )

    assert result == 0
    assert dispatched[0]["selection"].deploy_document_ingestion is True
    output = json.loads(capsys.readouterr().out)
    assert output["mode"] == "plan"
    assert output["mutation_performed"] is True


def test_guided_live_flow_pauses_for_plan_then_requires_explicit_apply(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    target = compute_target_binding(
        tenant_id="00000000-0000-0000-0000-000000000000",
        subscription_id="00000000-0000-0000-0000-000000000001",
    )
    profile = ProvisionProfile(
        environment="dev",
        region="koreacentral",
        target_binding=target,
        connectivity="online",
        host="managed-vm",
        transport="github-actions",
        access_method="github_actions",
        shadow_only=True,
        approval_quorum=1,
        monthly_cost_ceiling=100,
    )
    profile_path = tmp_path / "private" / "profile.json"
    profile_path.parent.mkdir(mode=0o700)
    write_profile(profile_path, profile)
    monkeypatch.setattr(
        "fdai_deployment_cli.cli.inspect_tools",
        lambda names: tuple(ToolCheck(name=name, available=True, version="test") for name in names),
    )
    monkeypatch.setattr("fdai_deployment_cli.cli.azure_cli_authenticated", lambda: True)
    monkeypatch.setattr("fdai_deployment_cli.cli.azure_active_target_binding", lambda: target)
    plan_calls: list[dict[str, object]] = []
    apply_calls: list[dict[str, object]] = []

    def fake_plan(**kwargs):
        plan_calls.append(kwargs)
        return dispatch_plan(**kwargs, run=RecordingRunner())

    def fake_apply(**kwargs):
        apply_calls.append(kwargs)
        return dispatch_apply(**kwargs, run=RecordingRunner())

    monkeypatch.setattr("fdai_deployment_cli.cli.dispatch_plan", fake_plan)
    monkeypatch.setattr("fdai_deployment_cli.cli.dispatch_apply", fake_apply)
    common = [
        "onboard",
        "guided",
        "--profile",
        str(profile_path),
        "--source-commit",
        _COMMIT,
        "--run-id",
        "run.guided",
        "--journal",
        str(tmp_path / "unused.jsonl"),
        "--repository",
        "example/fdai",
        "--output",
        "json",
    ]

    assert main(common) == 0
    planned = json.loads(capsys.readouterr().out)
    assert planned["state"] == "waiting"
    assert planned["next_action"] == "review-protected-plan"
    assert len(plan_calls) == 1

    assert (
        main(
            [
                *common,
                "--plan-id",
                "plan-123-1",
                "--plan-digest",
                "c" * 64,
            ]
        )
        == 3
    )
    assert "--approve-application" in capsys.readouterr().err
    assert (
        main(
            [
                *common,
                "--plan-id",
                "plan-123-1",
                "--plan-digest",
                "c" * 64,
                "--approve-application",
            ]
        )
        == 0
    )
    applying = json.loads(capsys.readouterr().out)
    assert applying["state"] == "applying"
    assert len(apply_calls) == 1
