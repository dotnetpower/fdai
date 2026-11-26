"""Validated immutable values for protected GitHub workflow operations."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from fdai_deployment_cli.contracts import canonical_digest

_REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}$")

_COMMIT = re.compile(r"^[0-9a-f]{40}$")

_DIGEST = re.compile(r"^[0-9a-f]{64}$")

_OCI_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")

_PROVIDER_SOURCE_REVISION = re.compile(r"^[0-9a-f]{40,64}$")

_PLAN_ID = re.compile(r"^plan-[1-9][0-9]*-[1-9][0-9]*$")

_REQUEST_ID = re.compile(
    r"^(?:plan|apply)-(?:cost-|history-|identity-|provider-cost-|provider-|rca-)?"
    r"[0-9a-f]{48}$"
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
            raise ValueError("monitoring-only deployment cannot specify runtime_image_revision")
        if self.runtime_image_revision and _COMMIT.fullmatch(self.runtime_image_revision) is None:
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


def _request_binding_from_id(request_id_value: str) -> str:
    """Return the target/context binding embedded in one validated request id."""

    for prefix in (
        "plan-history-",
        "apply-history-",
        "plan-identity-",
        "apply-identity-",
        "plan-provider-cost-",
        "apply-provider-cost-",
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


def _validate_repository(repository: str) -> None:
    if _REPOSITORY.fullmatch(repository) is None or ".." in repository:
        raise ValueError("repository MUST be owner/name")
