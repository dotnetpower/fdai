"""Bounded GitHub Actions transport for protected FDAI deployment workflows."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from fdai_deployment_cli.contracts import canonical_digest

_REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_OCI_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_PLAN_ID = re.compile(r"^plan-[1-9][0-9]*-[1-9][0-9]*$")
_REQUEST_ID = re.compile(
    r"^(?:plan|apply)-(?:cost-|history-|identity-|provider-|rca-)?[0-9a-f]{48}$"
)
_ENVIRONMENTS = frozenset({"dev", "staging", "prod"})
_RUNTIME_IMAGE_PROFILES = frozenset({"core-control-plane", "cost-governance"})
_BOOL_INPUTS = (
    "deploy_console",
    "deploy_dev_operations_gateway",
    "deploy_document_ingestion",
    "deploy_identity_migration",
    "deploy_isolated_executor",
    "deploy_monitoring",
    "deploy_operational_history",
    "deploy_operator_api",
)
_EXPIRES_AT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

# Artifact downloads are larger than metadata queries; use a longer timeout.
_ARTIFACT_DOWNLOAD_TIMEOUT = 90
_DEFAULT_GH_TIMEOUT = 30
_CORE_POST_APPLY_OBSERVATIONS = [
    "database-migrations",
    "runtime-health",
    "initial-inventory-execution",
    "canary-publisher",
    "terraform-zero-change",
]
_COST_GOVERNANCE_POST_APPLY_OBSERVATIONS = [
    "terraform-zero-change",
    "cost-governance-job-image-readback",
]


@dataclass(frozen=True, slots=True)
class CommandResult:
    """Bounded process result from one fixed GitHub CLI invocation."""

    returncode: int
    stdout: str
    stderr: str = ""


CommandRunner = Callable[[tuple[str, ...]], CommandResult]


@dataclass(frozen=True, slots=True)
class DeploymentSelection:
    """Feature selection sealed into both protected plan and apply requests."""

    deploy_console: bool = True
    deploy_dev_operations_gateway: bool = False
    deploy_document_ingestion: bool = False
    deploy_identity_migration: bool = False
    deploy_isolated_executor: bool = False
    deploy_monitoring: bool = False
    deploy_operational_history: bool = False
    deploy_operator_api: bool = True
    deploy_operator_channel_edge: bool = False
    deploy_provider_schema: bool = False
    deploy_rca_reader_identity: bool = False
    runtime_image_revision: str = ""
    runtime_image_profile: str = "core-control-plane"

    def __post_init__(self) -> None:
        application_targets = (
            self.deploy_console,
            self.deploy_dev_operations_gateway,
            self.deploy_document_ingestion,
            self.deploy_isolated_executor,
            self.deploy_operational_history,
            self.deploy_operator_api,
            self.deploy_operator_channel_edge,
            self.deploy_provider_schema,
        )
        if self.deploy_monitoring and not any(application_targets) and self.runtime_image_revision:
            raise ValueError("monitoring deployment cannot be combined with application targets")
        if self.runtime_image_revision:
            if _COMMIT.fullmatch(self.runtime_image_revision) is None:
                raise ValueError("runtime_image_revision MUST be a lowercase 40-character git SHA")
        if self.runtime_image_profile not in _RUNTIME_IMAGE_PROFILES:
            raise ValueError("runtime_image_profile is unsupported")
        if self.runtime_image_profile != "core-control-plane" and not self.runtime_image_revision:
            raise ValueError("non-default runtime_image_profile requires runtime_image_revision")
        if self.runtime_image_profile != "core-control-plane" and (
            self.deploy_identity_migration
            or self.deploy_operational_history
            or self.deploy_rca_reader_identity
        ):
            raise ValueError(
                "non-default runtime_image_profile cannot be combined with a bounded operation"
            )
        if self.deploy_provider_schema:
            if self.runtime_image_profile != "core-control-plane":
                raise ValueError(
                    "deploy_provider_schema requires the core-control-plane runtime image profile"
                )
            provider_schema_mixed = (
                self.deploy_console,
                self.deploy_dev_operations_gateway,
                self.deploy_document_ingestion,
                self.deploy_identity_migration,
                self.deploy_isolated_executor,
                self.deploy_monitoring,
                self.deploy_operational_history,
                self.deploy_operator_api,
                self.deploy_operator_channel_edge,
                self.deploy_rca_reader_identity,
            )
            if any(provider_schema_mixed):
                raise ValueError(
                    "deploy_provider_schema cannot be combined with another deployment target"
                )
            if not self.runtime_image_revision:
                raise ValueError("deploy_provider_schema requires runtime_image_revision")
        if self.deploy_rca_reader_identity and (
            any(application_targets) or self.deploy_monitoring or self.runtime_image_revision
        ):
            raise ValueError(
                "deploy_rca_reader_identity cannot be combined with another deployment target"
            )
        if self.deploy_identity_migration and (
            any(application_targets)
            or self.deploy_monitoring
            or self.deploy_operational_history
            or self.deploy_rca_reader_identity
            or self.runtime_image_revision
        ):
            raise ValueError(
                "deploy_identity_migration cannot be combined with another bounded operation"
            )

    def to_mapping(self) -> dict[str, bool | str]:
        """Return workflow input names in stable order."""

        result: dict[str, bool | str] = {name: bool(getattr(self, name)) for name in _BOOL_INPUTS}
        if self.deploy_operator_channel_edge:
            result["deploy_operator_channel_edge"] = True
        if self.deploy_provider_schema:
            result["deploy_provider_schema"] = True
        result["deploy_rca_reader_identity"] = self.deploy_rca_reader_identity
        result["document_ocr_action"] = "preserve"
        result["runtime_call_evidence_transition"] = False
        result["runtime_image_revision"] = self.runtime_image_revision
        result["runtime_image_profile"] = self.runtime_image_profile
        return result


@dataclass(frozen=True, slots=True)
class WorkflowDispatch:
    """Sanitized receipt for one accepted workflow dispatch."""

    request_id: str
    run_name: str
    context_digest: str
    mode: str

    def to_mapping(self) -> dict[str, object]:
        """Return stable dispatch output without credentials or target identifiers."""

        return {
            "schema_version": "fdai.workflow-dispatch.v1",
            "request_id": self.request_id,
            "run_name": self.run_name,
            "context_digest": self.context_digest,
            "mode": self.mode,
            "mutation_performed": True,
        }


def parse_plan_expiry(expires_at: str) -> datetime:
    """Parse a strict ISO-8601 UTC timestamp or raise fail-closed."""

    if _EXPIRES_AT_RE.fullmatch(expires_at) is None:
        raise ValueError("expires_at MUST be an ISO-8601 UTC timestamp ending in Z")
    try:
        return datetime.fromisoformat(expires_at)
    except ValueError as exc:
        raise ValueError("expires_at contains an invalid date or time") from exc


def enforce_plan_not_expired(
    expires_at: str,
    *,
    now: datetime | None = None,
) -> None:
    """Fail-closed: reject expired plans before apply dispatch."""

    deadline = parse_plan_expiry(expires_at)
    current = now if now is not None else datetime.now(UTC)
    if current >= deadline:
        raise ValueError("protected plan has expired; replan before applying")


def deployment_context_digest(
    *,
    environment: str,
    commit_sha: str,
    selection: DeploymentSelection,
) -> str:
    """Seal the non-secret deployment inputs shared by plan and apply."""

    if environment not in _ENVIRONMENTS:
        raise ValueError("environment is unsupported")
    if _COMMIT.fullmatch(commit_sha) is None:
        raise ValueError("commit_sha MUST be a lowercase git SHA")
    return canonical_digest(
        {
            "schema_version": "fdai.deployment-context.v1",
            "environment": environment,
            "commit_sha": commit_sha,
            "selection": selection.to_mapping(),
        }
    )


def request_id(
    mode: str,
    *,
    run_id: str,
    context_digest: str,
    target_binding: str,
    region: str,
    attempt: int = 1,
) -> str:
    """Derive one bounded request id without exposing the local run id."""

    if mode not in {"plan", "apply", "resume"}:
        raise ValueError("workflow request mode is unsupported")
    if not run_id or len(run_id) > 128:
        raise ValueError("run_id MUST be from 1 through 128 characters")
    if _DIGEST.fullmatch(context_digest) is None:
        raise ValueError("context_digest MUST be a lowercase SHA-256")
    if _DIGEST.fullmatch(target_binding) is None:
        raise ValueError("target_binding MUST be a lowercase SHA-256")
    if not region or len(region) > 64:
        raise ValueError("region is invalid")
    if not 1 <= attempt <= 9_999:
        raise ValueError("workflow attempt MUST be from 1 through 9999")
    binding = request_binding_prefix(
        target_binding=target_binding,
        context_digest=context_digest,
        mode=mode,
        region=region,
    )
    run_key = canonical_digest({"run_id": run_id})[:20]
    suffix = f"{binding}{run_key}{attempt:04x}"
    prefix = "apply" if mode == "resume" else mode
    return f"{prefix}-{suffix}"


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
        bounded_request_id = bounded_request_id.replace("plan-", "plan-provider-", 1)
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
        bounded_request_id = bounded_request_id.replace("apply-", "apply-provider-", 1)
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


def _request_binding_from_id(request_id_value: str) -> str:
    """Return the target/context binding embedded in one validated request id."""

    for prefix in (
        "plan-history-",
        "apply-history-",
        "plan-identity-",
        "apply-identity-",
        "plan-provider-",
        "apply-provider-",
        "plan-rca-",
        "apply-rca-",
        "plan-cost-",
        "apply-cost-",
        "plan-",
        "apply-",
    ):
        if request_id_value.startswith(prefix):
            return request_id_value.removeprefix(prefix)[:24]
    raise ValueError("request_id is invalid")


def run_github_cli(
    arguments: tuple[str, ...],
    timeout: int = _DEFAULT_GH_TIMEOUT,
) -> CommandResult:
    """Execute one fixed GitHub CLI command with bounded output and duration."""

    executable = shutil.which("gh")
    if executable is None:
        raise OSError("GitHub CLI is unavailable")
    try:
        completed = subprocess.run(
            [executable, *arguments],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return CommandResult(returncode=124, stdout="", stderr="")
    return CommandResult(
        returncode=completed.returncode,
        stdout=completed.stdout[:65_536],
        stderr=completed.stderr[:65_536],
    )


def request_binding_prefix(
    *,
    target_binding: str,
    context_digest: str,
    mode: str,
    region: str,
) -> str:
    """Return the target-bound prefix independently recomputed by the workflow."""

    if _DIGEST.fullmatch(target_binding) is None:
        raise ValueError("target_binding MUST be a lowercase SHA-256")
    if _DIGEST.fullmatch(context_digest) is None:
        raise ValueError("context_digest MUST be a lowercase SHA-256")
    if mode not in {"plan", "apply", "resume"}:
        raise ValueError("workflow request mode is unsupported")
    if not region or len(region) > 64:
        raise ValueError("region is invalid")
    return canonical_digest(
        {
            "target_binding": target_binding,
            "context_digest": context_digest,
            "mode": mode,
            "region": region.casefold(),
        }
    )[:24]


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


def _validate_repository(repository: str) -> None:
    if _REPOSITORY.fullmatch(repository) is None or ".." in repository:
        raise ValueError("repository MUST be owner/name")


def _artifact_runner(base: CommandRunner) -> CommandRunner:
    """Wrap the real runner with a longer timeout for artifact downloads."""

    if base is not run_github_cli:
        return base  # Test runners handle their own timing.
    return lambda args: run_github_cli(args, timeout=_ARTIFACT_DOWNLOAD_TIMEOUT)


def _download_plan_metadata(
    *,
    repository: str,
    workflow_run_id: int,
    request_id_value: str,
    expected_commit: str,
    expected_context_digest: str,
    run: CommandRunner,
) -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="fdai-plan-status-") as raw_directory:
        directory = Path(raw_directory)
        result = run(
            (
                "run",
                "download",
                str(workflow_run_id),
                "--repo",
                repository,
                "--name",
                f"deployment-plan-metadata-{request_id_value}",
                "--dir",
                str(directory),
            )
        )
        if result.returncode != 0:
            raise ValueError("github_plan_metadata_unavailable")
        path = directory / "plan-metadata.json"
        details = path.lstat()
        if (
            not stat.S_ISREG(details.st_mode)
            or details.st_uid != os.geteuid()
            or details.st_size > 262_144
        ):
            raise ValueError("github_plan_metadata_file_invalid")
        payload = _json_object(path.read_text(encoding="utf-8"), "plan metadata")
    required = {
        "schema_version": "fdai.deployment-plan.v1",
        "request_id": request_id_value,
        "commit_sha": expected_commit,
        "context_digest": expected_context_digest,
        "status": "ready",
    }
    if any(payload.get(key) != value for key, value in required.items()):
        raise ValueError("github_plan_metadata_context_mismatch")
    plan_id = payload.get("plan_id")
    plan_digest = payload.get("plan_digest")
    context_digest = payload.get("context_digest")
    expires_at = payload.get("expires_at")
    if (
        not isinstance(plan_id, str)
        or _PLAN_ID.fullmatch(plan_id) is None
        or not isinstance(plan_digest, str)
        or _DIGEST.fullmatch(plan_digest) is None
        or not isinstance(context_digest, str)
        or _DIGEST.fullmatch(context_digest) is None
        or not isinstance(expires_at, str)
    ):
        raise ValueError("github_plan_metadata_invalid")
    summary = _plan_summary(payload.get("plan_summary"))
    observations = payload.get("post_apply_observations")
    cost_governance = request_id_value.startswith("plan-cost-")
    expected_observations = (
        _COST_GOVERNANCE_POST_APPLY_OBSERVATIONS
        if cost_governance
        else _CORE_POST_APPLY_OBSERVATIONS
    )
    if observations != expected_observations:
        raise ValueError("github_plan_metadata_observations_invalid")
    runtime_image = payload.get("runtime_image")
    if cost_governance and (
        not isinstance(runtime_image, dict)
        or set(runtime_image) != {"source_revision", "digest", "profile"}
        or not isinstance(runtime_image.get("source_revision"), str)
        or _COMMIT.fullmatch(runtime_image["source_revision"]) is None
        or not isinstance(runtime_image.get("digest"), str)
        or _OCI_DIGEST.fullmatch(runtime_image["digest"]) is None
        or runtime_image.get("profile") != "cost-governance"
    ):
        raise ValueError("github_plan_metadata_runtime_image_invalid")
    return {
        "plan_id": plan_id,
        "plan_digest": plan_digest,
        "context_digest": context_digest,
        "expires_at": expires_at,
        "status": "ready",
        "plan_summary": summary,
        "post_apply_observations": observations,
    }


def _plan_summary(value: object) -> dict[str, object]:
    """Validate one address-free protected-plan action summary."""

    if not isinstance(value, dict) or set(value) != {
        "schema_version",
        "action_counts",
        "resource_type_counts",
        "managed_resources",
        "destructive",
        "summary_digest",
    }:
        raise ValueError("github_plan_summary_invalid")
    digest = value.get("summary_digest")
    body = {key: item for key, item in value.items() if key != "summary_digest"}
    if (
        value.get("schema_version") != "fdai.deployment-plan-summary.v1"
        or not isinstance(digest, str)
        or _DIGEST.fullmatch(digest) is None
        or canonical_digest(body) != digest
        or type(value.get("managed_resources")) is not int
        or int(value["managed_resources"]) < 0
        or type(value.get("destructive")) is not bool
    ):
        raise ValueError("github_plan_summary_invalid")
    actions = value.get("action_counts")
    expected_actions = {"create", "update", "delete", "replace", "no_op", "read"}
    if (
        not isinstance(actions, dict)
        or set(actions) != expected_actions
        or any(type(count) is not int or count < 0 for count in actions.values())
        or sum(actions.values()) != value["managed_resources"]
    ):
        raise ValueError("github_plan_summary_invalid")
    resource_types = value.get("resource_type_counts")
    if not isinstance(resource_types, dict) or len(resource_types) > 256:
        raise ValueError("github_plan_summary_invalid")
    for resource_type, counts in resource_types.items():
        if (
            not isinstance(resource_type, str)
            or not resource_type
            or len(resource_type) > 128
            or not isinstance(counts, dict)
            or not set(counts).issubset(expected_actions)
            or any(type(count) is not int or count <= 0 for count in counts.values())
        ):
            raise ValueError("github_plan_summary_invalid")
    return {str(key): item for key, item in value.items()}


def _download_apply_receipt(
    *,
    repository: str,
    workflow_run_id: int,
    request_id_value: str,
    expected_commit: str,
    expected_context_digest: str,
    expected_plan_id: str,
    expected_plan_digest: str,
    run: CommandRunner,
) -> dict[str, object]:
    """Download and validate one application receipt and its profile observation."""

    if (
        _PLAN_ID.fullmatch(expected_plan_id) is None
        or _DIGEST.fullmatch(expected_plan_digest) is None
    ):
        raise ValueError("expected apply plan identity is invalid")
    with tempfile.TemporaryDirectory(prefix="fdai-apply-status-") as raw_directory:
        directory = Path(raw_directory)
        result = run(
            (
                "run",
                "download",
                str(workflow_run_id),
                "--repo",
                repository,
                "--name",
                f"deployment-apply-receipt-{expected_plan_id}",
                "--dir",
                str(directory),
            )
        )
        if result.returncode != 0:
            raise ValueError("github_apply_receipt_unavailable")
        receipt = _private_artifact_json(directory / "apply-receipt.json", "apply receipt")
        cost_governance = request_id_value.startswith("apply-cost-")
        observation_path = directory / (
            "cost-governance-job-image-readback.json"
            if cost_governance
            else "initial-inventory-receipt.json"
        )
        observation_label = (
            "Cost Governance Job image readback"
            if cost_governance
            else "initial inventory execution receipt"
        )
        observation_bytes = _private_artifact_bytes(observation_path, observation_label)
        observation = dict(_json_object(observation_bytes.decode("utf-8"), observation_label))
    expected = {
        "schema_version": "fdai.deployment-apply-receipt.v1",
        "plan_id": expected_plan_id,
        "plan_digest": expected_plan_digest,
        "request_id": request_id_value,
        "context_digest": expected_context_digest,
        "source_commit": expected_commit,
        "status": "applied",
        "terraform_zero_change_verified": True,
        "subscription_ready": False,
    }
    if cost_governance:
        expected["cost_governance_job_images_verified"] = True
    else:
        expected.update(
            {
                "migration_stage_verified": True,
                "runtime_health_verified": True,
                "canary_verified": True,
            }
        )
    receipt_digest = receipt.get("receipt_digest")
    receipt_body = {key: item for key, item in receipt.items() if key != "receipt_digest"}
    if any(receipt.get(key) != item for key, item in expected.items()):
        raise ValueError("github_apply_receipt_context_mismatch")
    if (
        not isinstance(receipt_digest, str)
        or _DIGEST.fullmatch(receipt_digest) is None
        or canonical_digest(receipt_body) != receipt_digest
    ):
        raise ValueError("github_apply_receipt_digest_invalid")
    observation_digest = hashlib.sha256(observation_bytes).hexdigest()
    if cost_governance:
        image_digest = receipt.get("cost_governance_image_digest")
        if (
            receipt.get("cost_governance_job_image_readback_digest") != observation_digest
            or not isinstance(image_digest, str)
            or _OCI_DIGEST.fullmatch(image_digest) is None
        ):
            raise ValueError("github_cost_governance_readback_invalid")
        _validate_cost_governance_readback(observation, expected_digest=image_digest)
        return {
            **expected,
            "cost_governance_image_digest": image_digest,
            "cost_governance_job_image_readback_digest": observation_digest,
        }
    inventory_receipt_digest = observation.get("receipt_digest")
    inventory_body = {key: item for key, item in observation.items() if key != "receipt_digest"}
    if (
        receipt.get("initial_inventory_execution_receipt_digest") != observation_digest
        or observation.get("schema_version")
        != "fdai.genesis-initial-inventory-execution-receipt.v1"
        or observation.get("source_commit") != expected_commit
        or observation.get("status") != "succeeded"
        or observation.get("active_generation_verified") is not False
        or observation.get("subscription_ready") is not False
        or not isinstance(inventory_receipt_digest, str)
        or _DIGEST.fullmatch(inventory_receipt_digest) is None
        or hashlib.sha256(
            json.dumps(inventory_body, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        != inventory_receipt_digest
    ):
        raise ValueError("github_initial_inventory_receipt_invalid")
    return {
        "plan_id": expected_plan_id,
        "plan_digest": expected_plan_digest,
        "request_id": request_id_value,
        "context_digest": expected_context_digest,
        "source_commit": expected_commit,
        "status": "applied",
        "terraform_zero_change_verified": True,
        "migration_stage_verified": True,
        "runtime_health_verified": True,
        "canary_verified": True,
        "initial_inventory_execution_receipt_digest": observation_digest,
        "subscription_ready": False,
    }


def _validate_cost_governance_readback(
    value: Mapping[str, object],
    *,
    expected_digest: str,
) -> None:
    """Reject incomplete or mismatched Cost Governance Job observations."""
    if (
        set(value) != {"schema_version", "image_digest", "jobs"}
        or value.get("schema_version") != "fdai.cost-governance-job-image-readback.v1"
        or value.get("image_digest") != expected_digest
    ):
        raise ValueError("github_cost_governance_readback_invalid")
    jobs = value.get("jobs")
    expected_containers = {
        "analyzer": "cost-governance-analyzer",
        "collector": "cost-governance-collector",
    }
    if not isinstance(jobs, dict) or set(jobs) != set(expected_containers):
        raise ValueError("github_cost_governance_readback_invalid")
    for role, container in expected_containers.items():
        job = jobs[role]
        if (
            not isinstance(job, dict)
            or set(job) != {"container", "image_digest"}
            or job.get("container") != container
            or job.get("image_digest") != expected_digest
        ):
            raise ValueError("github_cost_governance_readback_invalid")


def _private_artifact_json(path: Path, label: str) -> dict[str, object]:
    return dict(_json_object(_private_artifact_bytes(path, label).decode("utf-8"), label))


def _private_artifact_bytes(path: Path, label: str) -> bytes:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        details = os.fstat(stream.fileno())
        if (
            not stat.S_ISREG(details.st_mode)
            or details.st_uid != os.geteuid()
            or details.st_size > 262_144
        ):
            raise ValueError(f"github_{label.replace(' ', '_')}_file_invalid")
        return stream.read(262_145)


def _json_array(raw: str, label: str) -> list[Mapping[str, object]]:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label} response is invalid") from exc
    if not isinstance(payload, list) or not all(isinstance(item, dict) for item in payload):
        raise ValueError(f"{label} response MUST be an array of objects")
    if len(payload) > 50:
        raise ValueError(f"{label} response exceeds the requested bound")
    return payload


def _json_object(raw: str, label: str) -> Mapping[str, object]:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label} response is invalid") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label} response MUST be an object")
    return payload


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
