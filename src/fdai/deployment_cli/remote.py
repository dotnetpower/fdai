"""Remote deployment plan records and exact-plan submission guard."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID

_DIGEST = re.compile(r"^[a-f0-9]{64}$")
_COMMIT = re.compile(r"^[a-f0-9]{40}$")


class PlanStatus(StrEnum):
    PLANNING = "planning"
    READY = "ready"
    APPLYING = "applying"
    APPLIED = "applied"
    FAILED = "failed"
    EXPIRED = "expired"


@dataclass(frozen=True, slots=True)
class DeploymentPlanContext:
    """Non-secret context that binds a plan to one immutable deployment target."""

    tenant_id: UUID
    subscription_id: UUID
    environment: str
    bundle_digest: str
    commit_sha: str
    backend_ref: str
    runner_ref: str
    deploy_console: bool = False
    deploy_read_api: bool = False
    deploy_dev_operations_gateway: bool = False
    deploy_document_ingestion: bool = False

    def __post_init__(self) -> None:
        if self.environment not in {"dev", "staging", "prod"}:
            raise ValueError("deployment environment is invalid")
        if _DIGEST.fullmatch(self.bundle_digest) is None:
            raise ValueError("bundle_digest MUST be a lowercase SHA-256 digest")
        if _COMMIT.fullmatch(self.commit_sha) is None:
            raise ValueError("commit_sha MUST be a lowercase 40-character git SHA")
        if not self.backend_ref or not self.runner_ref:
            raise ValueError("backend_ref and runner_ref MUST be non-empty")
        if self.deploy_dev_operations_gateway and self.environment != "dev":
            raise ValueError("the development operations gateway is dev-only")


@dataclass(frozen=True, slots=True)
class DeploymentPlanRecord:
    """Opaque workflow-owned plan metadata; never contains the binary plan."""

    plan_id: str
    plan_digest: str
    context: DeploymentPlanContext | None
    created_at: datetime
    expires_at: datetime
    status: PlanStatus
    workflow_url: str
    context_digest: str | None = None
    preflight_blocks: bool = False
    runner_available: bool = True

    def __post_init__(self) -> None:
        if not self.plan_id or not self.workflow_url:
            raise ValueError("plan_id and workflow_url MUST be non-empty")
        if _DIGEST.fullmatch(self.plan_digest) is None:
            raise ValueError("plan_digest MUST be a lowercase SHA-256 digest")
        if self.context is None and self.context_digest is None:
            raise ValueError("plan record MUST include context or context_digest")
        if self.context_digest is not None and _DIGEST.fullmatch(self.context_digest) is None:
            raise ValueError("context_digest MUST be a lowercase SHA-256 digest")
        if (
            self.context is not None
            and self.context_digest is not None
            and deployment_context_digest(self.context) != self.context_digest
        ):
            raise ValueError("context and context_digest MUST match")
        if self.expires_at <= self.created_at:
            raise ValueError("plan expiry MUST be after creation")


@dataclass(frozen=True, slots=True)
class DeploymentSubmission:
    submission_id: str
    workflow_url: str


class DeploymentWorkflowTransport(Protocol):
    """Approved runner workflow API; concrete credentials stay in delivery code."""

    async def submit_plan(self, context: DeploymentPlanContext) -> DeploymentSubmission: ...

    async def get_plan(self, plan_id: str) -> DeploymentPlanRecord: ...

    async def submit_apply(
        self,
        *,
        plan_id: str,
        plan_digest: str,
        context: DeploymentPlanContext,
    ) -> DeploymentSubmission: ...


class RemoteDeploymentError(RuntimeError):
    """Remote deployment submission failed a local integrity guard."""


class RemoteDeploymentService:
    """Submit plan-only work and guarded exact-plan apply to the approved runner."""

    def __init__(self, *, transport: DeploymentWorkflowTransport) -> None:
        self._transport = transport

    async def submit_plan(self, context: DeploymentPlanContext) -> DeploymentSubmission:
        return await self._transport.submit_plan(context)

    async def submit_apply(
        self,
        *,
        plan_id: str,
        expected_context: DeploymentPlanContext,
        now: datetime,
    ) -> DeploymentSubmission:
        record = await self._transport.get_plan(plan_id)
        validate_exact_plan(record, expected_context=expected_context, now=now)
        return await self._transport.submit_apply(
            plan_id=record.plan_id,
            plan_digest=record.plan_digest,
            context=expected_context,
        )


def deployment_context_digest(context: DeploymentPlanContext) -> str:
    """Return a stable digest without serializing target identifiers to a transport."""
    payload = {
        "backend_ref": context.backend_ref,
        "bundle_digest": context.bundle_digest,
        "commit_sha": context.commit_sha,
        "deploy_console": context.deploy_console,
        "deploy_dev_operations_gateway": context.deploy_dev_operations_gateway,
        "deploy_document_ingestion": context.deploy_document_ingestion,
        "deploy_read_api": context.deploy_read_api,
        "environment": context.environment,
        "runner_ref": context.runner_ref,
        "subscription_id": str(context.subscription_id),
        "tenant_id": str(context.tenant_id),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def validate_exact_plan(
    record: DeploymentPlanRecord,
    *,
    expected_context: DeploymentPlanContext,
    now: datetime,
) -> None:
    """Block apply unless the stored ready plan exactly matches current intent."""
    if record.status is not PlanStatus.READY:
        raise RemoteDeploymentError(f"plan is not ready for apply (status={record.status.value})")
    if now >= record.expires_at:
        raise RemoteDeploymentError("plan has expired")
    expected_digest = deployment_context_digest(expected_context)
    stored_digest = (
        record.context_digest
        if record.context_digest is not None
        else deployment_context_digest(record.context)
        if record.context is not None
        else ""
    )
    if stored_digest != expected_digest:
        raise RemoteDeploymentError("plan context does not match the requested deployment")
    if record.context is not None and record.context != expected_context:
        raise RemoteDeploymentError("plan context does not match the requested deployment")
    if record.preflight_blocks:
        raise RemoteDeploymentError("plan is blocked by enforced deployment preflight")
    if not record.runner_available:
        raise RemoteDeploymentError("approved deployment runner is unavailable")


__all__ = [
    "DeploymentPlanContext",
    "DeploymentPlanRecord",
    "DeploymentSubmission",
    "DeploymentWorkflowTransport",
    "PlanStatus",
    "RemoteDeploymentError",
    "RemoteDeploymentService",
    "deployment_context_digest",
    "validate_exact_plan",
]
