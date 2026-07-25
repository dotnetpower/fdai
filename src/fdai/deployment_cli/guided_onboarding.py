"""Guided plan-only deployment onboarding orchestration."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Final, Protocol

from fdai.deployment_cli.doctor import DoctorReport, run_doctor
from fdai.deployment_cli.onboarding import (
    EnvironmentName,
    OnboardingError,
    OnboardingResult,
    initialize_environment,
)
from fdai.deployment_cli.plan_submission import (
    PlanStatusResult,
    PlanSubmissionError,
    PlanSubmissionResult,
    get_github_plan_status,
    submit_github_plan,
)
from fdai.deployment_cli.preflight import (
    PreflightInputError,
    StaticPreflightResult,
    run_azure_live_preflight,
)

GUIDED_ONBOARDING_SCHEMA: Final = "fdai.deployment-cli.guided-onboarding.v1"
_ACCEPTED_POST_CHECK_STATUSES: Final = frozenset(("planning", "ready"))
_POST_CHECK_ATTEMPTS: Final = 30
_POST_CHECK_INTERVAL_SECONDS: Final = 2.0
_TRANSIENT_STATUS_ERROR: Final = "plan metadata artifact is missing or ambiguous"


class DoctorRunner(Protocol):
    def __call__(self, *, config_path: Path | None = None) -> DoctorReport: ...


class EnvironmentInitializer(Protocol):
    def __call__(
        self,
        *,
        environment: EnvironmentName,
        region: str,
        destination: Path | None = None,
        force: bool = False,
    ) -> OnboardingResult: ...


class PreflightRunner(Protocol):
    async def __call__(
        self,
        input_path: Path,
        environment_path: Path,
        terraform_plan_path: Path | None = None,
    ) -> StaticPreflightResult: ...


class PlanSubmitter(Protocol):
    async def __call__(
        self,
        *,
        config_path: Path,
        repository: str,
        workflow_id: str,
        ref: str,
        bundle_digest: str,
        commit_sha: str,
        doctor_report: DoctorReport,
        deploy_console: bool,
        deploy_read_api: bool,
        deploy_dev_operations_gateway: bool,
        deploy_document_ingestion: bool,
    ) -> PlanSubmissionResult: ...


class PlanStatusReader(Protocol):
    async def __call__(self, *, repository: str, plan_id: str) -> PlanStatusResult: ...


@dataclass(frozen=True, slots=True)
class GuidedOnboardingRequest:
    environment: EnvironmentName
    region: str
    config_path: Path
    preflight_input_path: Path
    repository: str
    bundle_digest: str
    commit_sha: str
    terraform_plan_path: Path | None = None
    workflow_id: str = "deploy-dev.yml"
    ref: str = "main"
    force_config: bool = False
    deploy_console: bool = False
    deploy_read_api: bool = False
    deploy_dev_operations_gateway: bool = False
    deploy_document_ingestion: bool = False


@dataclass(frozen=True, slots=True)
class GuidedOnboardingStep:
    step_id: str
    status: str
    summary: str


@dataclass(frozen=True, slots=True)
class GuidedOnboardingResult:
    steps: tuple[GuidedOnboardingStep, ...]
    config_path: str
    submission_id: str
    plan_id: str
    plan_status: str
    workflow_url: str
    schema_version: str = GUIDED_ONBOARDING_SCHEMA

    def to_json(self) -> str:
        return json.dumps(
            {
                "config_path": self.config_path,
                "plan_id": self.plan_id,
                "plan_status": self.plan_status,
                "schema_version": self.schema_version,
                "steps": [asdict(step) for step in self.steps],
                "submission_id": self.submission_id,
                "workflow_url": self.workflow_url,
            },
            sort_keys=True,
            separators=(",", ":"),
        )


class GuidedOnboardingError(RuntimeError):
    """A guided onboarding stage failed before plan-only completion."""

    def __init__(self, step_id: str, message: str) -> None:
        super().__init__(message)
        self.step_id = step_id

    def to_json(self) -> str:
        return json.dumps(
            {
                "error": str(self),
                "failed_step": self.step_id,
                "schema_version": GUIDED_ONBOARDING_SCHEMA,
            },
            sort_keys=True,
            separators=(",", ":"),
        )


async def run_guided_onboarding(
    request: GuidedOnboardingRequest,
    *,
    doctor_runner: DoctorRunner = run_doctor,
    environment_initializer: EnvironmentInitializer = initialize_environment,
    preflight_runner: PreflightRunner = run_azure_live_preflight,
    plan_submitter: PlanSubmitter = submit_github_plan,
    status_reader: PlanStatusReader = get_github_plan_status,
    post_check_attempts: int = _POST_CHECK_ATTEMPTS,
    post_check_interval_seconds: float = _POST_CHECK_INTERVAL_SECONDS,
    sleeper: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> GuidedOnboardingResult:
    """Run guarded setup through plan status without any local apply path."""
    steps: list[GuidedOnboardingStep] = []
    toolchain_report = doctor_runner(config_path=None)
    _require_doctor_ready(toolchain_report, step_id="doctor-toolchain")
    steps.append(_step("doctor-toolchain", "pass", "Local toolchain and authentication passed"))

    try:
        initialized = environment_initializer(
            environment=request.environment,
            region=request.region,
            destination=request.config_path,
            force=request.force_config,
        )
    except (OnboardingError, OSError, ValueError) as exc:
        raise GuidedOnboardingError(
            "config", "Environment configuration could not be created safely"
        ) from exc
    steps.append(_step("config", "pass", "Private environment configuration was created"))

    target_report = doctor_runner(config_path=request.config_path)
    _require_doctor_ready(target_report, step_id="doctor-target")
    steps.append(_step("doctor-target", "pass", "Active Azure target matches configuration"))

    try:
        preflight = await preflight_runner(
            request.preflight_input_path,
            request.config_path,
            request.terraform_plan_path,
        )
    except (PreflightInputError, OSError, ValueError) as exc:
        raise GuidedOnboardingError(
            "preflight", "Deployment preflight could not produce a complete report"
        ) from exc
    if preflight.report.blocks_deploy:
        raise GuidedOnboardingError("preflight", "Deployment preflight reported a blocker")
    preflight_status = "warning" if preflight.report.findings else "pass"
    steps.append(
        _step(
            "preflight",
            preflight_status,
            "Deployment preflight completed without blockers",
        )
    )

    try:
        submission = await plan_submitter(
            config_path=request.config_path,
            repository=request.repository,
            workflow_id=request.workflow_id,
            ref=request.ref,
            bundle_digest=request.bundle_digest,
            commit_sha=request.commit_sha,
            doctor_report=target_report,
            deploy_console=request.deploy_console,
            deploy_read_api=request.deploy_read_api,
            deploy_dev_operations_gateway=request.deploy_dev_operations_gateway,
            deploy_document_ingestion=request.deploy_document_ingestion,
        )
    except (PlanSubmissionError, OSError, ValueError) as exc:
        raise GuidedOnboardingError(
            "runner-submission", "Plan-only runner submission failed"
        ) from exc
    steps.append(_step("runner-submission", "pass", "Plan-only runner workflow was submitted"))

    if post_check_attempts < 1 or post_check_interval_seconds < 0:
        raise ValueError("guided post-check retry settings are invalid")
    status: PlanStatusResult | None = None
    for attempt in range(post_check_attempts):
        try:
            status = await status_reader(
                repository=request.repository,
                plan_id=submission.plan_id,
            )
        except PlanSubmissionError as exc:
            retryable = _TRANSIENT_STATUS_ERROR in str(exc).lower()
            if not retryable or attempt == post_check_attempts - 1:
                raise GuidedOnboardingError("post-check", "Plan status post-check failed") from exc
            await sleeper(post_check_interval_seconds)
        except (OSError, ValueError) as exc:
            raise GuidedOnboardingError("post-check", "Plan status post-check failed") from exc
        else:
            break
    if status is None:
        raise GuidedOnboardingError("post-check", "Plan status post-check failed")
    if status.plan_id != submission.plan_id or status.status not in _ACCEPTED_POST_CHECK_STATUSES:
        raise GuidedOnboardingError("post-check", "Plan status post-check returned an unsafe state")
    steps.append(_step("post-check", "pass", "Sanitized plan status is available"))

    return GuidedOnboardingResult(
        steps=tuple(steps),
        config_path=initialized.path,
        submission_id=submission.submission_id,
        plan_id=submission.plan_id,
        plan_status=status.status,
        workflow_url=submission.workflow_url,
    )


def _require_doctor_ready(report: DoctorReport, *, step_id: str) -> None:
    if not report.ready:
        raise GuidedOnboardingError(step_id, "Deployment doctor checks failed")


def _step(step_id: str, status: str, summary: str) -> GuidedOnboardingStep:
    return GuidedOnboardingStep(step_id=step_id, status=status, summary=summary)


__all__ = [
    "GUIDED_ONBOARDING_SCHEMA",
    "GuidedOnboardingError",
    "GuidedOnboardingRequest",
    "GuidedOnboardingResult",
    "GuidedOnboardingStep",
    "run_guided_onboarding",
]
