"""Exact HTTP manifest for the extracted Operator workflow route family."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from fdai_operator_service.families.workflow.contracts import WorkflowOperation
from fdai_service_contracts import OperatorRole

READER_ROLES = frozenset(
    {
        OperatorRole.READER,
        OperatorRole.CONTRIBUTOR,
        OperatorRole.APPROVER,
        OperatorRole.OWNER,
    }
)
CONTRIBUTOR_ROLES = frozenset({OperatorRole.CONTRIBUTOR, OperatorRole.APPROVER, OperatorRole.OWNER})
APPROVER_ROLES = frozenset({OperatorRole.APPROVER, OperatorRole.OWNER})
OWNER_ROLES = frozenset({OperatorRole.OWNER})


@dataclass(frozen=True, slots=True)
class PaginationSpec:
    """Legacy offset pagination limits for one route."""

    default_limit: int
    maximum_limit: int
    supports_offset: bool = True


@dataclass(frozen=True, slots=True)
class WorkflowRouteSpec:
    """Frozen method, path, name, RBAC, parsing, and dispatch contract."""

    method: Literal["GET", "POST", "PUT", "DELETE"]
    path: str
    name: str
    operation: WorkflowOperation
    dispatch: Literal["read", "proposal"]
    required_roles: frozenset[OperatorRole] = READER_ROLES
    maximum_body_bytes: int = 0
    pagination: PaginationSpec | None = None


WORKFLOW_FAMILY_ROUTE_MANIFEST: tuple[WorkflowRouteSpec, ...] = (
    WorkflowRouteSpec(
        "GET",
        "/rules",
        "list_handler",
        WorkflowOperation.RULE_LIST,
        "read",
        pagination=PaginationSpec(100, 500),
    ),
    WorkflowRouteSpec(
        "POST",
        "/rules/search",
        "search_handler",
        WorkflowOperation.RULE_SEARCH,
        "read",
        maximum_body_bytes=32_768,
    ),
    WorkflowRouteSpec(
        "GET",
        "/rules/findings-summary",
        "summary_handler",
        WorkflowOperation.RULE_FINDINGS_SUMMARY,
        "read",
    ),
    WorkflowRouteSpec(
        "GET",
        "/rules/{rule_id}/findings",
        "findings_handler",
        WorkflowOperation.RULE_FINDINGS,
        "read",
    ),
    WorkflowRouteSpec(
        "GET",
        "/rules/{rule_id}",
        "detail_handler",
        WorkflowOperation.RULE_DETAIL,
        "read",
    ),
    WorkflowRouteSpec(
        "GET",
        "/best-practices",
        "list_handler",
        WorkflowOperation.BEST_PRACTICE_LIST,
        "read",
        pagination=PaginationSpec(100, 200),
    ),
    WorkflowRouteSpec(
        "GET",
        "/best-practices/{best_practice_id}",
        "detail_handler",
        WorkflowOperation.BEST_PRACTICE_DETAIL,
        "read",
    ),
    WorkflowRouteSpec(
        "GET",
        "/mcsb-controls",
        "list_handler",
        WorkflowOperation.MCSB_LIST,
        "read",
        pagination=PaginationSpec(100, 200),
    ),
    WorkflowRouteSpec(
        "GET",
        "/mcsb-controls/{benchmark_version}/{control_id}",
        "detail_handler",
        WorkflowOperation.MCSB_DETAIL,
        "read",
    ),
    WorkflowRouteSpec(
        "GET",
        "/kpi/promotion-gates",
        "handler",
        WorkflowOperation.PROMOTION_GATE_LIST,
        "read",
    ),
    WorkflowRouteSpec(
        "GET",
        "/context-selection-comparisons",
        "handler",
        WorkflowOperation.CONTEXT_SELECTION_COMPARISON_LIST,
        "read",
        pagination=PaginationSpec(100, 500, supports_offset=False),
    ),
    WorkflowRouteSpec(
        "GET",
        "/workflows/action-types",
        "handler",
        WorkflowOperation.WORKFLOW_ACTION_TYPE_LIST,
        "read",
    ),
    WorkflowRouteSpec(
        "POST",
        "/workflows/validate",
        "handler",
        WorkflowOperation.WORKFLOW_VALIDATE,
        "read",
        maximum_body_bytes=262_144,
    ),
    WorkflowRouteSpec(
        "GET",
        "/workflows/catalog",
        "handler",
        WorkflowOperation.WORKFLOW_CATALOG,
        "read",
    ),
    WorkflowRouteSpec(
        "POST",
        "/workflows/run",
        "handler",
        WorkflowOperation.WORKFLOW_RUN_REQUEST,
        "proposal",
        required_roles=CONTRIBUTOR_ROLES,
        maximum_body_bytes=32_000,
    ),
    WorkflowRouteSpec(
        "POST",
        "/workflows/{process_id}/resume",
        "handler",
        WorkflowOperation.WORKFLOW_RESUME_REQUEST,
        "proposal",
        required_roles=CONTRIBUTOR_ROLES,
    ),
    WorkflowRouteSpec(
        "POST",
        "/workflows/{process_id}/cancel",
        "handler",
        WorkflowOperation.WORKFLOW_CANCEL_REQUEST,
        "proposal",
        required_roles=CONTRIBUTOR_ROLES,
    ),
    WorkflowRouteSpec(
        "POST",
        "/workflows/{process_id}/retry",
        "handler",
        WorkflowOperation.WORKFLOW_RETRY_REQUEST,
        "proposal",
        required_roles=CONTRIBUTOR_ROLES,
    ),
    WorkflowRouteSpec(
        "GET",
        "/python-tasks/capabilities",
        "capabilities",
        WorkflowOperation.PYTHON_CAPABILITIES,
        "read",
    ),
    WorkflowRouteSpec(
        "POST",
        "/python-tasks/generate",
        "generate_task",
        WorkflowOperation.PYTHON_GENERATE,
        "read",
        required_roles=CONTRIBUTOR_ROLES,
        maximum_body_bytes=600_000,
    ),
    WorkflowRouteSpec(
        "POST",
        "/python-tasks/validate",
        "validate_task",
        WorkflowOperation.PYTHON_VALIDATE,
        "read",
        maximum_body_bytes=600_000,
    ),
    WorkflowRouteSpec(
        "POST",
        "/python-tasks/stage",
        "stage_task",
        WorkflowOperation.PYTHON_STAGE_PROPOSAL,
        "proposal",
        required_roles=CONTRIBUTOR_ROLES,
        maximum_body_bytes=600_000,
    ),
    WorkflowRouteSpec(
        "POST",
        "/python-tasks/test",
        "test_task",
        WorkflowOperation.PYTHON_TEST,
        "read",
        required_roles=CONTRIBUTOR_ROLES,
        maximum_body_bytes=600_000,
    ),
    WorkflowRouteSpec(
        "POST",
        "/python-tasks/request-run",
        "request_run",
        WorkflowOperation.PYTHON_RUN_PROPOSAL,
        "proposal",
        required_roles=CONTRIBUTOR_ROLES,
        maximum_body_bytes=600_000,
    ),
    WorkflowRouteSpec(
        "POST",
        "/python-tasks/schedule",
        "create_schedule",
        WorkflowOperation.PYTHON_SCHEDULE_PROPOSAL,
        "proposal",
        required_roles=CONTRIBUTOR_ROLES,
        maximum_body_bytes=600_000,
    ),
    WorkflowRouteSpec(
        "GET",
        "/api/v1/skill-sources/browse",
        "browse",
        WorkflowOperation.SKILL_SOURCE_BROWSE,
        "read",
    ),
    WorkflowRouteSpec(
        "GET",
        "/api/v1/skill-sources/search",
        "search",
        WorkflowOperation.SKILL_SOURCE_SEARCH,
        "read",
    ),
    WorkflowRouteSpec(
        "GET",
        "/api/v1/skill-sources/{source_id:str}/inspect",
        "inspect",
        WorkflowOperation.SKILL_SOURCE_INSPECT,
        "read",
    ),
    WorkflowRouteSpec(
        "GET",
        "/api/v1/skill-sources/{source_id:str}/check-update",
        "check_update",
        WorkflowOperation.SKILL_SOURCE_CHECK_UPDATE,
        "read",
    ),
    WorkflowRouteSpec(
        "GET",
        "/api/v1/skill-sources/{source_id:str}/candidates",
        "candidates",
        WorkflowOperation.SKILL_SOURCE_CANDIDATES,
        "read",
    ),
    WorkflowRouteSpec(
        "POST",
        "/api/v1/skill-sources/{source_id:str}/approve-candidate",
        "approve",
        WorkflowOperation.SKILL_SOURCE_APPROVAL_PROPOSAL,
        "proposal",
        required_roles=APPROVER_ROLES,
        maximum_body_bytes=4_096,
    ),
    WorkflowRouteSpec(
        "POST",
        "/api/v1/skill-sources/{source_id:str}/revoke",
        "revoke",
        WorkflowOperation.SKILL_SOURCE_REVOCATION_PROPOSAL,
        "proposal",
        required_roles=OWNER_ROLES,
        maximum_body_bytes=4_096,
    ),
    WorkflowRouteSpec(
        "GET",
        "/admin/trajectory-datasets",
        "list_datasets",
        WorkflowOperation.TRAJECTORY_DATASET_LIST,
        "read",
        required_roles=OWNER_ROLES,
        pagination=PaginationSpec(100, 100, supports_offset=False),
    ),
    WorkflowRouteSpec(
        "GET",
        "/admin/trajectory-datasets/{dataset_id}",
        "get_dataset",
        WorkflowOperation.TRAJECTORY_DATASET_DETAIL,
        "read",
        required_roles=OWNER_ROLES,
    ),
    WorkflowRouteSpec(
        "GET",
        "/workflows/definitions",
        "catalog",
        WorkflowOperation.WORKFLOW_DEFINITION_LIST,
        "read",
    ),
    WorkflowRouteSpec(
        "POST",
        "/workflows/definitions",
        "create_definition",
        WorkflowOperation.WORKFLOW_DEFINITION_CREATE_PROPOSAL,
        "proposal",
        maximum_body_bytes=262_144,
    ),
    WorkflowRouteSpec(
        "POST",
        "/workflows/bindings",
        "create_binding",
        WorkflowOperation.WORKFLOW_BINDING_CREATE_PROPOSAL,
        "proposal",
        maximum_body_bytes=262_144,
    ),
    WorkflowRouteSpec(
        "PUT",
        "/workflows/bindings/{binding_id:str}",
        "update_binding",
        WorkflowOperation.WORKFLOW_BINDING_UPDATE_PROPOSAL,
        "proposal",
        maximum_body_bytes=262_144,
    ),
    WorkflowRouteSpec(
        "DELETE",
        "/workflows/bindings/{binding_id:str}",
        "delete_binding",
        WorkflowOperation.WORKFLOW_BINDING_DELETE_PROPOSAL,
        "proposal",
    ),
)


__all__ = [
    "APPROVER_ROLES",
    "CONTRIBUTOR_ROLES",
    "OWNER_ROLES",
    "PaginationSpec",
    "READER_ROLES",
    "WORKFLOW_FAMILY_ROUTE_MANIFEST",
    "WorkflowRouteSpec",
]
