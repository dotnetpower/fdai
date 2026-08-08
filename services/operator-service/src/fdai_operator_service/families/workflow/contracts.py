"""Typed dependency contracts for the Operator workflow route family.

Responsibility: Describe authenticated read requests and inert mutation proposals.
Boundary: HTTP parsing stays in the route factory; storage and transport stay injected.
Authority and state: These contracts grant no execution or promotion authority and own no state.
Dependencies: Neutral Operator DTOs and Python typing primitives only.
Deployment: Process-local contracts inside the independently deployable Operator Service.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from fdai_service_contracts import JsonObject, OperatorPrincipal, OperatorRole
from starlette.requests import Request


class WorkflowOperation(StrEnum):
    """Stable operation identifiers for the legacy workflow HTTP family."""

    RULE_LIST = "rule.list"
    RULE_SEARCH = "rule.search"
    RULE_FINDINGS_SUMMARY = "rule.findings-summary"
    RULE_FINDINGS = "rule.findings"
    RULE_DETAIL = "rule.detail"
    BEST_PRACTICE_LIST = "best-practice.list"
    BEST_PRACTICE_DETAIL = "best-practice.detail"
    MCSB_LIST = "mcsb.list"
    MCSB_DETAIL = "mcsb.detail"
    PROMOTION_GATE_LIST = "promotion-gate.list"
    WORKFLOW_ACTION_TYPE_LIST = "workflow.action-type-list"
    WORKFLOW_VALIDATE = "workflow.validate"
    WORKFLOW_CATALOG = "workflow.catalog"
    WORKFLOW_RUN_REQUEST = "workflow.run-request"
    WORKFLOW_RESUME_REQUEST = "workflow.resume-request"
    WORKFLOW_CANCEL_REQUEST = "workflow.cancel-request"
    WORKFLOW_RETRY_REQUEST = "workflow.retry-request"
    PYTHON_CAPABILITIES = "python-task.capabilities"
    PYTHON_GENERATE = "python-task.generate"
    PYTHON_VALIDATE = "python-task.validate"
    PYTHON_STAGE_PROPOSAL = "python-task.stage-proposal"
    PYTHON_TEST = "python-task.test"
    PYTHON_RUN_PROPOSAL = "python-task.run-proposal"
    PYTHON_SCHEDULE_PROPOSAL = "python-task.schedule-proposal"
    SKILL_SOURCE_BROWSE = "skill-source.browse"
    SKILL_SOURCE_SEARCH = "skill-source.search"
    SKILL_SOURCE_INSPECT = "skill-source.inspect"
    SKILL_SOURCE_CHECK_UPDATE = "skill-source.check-update"
    SKILL_SOURCE_CANDIDATES = "skill-source.candidates"
    SKILL_SOURCE_APPROVAL_PROPOSAL = "skill-source.approval-proposal"
    SKILL_SOURCE_REVOCATION_PROPOSAL = "skill-source.revocation-proposal"
    TRAJECTORY_DATASET_LIST = "trajectory-dataset.list"
    TRAJECTORY_DATASET_DETAIL = "trajectory-dataset.detail"
    WORKFLOW_DEFINITION_LIST = "workflow-definition.list"
    WORKFLOW_DEFINITION_CREATE_PROPOSAL = "workflow-definition.create-proposal"
    WORKFLOW_BINDING_CREATE_PROPOSAL = "workflow-binding.create-proposal"
    WORKFLOW_BINDING_UPDATE_PROPOSAL = "workflow-binding.update-proposal"
    WORKFLOW_BINDING_DELETE_PROPOSAL = "workflow-binding.delete-proposal"


@dataclass(frozen=True, slots=True)
class ProjectionProvenance:
    """Authoritative source identity attached to one read projection."""

    source_ref: str
    revision: str
    synthetic: bool = False

    def __post_init__(self) -> None:
        if not self.source_ref.strip() or not self.revision.strip():
            raise ValueError("projection provenance source_ref and revision MUST be non-empty")
        if self.synthetic:
            raise ValueError("workflow family routes MUST NOT return synthetic projections")


@dataclass(frozen=True, slots=True)
class WorkflowReadRequest:
    """Bounded, authenticated query passed to an authoritative read store."""

    operation: WorkflowOperation
    principal_id: str
    query: Mapping[str, str]
    path_parameters: Mapping[str, str]
    body: JsonObject | None = None
    limit: int | None = None
    offset: int | None = None


@dataclass(frozen=True, slots=True)
class WorkflowReadResult:
    """Store-owned HTTP projection with explicit non-synthetic provenance."""

    payload: JsonObject
    provenance: ProjectionProvenance
    status_code: int = 200

    def __post_init__(self) -> None:
        if self.status_code < 200 or self.status_code > 599:
            raise ValueError("workflow read result status_code MUST be between 200 and 599")


@dataclass(frozen=True, slots=True)
class WorkflowProposal:
    """Inert operator proposal that must re-enter downstream governance gates."""

    operation: WorkflowOperation
    principal_id: str
    idempotency_key: str
    expected_revision: str
    request_source: str
    path_parameters: Mapping[str, str]
    payload: JsonObject
    mode: str = "shadow"

    def __post_init__(self) -> None:
        if not self.idempotency_key.strip() or len(self.idempotency_key) > 200:
            raise ValueError("idempotency_key MUST be a bounded non-empty string")
        if not self.expected_revision.strip() or len(self.expected_revision) > 256:
            raise ValueError("expected_revision MUST be a bounded non-empty string")
        if self.mode != "shadow":
            raise ValueError("Operator workflow proposals MUST remain shadow-first")


@dataclass(frozen=True, slots=True)
class WorkflowProposalReceipt:
    """Durable acceptance receipt returned by an injected proposal writer."""

    proposal_id: str
    revision: str
    duplicate: bool = False

    def __post_init__(self) -> None:
        if not self.proposal_id.strip() or not self.revision.strip():
            raise ValueError("proposal receipt id and revision MUST be non-empty")


class WorkflowReadStore(Protocol):
    """Read authoritative workflow-family projections without fabricating fallback data."""

    async def read(self, request: WorkflowReadRequest) -> WorkflowReadResult: ...


class WorkflowProposalWriter(Protocol):
    """Persist or publish inert proposals without executing or promoting them."""

    async def submit(self, proposal: WorkflowProposal) -> WorkflowProposalReceipt: ...


class WorkflowPrincipalAuthorizer(Protocol):
    """Authenticate a request and enforce one manifest-declared role set."""

    async def __call__(
        self,
        request: Request,
        required_roles: frozenset[OperatorRole],
    ) -> OperatorPrincipal: ...


__all__ = [
    "ProjectionProvenance",
    "WorkflowOperation",
    "WorkflowPrincipalAuthorizer",
    "WorkflowProposal",
    "WorkflowProposalReceipt",
    "WorkflowProposalWriter",
    "WorkflowReadRequest",
    "WorkflowReadResult",
    "WorkflowReadStore",
]
