"""Bounded GitHub Actions transport for protected FDAI deployment workflows."""

from __future__ import annotations

from datetime import UTC, datetime

from fdai_deployment_cli.github_transport import _artifact_runner, run_github_cli
from fdai_deployment_cli.github_workflow_values import (
    _COMMIT,
    _DIGEST,
    _REQUEST_ID,
    CommandResult,
    CommandRunner,
    DeploymentSelection,
    WorkflowDispatch,
    _request_binding_from_id,
    _validate_repository,
    deployment_context_digest,
    enforce_plan_not_expired,
    parse_plan_expiry,
    request_binding_prefix,
    request_id,
)
from fdai_deployment_cli.github_dispatch import dispatch_apply, dispatch_plan
from fdai_deployment_cli.github_plan_artifact import _download_plan_metadata
from fdai_deployment_cli.github_apply_artifact import _download_apply_receipt
from fdai_deployment_cli.github_artifact_io import (
    _json_array,
)


# Artifact downloads are larger than metadata queries; use a longer timeout.


def workflow_status(
    *,
    repository: str,
    request_id_value: str,
    expected_commit: str,
    expected_context_digest: str,
    target_binding: str,
    expected_region: str,
    resume_verification: bool = False,
    expected_plan_id: str | None = None,
    expected_plan_digest: str | None = None,
    run: CommandRunner | None = None,
) -> dict[str, object]:
    """Read one uniquely matched workflow run without polling."""

    _validate_repository(repository)
    if _REQUEST_ID.fullmatch(request_id_value) is None:
        raise ValueError("request_id is invalid")
    if _COMMIT.fullmatch(expected_commit) is None:
        raise ValueError("expected_commit MUST be a lowercase git SHA")
    if _DIGEST.fullmatch(expected_context_digest) is None:
        raise ValueError("expected_context_digest MUST be a lowercase SHA-256")
    request_mode = (
        "plan"
        if request_id_value.startswith("plan-")
        else ("resume" if resume_verification else "apply")
    )
    expected_binding = request_binding_prefix(
        target_binding=target_binding,
        context_digest=expected_context_digest,
        mode=request_mode,
        region=expected_region,
    )
    if _request_binding_from_id(request_id_value) != expected_binding:
        raise ValueError("request_id does not match the approved deployment context")
    runner = run or run_github_cli
    result = runner(
        (
            "run",
            "list",
            "--repo",
            repository,
            "--workflow",
            "deploy-dev.yml",
            "--event",
            "workflow_dispatch",
            "--limit",
            "50",
            "--json",
            "databaseId,displayTitle,status,conclusion,url,headSha",
        )
    )
    if result.returncode != 0:
        raise ValueError("github_workflow_status_unavailable")
    payload = _json_array(result.stdout, "workflow runs")
    expected_title = f"deploy-{request_id_value}"
    matches = [item for item in payload if item.get("displayTitle") == expected_title]
    if not matches:
        raise ValueError("github_workflow_run_not_found")
    if len(matches) != 1:
        raise ValueError("github_workflow_run_ambiguous")
    selected = matches[0]
    database_id = selected.get("databaseId")
    status = selected.get("status")
    conclusion = selected.get("conclusion")
    head_sha = selected.get("headSha")
    if (
        not isinstance(database_id, int)
        or not isinstance(status, str)
        or (conclusion is not None and not isinstance(conclusion, str))
        or not isinstance(head_sha, str)
        or _COMMIT.fullmatch(head_sha) is None
    ):
        raise ValueError("github_workflow_run_invalid")
    projected: dict[str, object] = {
        "schema_version": "fdai.workflow-status.v1",
        "request_id": request_id_value,
        "workflow_run_id": database_id,
        "status": status,
        "conclusion": conclusion,
        "dispatch_ref_sha": head_sha,
        "requested_commit": expected_commit,
        "url": selected.get("url") if isinstance(selected.get("url"), str) else None,
        "mutation_performed": False,
    }
    if request_id_value.startswith("plan-") and status == "completed" and conclusion == "success":
        plan_meta = _download_plan_metadata(
            repository=repository,
            workflow_run_id=database_id,
            request_id_value=request_id_value,
            expected_commit=expected_commit,
            expected_context_digest=expected_context_digest,
            run=_artifact_runner(runner),
        )
        # Expose expired as read-only status without blocking the status query.
        expires_at = plan_meta.get("expires_at")
        if isinstance(expires_at, str):
            try:
                deadline = parse_plan_expiry(expires_at)
                plan_meta["expired"] = datetime.now(UTC) >= deadline
            except ValueError:
                plan_meta["expired"] = True  # Fail-closed on unparseable expiry.
        projected["plan"] = plan_meta
    elif (
        status == "completed"
        and conclusion == "success"
        and (expected_plan_id is not None or expected_plan_digest is not None)
    ):
        if expected_plan_id is None or expected_plan_digest is None:
            raise ValueError("apply status requires plan id and digest together")
        projected["apply_receipt"] = _download_apply_receipt(
            repository=repository,
            workflow_run_id=database_id,
            request_id_value=request_id_value,
            expected_commit=expected_commit,
            expected_context_digest=expected_context_digest,
            expected_plan_id=expected_plan_id,
            expected_plan_digest=expected_plan_digest,
            run=_artifact_runner(runner),
        )
    return projected


__all__ = [
    "CommandResult",
    "DeploymentSelection",
    "WorkflowDispatch",
    "deployment_context_digest",
    "dispatch_apply",
    "dispatch_plan",
    "enforce_plan_not_expired",
    "parse_plan_expiry",
    "request_binding_prefix",
    "request_id",
    "run_github_cli",
    "workflow_status",
]
