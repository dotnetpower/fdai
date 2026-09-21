"""Protected GitHub workflow plan and apply dispatch."""

from __future__ import annotations

from fdai_deployment_cli.github_transport import run_github_cli
from fdai_deployment_cli.github_workflow_values import (
    _COMMIT,
    _DIGEST,
    _ENVIRONMENTS,
    _PLAN_ID,
    _REQUEST_ID,
    CommandRunner,
    DeploymentSelection,
    WorkflowDispatch,
    _validate_repository,
    deployment_context_digest,
    enforce_plan_not_expired,
    request_id,
)


def dispatch_plan(
    *,
    repository: str,
    environment: str,
    commit_sha: str,
    target_binding: str,
    region: str,
    run_id: str,
    selection: DeploymentSelection,
    attempt: int = 1,
    run: CommandRunner | None = None,
) -> WorkflowDispatch:
    """Dispatch one protected plan-only run."""

    if environment == "prod":
        raise ValueError("fdaictl production deployment inputs are not implemented")
    context_digest = deployment_context_digest(
        environment=environment,
        commit_sha=commit_sha,
        selection=selection,
    )
    bounded_request_id = request_id(
        "plan",
        run_id=run_id,
        context_digest=context_digest,
        target_binding=target_binding,
        region=region,
        attempt=attempt,
    )
    if selection.deploy_rca_reader_identity:
        bounded_request_id = bounded_request_id.replace("plan-", "plan-rca-", 1)
    elif selection.deploy_provider_schema:
        request_prefix = (
            "plan-provider-cost-"
            if selection.runtime_image_profile == "cost-governance"
            else "plan-provider-"
        )
        bounded_request_id = bounded_request_id.replace("plan-", request_prefix, 1)
    elif selection.deploy_identity_migration:
        bounded_request_id = bounded_request_id.replace("plan-", "plan-identity-", 1)
    elif selection.deploy_operational_history:
        bounded_request_id = bounded_request_id.replace("plan-", "plan-history-", 1)
    elif selection.runtime_image_profile == "cost-governance":
        bounded_request_id = bounded_request_id.replace("plan-", "plan-cost-", 1)
    _dispatch(
        repository=repository,
        environment=environment,
        commit_sha=commit_sha,
        context_digest=context_digest,
        request_id_value=bounded_request_id,
        apply=False,
        plan_id=None,
        plan_digest=None,
        resume_verification=False,
        selection=selection,
        run=run,
    )
    return WorkflowDispatch(
        request_id=bounded_request_id,
        run_name=f"deploy-{bounded_request_id}",
        context_digest=context_digest,
        mode="plan",
    )


def dispatch_apply(
    *,
    repository: str,
    environment: str,
    commit_sha: str,
    target_binding: str,
    region: str,
    approval_quorum: int,
    run_id: str,
    plan_id: str,
    plan_digest: str,
    plan_expires_at: str,
    resume_verification: bool,
    selection: DeploymentSelection,
    attempt: int = 1,
    run: CommandRunner | None = None,
) -> WorkflowDispatch:
    """Dispatch exact-plan apply or verification-only resume."""

    if environment == "prod":
        raise ValueError("fdaictl production deployment inputs are not implemented")
    if _PLAN_ID.fullmatch(plan_id) is None:
        raise ValueError("plan_id is invalid")
    if _DIGEST.fullmatch(plan_digest) is None:
        raise ValueError("plan_digest MUST be a lowercase SHA-256")
    if not resume_verification:
        enforce_plan_not_expired(plan_expires_at)
    context_digest = deployment_context_digest(
        environment=environment,
        commit_sha=commit_sha,
        selection=selection,
    )
    if _DIGEST.fullmatch(target_binding) is None:
        raise ValueError("target_binding MUST be a lowercase SHA-256")
    if approval_quorum < 1:
        raise ValueError("approval_quorum MUST be positive")
    runner = run or run_github_cli
    bounded_request_id = request_id(
        "resume" if resume_verification else "apply",
        run_id=run_id,
        context_digest=context_digest,
        target_binding=target_binding,
        region=region,
        attempt=attempt,
    )
    if selection.deploy_rca_reader_identity:
        bounded_request_id = bounded_request_id.replace("apply-", "apply-rca-", 1)
    elif selection.deploy_provider_schema:
        request_prefix = (
            "apply-provider-cost-"
            if selection.runtime_image_profile == "cost-governance"
            else "apply-provider-"
        )
        bounded_request_id = bounded_request_id.replace("apply-", request_prefix, 1)
    elif selection.deploy_identity_migration:
        bounded_request_id = bounded_request_id.replace("apply-", "apply-identity-", 1)
    elif selection.deploy_operational_history:
        bounded_request_id = bounded_request_id.replace("apply-", "apply-history-", 1)
    elif selection.runtime_image_profile == "cost-governance":
        bounded_request_id = bounded_request_id.replace("apply-", "apply-cost-", 1)
    _dispatch(
        repository=repository,
        environment=environment,
        commit_sha=commit_sha,
        context_digest=context_digest,
        request_id_value=bounded_request_id,
        apply=True,
        plan_id=plan_id,
        plan_digest=plan_digest,
        resume_verification=resume_verification,
        selection=selection,
        run=runner,
    )
    return WorkflowDispatch(
        request_id=bounded_request_id,
        run_name=f"deploy-{bounded_request_id}",
        context_digest=context_digest,
        mode="resume-verification" if resume_verification else "apply",
    )


def _dispatch(
    *,
    repository: str,
    environment: str,
    commit_sha: str,
    context_digest: str,
    request_id_value: str,
    apply: bool,
    plan_id: str | None,
    plan_digest: str | None,
    resume_verification: bool,
    selection: DeploymentSelection,
    run: CommandRunner | None,
) -> None:
    _validate_repository(repository)
    if environment not in _ENVIRONMENTS:
        raise ValueError("environment is unsupported")
    if _COMMIT.fullmatch(commit_sha) is None:
        raise ValueError("commit_sha MUST be a lowercase git SHA")
    if _REQUEST_ID.fullmatch(request_id_value) is None:
        raise ValueError("request_id is invalid")
    fields: dict[str, str] = {
        "environment": environment,
        "apply": str(apply).lower(),
        "promote_runtime_image": str(bool(selection.runtime_image_revision) and not apply).lower(),
        "resume_verification": str(resume_verification).lower(),
        "request_id": request_id_value,
        "context_digest": context_digest,
        "commit_sha": commit_sha,
        **{
            key: str(value).lower()
            for key, value in selection.to_mapping().items()
            if key
            not in {
                "deploy_identity_migration",
                "deploy_operational_history",
                "deploy_provider_schema",
                "deploy_rca_reader_identity",
                "runtime_call_evidence_transition",
                "runtime_image_profile",
            }
        },
    }
    if apply:
        if plan_id is None or plan_digest is None:
            raise ValueError("exact apply requires plan id and digest")
        fields["plan_id"] = plan_id
        fields["plan_digest"] = plan_digest
    workflow = "deploy-dev.yml"
    if apply and (selection.deploy_operational_history or selection.deploy_rca_reader_identity):
        workflow = "request-protected-operation.yml"
        fields = {
            "operation": (
                "operational-history-apply"
                if selection.deploy_operational_history
                else "rca-reader-apply"
            ),
            "environment": environment,
            "commit_sha": commit_sha,
            "request_id": request_id_value,
            "context_digest": context_digest,
            "plan_id": fields["plan_id"],
            "plan_digest": fields["plan_digest"],
            "resume_verification": str(resume_verification).lower(),
        }
        if selection.deploy_operational_history:
            fields["runtime_image_revision"] = selection.runtime_image_revision
    arguments = [
        "workflow",
        "run",
        workflow,
        "--repo",
        repository,
        "--ref",
        "main",
    ]
    for key, value in fields.items():
        arguments.extend(("--field", f"{key}={value}"))
    result = (run or run_github_cli)(tuple(arguments))
    if result.returncode != 0:
        raise ValueError("github_workflow_dispatch_failed")
