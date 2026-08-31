"""Bounded GitHub Actions transport for protected FDAI deployment workflows."""

from __future__ import annotations

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
_PLAN_ID = re.compile(r"^plan-[1-9][0-9]*-[1-9][0-9]*$")
_REQUEST_ID = re.compile(r"^(?:plan|apply)-[0-9a-f]{48}$")
_ENVIRONMENTS = frozenset({"dev", "staging", "prod"})
_BOOL_INPUTS = (
    "deploy_console",
    "deploy_operator_api",
    "deploy_document_ingestion",
    "deploy_isolated_executor",
    "deploy_monitoring",
)
_EXPIRES_AT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

# Artifact downloads are larger than metadata queries; use a longer timeout.
_ARTIFACT_DOWNLOAD_TIMEOUT = 90
_DEFAULT_GH_TIMEOUT = 30


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
    deploy_operator_api: bool = True
    deploy_document_ingestion: bool = False
    deploy_isolated_executor: bool = False
    deploy_monitoring: bool = False

    def __post_init__(self) -> None:
        if self.deploy_monitoring and any(
            (
                self.deploy_console,
                self.deploy_operator_api,
                self.deploy_document_ingestion,
                self.deploy_isolated_executor,
            )
        ):
            raise ValueError("monitoring deployment cannot be combined with application targets")

    def to_mapping(self) -> dict[str, bool]:
        """Return workflow input names in stable order."""

        return {name: bool(getattr(self, name)) for name in _BOOL_INPUTS}


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
    verify_environment_quorum(
        repository=repository,
        environment=environment,
        required_quorum=approval_quorum,
        run=runner,
    )
    bounded_request_id = request_id(
        "resume" if resume_verification else "apply",
        run_id=run_id,
        context_digest=context_digest,
        target_binding=target_binding,
        region=region,
        attempt=attempt,
    )
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
    if request_id_value.split("-", maxsplit=1)[1][:24] != expected_binding:
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
    return projected


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


def verify_environment_quorum(
    *,
    repository: str,
    environment: str,
    required_quorum: int,
    run: CommandRunner | None = None,
) -> None:
    """Require the protected apply environment to meet the profile approval quorum."""

    _validate_repository(repository)
    if environment not in _ENVIRONMENTS:
        raise ValueError("environment is unsupported")
    if required_quorum < 1:
        raise ValueError("required approval quorum MUST be positive")
    if required_quorum != 1:
        raise ValueError("github-actions transport supports exactly one required approval")
    result = (run or run_github_cli)(
        (
            "api",
            f"repos/{repository}/environments/{environment}",
            "--method",
            "GET",
        )
    )
    if result.returncode != 0:
        raise ValueError("github_environment_protection_unavailable")
    payload = _json_object(result.stdout, "GitHub environment")
    if payload.get("can_admins_bypass") is not False:
        raise ValueError("github_environment_admin_bypass_enabled")
    rules = payload.get("protection_rules")
    if not isinstance(rules, list):
        raise ValueError("github_environment_protection_invalid")
    reviewer_rules = [
        rule
        for rule in rules
        if isinstance(rule, dict) and rule.get("type") == "required_reviewers"
    ]
    if len(reviewer_rules) != 1:
        raise ValueError("github_environment_required_reviewers_missing")
    rule = reviewer_rules[0]
    reviewers = rule.get("reviewers")
    if not isinstance(reviewers, list) or any(not isinstance(item, dict) for item in reviewers):
        raise ValueError("github_environment_required_reviewers_invalid")
    reviewer_ids = {
        str(item.get("reviewer", {}).get("id"))
        for item in reviewers
        if isinstance(item.get("reviewer"), dict) and item["reviewer"].get("id") is not None
    }
    if not reviewer_ids:
        raise ValueError("github_environment_required_reviewers_missing")
    if rule.get("prevent_self_review") is not True:
        raise ValueError("github_environment_self_review_not_blocked")


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
        "resume_verification": str(resume_verification).lower(),
        "request_id": request_id_value,
        "context_digest": context_digest,
        "commit_sha": commit_sha,
        **{key: str(value).lower() for key, value in selection.to_mapping().items()},
    }
    if apply:
        if plan_id is None or plan_digest is None:
            raise ValueError("exact apply requires plan id and digest")
        fields["plan_id"] = plan_id
        fields["plan_digest"] = plan_digest
    arguments = [
        "workflow",
        "run",
        "deploy-dev.yml",
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
    return {
        "plan_id": plan_id,
        "plan_digest": plan_digest,
        "context_digest": context_digest,
        "expires_at": expires_at,
        "status": "ready",
    }


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
    "verify_environment_quorum",
    "workflow_status",
]
