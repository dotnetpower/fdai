"""Submit plan-only deployment work after local target and toolchain checks."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

import httpx

from fdai.delivery.github.deployment_workflow import (
    GitHubActionsDeploymentTransport,
    GitHubDeploymentWorkflowConfig,
    TokenProvider,
)
from fdai.deployment_cli.doctor import DoctorReport
from fdai.deployment_cli.onboarding import OnboardingError, load_environment
from fdai.deployment_cli.remote import (
    DeploymentPlanContext,
    DeploymentPlanRecord,
    PlanStatus,
    RemoteDeploymentService,
)

PLAN_SUBMISSION_SCHEMA: Final[str] = "fdai.deployment-cli.plan-submission.v1"
PLAN_STATUS_SCHEMA: Final[str] = "fdai.deployment-cli.plan-status.v1"
APPLY_SUBMISSION_SCHEMA: Final[str] = "fdai.deployment-cli.apply-submission.v1"
_TOKEN_ENV: Final[str] = "FDAI_GITHUB_TOKEN"  # noqa: S105 - environment key, not a token


class PlanSubmissionError(RuntimeError):
    """Plan-only workflow submission could not be completed safely."""

    def to_json(self) -> str:
        return json.dumps(
            {"error": str(self), "schema_version": PLAN_SUBMISSION_SCHEMA},
            sort_keys=True,
            separators=(",", ":"),
        )


@dataclass(frozen=True, slots=True)
class PlanSubmissionResult:
    submission_id: str
    plan_id: str
    workflow_url: str
    schema_version: str = PLAN_SUBMISSION_SCHEMA

    def to_json(self) -> str:
        return json.dumps(
            {
                "schema_version": self.schema_version,
                "submission_id": self.submission_id,
                "plan_id": self.plan_id,
                "workflow_url": self.workflow_url,
            },
            sort_keys=True,
            separators=(",", ":"),
        )


@dataclass(frozen=True, slots=True)
class PlanStatusResult:
    plan_id: str
    plan_digest: str
    created_at: str
    expires_at: str
    status: str
    workflow_url: str
    schema_version: str = PLAN_STATUS_SCHEMA

    def to_json(self) -> str:
        return json.dumps(
            {
                "schema_version": self.schema_version,
                "plan_id": self.plan_id,
                "plan_digest": self.plan_digest,
                "created_at": self.created_at,
                "expires_at": self.expires_at,
                "status": self.status,
                "workflow_url": self.workflow_url,
            },
            sort_keys=True,
            separators=(",", ":"),
        )


@dataclass(frozen=True, slots=True)
class ApplySubmissionResult:
    plan_id: str
    submission_id: str
    workflow_url: str
    schema_version: str = APPLY_SUBMISSION_SCHEMA

    def to_json(self) -> str:
        return json.dumps(
            {
                "schema_version": self.schema_version,
                "plan_id": self.plan_id,
                "submission_id": self.submission_id,
                "workflow_url": self.workflow_url,
            },
            sort_keys=True,
            separators=(",", ":"),
        )


async def submit_github_plan(
    *,
    config_path: Path,
    repository: str,
    workflow_id: str,
    ref: str,
    bundle_digest: str,
    commit_sha: str,
    doctor_report: DoctorReport,
    deploy_console: bool = False,
    deploy_design_mocks: bool = False,
    deploy_operator_api: bool = False,
    deploy_dev_operations_gateway: bool = False,
    deploy_document_ingestion: bool = False,
    environ: Mapping[str, str] | None = None,
    http_client: httpx.AsyncClient | None = None,
) -> PlanSubmissionResult:
    """Submit one remote plan after doctor confirms the active Azure target."""
    if not doctor_report.ready:
        raise PlanSubmissionError(
            "deployment doctor checks failed; run fdaictl doctor with the same config"
        )
    try:
        environment = load_environment(config_path)
        context = DeploymentPlanContext(
            tenant_id=environment.azure.tenant_id,
            subscription_id=environment.azure.subscription_id,
            environment=environment.environment,
            bundle_digest=bundle_digest,
            commit_sha=commit_sha,
            backend_ref="backend:remote-state",
            runner_ref="runner:fdai-deploy",
            deploy_console=deploy_console,
            deploy_design_mocks=deploy_design_mocks,
            deploy_operator_api=deploy_operator_api,
            deploy_dev_operations_gateway=deploy_dev_operations_gateway,
            deploy_document_ingestion=deploy_document_ingestion,
        )
        transport_config = GitHubDeploymentWorkflowConfig(
            repository=repository,
            workflow_id=workflow_id,
            ref=ref,
        )
    except (OnboardingError, ValueError) as exc:
        raise PlanSubmissionError("deployment plan settings are invalid") from exc

    env = environ or os.environ

    async def token_provider() -> str:
        return env.get(_TOKEN_ENV, "")

    if http_client is not None:
        return await _submit(
            context,
            transport_config,
            http_client=http_client,
            token_provider=token_provider,
        )
    async with httpx.AsyncClient() as owned_client:
        return await _submit(
            context,
            transport_config,
            http_client=owned_client,
            token_provider=token_provider,
        )


async def _submit(
    context: DeploymentPlanContext,
    transport_config: GitHubDeploymentWorkflowConfig,
    *,
    http_client: httpx.AsyncClient,
    token_provider: TokenProvider,
) -> PlanSubmissionResult:
    transport = GitHubActionsDeploymentTransport(
        config=transport_config,
        http_client=http_client,
        token_provider=token_provider,
    )
    try:
        submission = await RemoteDeploymentService(transport=transport).submit_plan(context)
    except RuntimeError as exc:
        raise PlanSubmissionError(str(exc)) from exc
    return PlanSubmissionResult(
        submission_id=submission.submission_id,
        plan_id=f"plan-{submission.submission_id}-1",
        workflow_url=submission.workflow_url,
    )


async def get_github_plan_status(
    *,
    repository: str,
    plan_id: str,
    environ: Mapping[str, str] | None = None,
    http_client: httpx.AsyncClient | None = None,
    now: datetime | None = None,
) -> PlanStatusResult:
    """Read sanitized plan metadata without accessing the binary plan."""
    try:
        transport_config = GitHubDeploymentWorkflowConfig(repository=repository)
    except ValueError as exc:
        raise PlanSubmissionError("deployment status settings are invalid") from exc
    env = environ or os.environ

    async def token_provider() -> str:
        return env.get(_TOKEN_ENV, "")

    if http_client is not None:
        return await _get_status(
            plan_id,
            transport_config,
            http_client=http_client,
            token_provider=token_provider,
            now=now or datetime.now(UTC),
        )
    async with httpx.AsyncClient() as owned_client:
        return await _get_status(
            plan_id,
            transport_config,
            http_client=owned_client,
            token_provider=token_provider,
            now=now or datetime.now(UTC),
        )


async def _get_status(
    plan_id: str,
    transport_config: GitHubDeploymentWorkflowConfig,
    *,
    http_client: httpx.AsyncClient,
    token_provider: TokenProvider,
    now: datetime,
) -> PlanStatusResult:
    transport = GitHubActionsDeploymentTransport(
        config=transport_config,
        http_client=http_client,
        token_provider=token_provider,
    )
    try:
        record = await transport.get_plan(plan_id)
    except RuntimeError as exc:
        raise PlanSubmissionError(str(exc)) from exc
    return PlanStatusResult(
        plan_id=record.plan_id,
        plan_digest=record.plan_digest,
        created_at=record.created_at.isoformat().replace("+00:00", "Z"),
        expires_at=record.expires_at.isoformat().replace("+00:00", "Z"),
        status=_effective_status(record, now=now).value,
        workflow_url=record.workflow_url,
    )


async def submit_github_apply(
    *,
    config_path: Path,
    repository: str,
    plan_id: str,
    bundle_digest: str,
    commit_sha: str,
    doctor_report: DoctorReport,
    deploy_console: bool = False,
    deploy_design_mocks: bool = False,
    deploy_operator_api: bool = False,
    deploy_dev_operations_gateway: bool = False,
    deploy_document_ingestion: bool = False,
    resume_verification: bool = False,
    now: datetime | None = None,
    environ: Mapping[str, str] | None = None,
    http_client: httpx.AsyncClient | None = None,
) -> ApplySubmissionResult:
    """Reload, validate, and submit one exact protected plan for remote apply."""
    if not doctor_report.ready:
        raise PlanSubmissionError(
            "deployment doctor checks failed; run fdaictl doctor with the same config"
        )
    try:
        environment = load_environment(config_path)
        context = DeploymentPlanContext(
            tenant_id=environment.azure.tenant_id,
            subscription_id=environment.azure.subscription_id,
            environment=environment.environment,
            bundle_digest=bundle_digest,
            commit_sha=commit_sha,
            backend_ref="backend:remote-state",
            runner_ref="runner:fdai-deploy",
            deploy_console=deploy_console,
            deploy_design_mocks=deploy_design_mocks,
            deploy_operator_api=deploy_operator_api,
            deploy_dev_operations_gateway=deploy_dev_operations_gateway,
            deploy_document_ingestion=deploy_document_ingestion,
        )
        transport_config = GitHubDeploymentWorkflowConfig(repository=repository)
    except (OnboardingError, ValueError) as exc:
        raise PlanSubmissionError("deployment apply settings are invalid") from exc
    env = environ or os.environ

    async def token_provider() -> str:
        return env.get(_TOKEN_ENV, "")

    if http_client is not None:
        return await _submit_apply(
            plan_id,
            context,
            transport_config,
            now=now or datetime.now(UTC),
            http_client=http_client,
            token_provider=token_provider,
            resume_verification=resume_verification,
        )
    async with httpx.AsyncClient() as owned_client:
        return await _submit_apply(
            plan_id,
            context,
            transport_config,
            now=now or datetime.now(UTC),
            http_client=owned_client,
            token_provider=token_provider,
            resume_verification=resume_verification,
        )


async def _submit_apply(
    plan_id: str,
    context: DeploymentPlanContext,
    transport_config: GitHubDeploymentWorkflowConfig,
    *,
    now: datetime,
    http_client: httpx.AsyncClient,
    token_provider: TokenProvider,
    resume_verification: bool = False,
) -> ApplySubmissionResult:
    transport = GitHubActionsDeploymentTransport(
        config=transport_config,
        http_client=http_client,
        token_provider=token_provider,
    )
    try:
        submission = await RemoteDeploymentService(transport=transport).submit_apply(
            plan_id=plan_id,
            expected_context=context,
            now=now,
            resume_verification=resume_verification,
        )
    except RuntimeError as exc:
        raise PlanSubmissionError(str(exc)) from exc
    return ApplySubmissionResult(
        plan_id=plan_id,
        submission_id=submission.submission_id,
        workflow_url=submission.workflow_url,
    )


def _effective_status(record: DeploymentPlanRecord, *, now: datetime) -> PlanStatus:
    if record.status is PlanStatus.READY and now >= record.expires_at:
        return PlanStatus.EXPIRED
    return record.status


__all__ = [
    "PLAN_SUBMISSION_SCHEMA",
    "PLAN_STATUS_SCHEMA",
    "APPLY_SUBMISSION_SCHEMA",
    "ApplySubmissionResult",
    "PlanSubmissionError",
    "PlanSubmissionResult",
    "PlanStatusResult",
    "get_github_plan_status",
    "submit_github_apply",
    "submit_github_plan",
]
