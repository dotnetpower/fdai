"""Compose shadow-first human report-line approval routing."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from fdai.core.hil_resume.rung_eligibility import DirectoryRungEligibility
from fdai.core.human_reporting import (
    ApprovalContactConsentService,
    ReportingLineService,
    ReportLineApprovalRouter,
    ReportLineRoutingPolicy,
)
from fdai.runtime.approval_policy import approver_authorizer_from_environment
from fdai.shared.providers.state_store import StateStore

_ROUTES_ENV = "FDAI_REPORT_LINE_APPROVAL_ROUTES_JSON"


@dataclass(frozen=True, slots=True)
class CurrentReportLineEligibility:
    """Combine current ordinary role evidence with exact ActionType approval policy."""

    roles: DirectoryRungEligibility
    can_approve: Callable[[str, str], bool]

    async def is_eligible(
        self,
        *,
        subject_ref: str,
        minimum_role: str,
        action_type: str,
        scope_ref: str,
        at: datetime,
    ) -> bool:
        del scope_ref, at
        return await self.roles.is_eligible(
            subject_ref=subject_ref,
            minimum_role=minimum_role,
        ) and self.can_approve(subject_ref, action_type)


@dataclass(frozen=True, slots=True)
class ReportLineRuntime:
    """Bound report-line router and its separate requester-consent service."""

    router: ReportLineApprovalRouter
    consent: ApprovalContactConsentService
    escalation_eligibility: ReportLineAwareRungEligibility


@dataclass(frozen=True, slots=True)
class ReportLineAwareRungEligibility:
    """Revalidate a pinned report-line route before every escalation delivery."""

    base: DirectoryRungEligibility
    router: ReportLineApprovalRouter

    async def is_eligible(
        self,
        *,
        subject_ref: str,
        minimum_role: str,
        context: Mapping[str, Any] | None = None,
        at: datetime | None = None,
    ) -> bool:
        if not await self.base.is_eligible(
            subject_ref=subject_ref,
            minimum_role=minimum_role,
        ):
            return False
        if context is None or not isinstance(context.get("report_line_route"), Mapping):
            return True
        action = context.get("action")
        route = context["report_line_route"]
        requester = context.get("submitter_oid")
        if (
            not isinstance(action, Mapping)
            or not isinstance(requester, str)
            or not requester
            or not isinstance(action.get("action_type"), str)
            or not isinstance(action.get("target_resource_ref"), str)
        ):
            return False
        try:
            current = await self.router.plan(
                requester_ref=requester,
                action_type=str(action["action_type"]),
                scope_ref=str(action["target_resource_ref"]),
                minimum_role=minimum_role,
                at=at or datetime.now(tz=UTC),
            )
        except PermissionError:
            return False
        return (
            current is not None
            and current.digest == route.get("route_digest")
            and current.path_revision == route.get("path_revision")
            and any(rung.subject_ref.casefold() == subject_ref.casefold() for rung in current.rungs)
        )


def build_report_line_runtime(
    *,
    store: StateStore,
    environment: Mapping[str, str],
    role_eligibility: DirectoryRungEligibility | None,
) -> ReportLineRuntime | None:
    """Build routing only for an explicit ActionType allowlist and complete evidence seams."""

    raw = environment.get(_ROUTES_ENV, "").strip()
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{_ROUTES_ENV} MUST be valid JSON") from exc
    if not isinstance(parsed, dict) or not 1 <= len(parsed) <= 128:
        raise ValueError(f"{_ROUTES_ENV} MUST be an object with 1-128 ActionTypes")
    quorum: dict[str, int] = {}
    for action_type, value in parsed.items():
        if (
            not isinstance(action_type, str)
            or not action_type.strip()
            or action_type != action_type.strip()
            or len(action_type) > 256
            or type(value) is not int
            or value != 1
        ):
            raise ValueError(
                f"{_ROUTES_ENV} currently requires exact ActionType keys with quorum 1"
            )
        quorum[action_type] = value
    authorizer = approver_authorizer_from_environment(environment)
    if role_eligibility is None or authorizer is None:
        raise ValueError(
            "report-line routing requires current directory roles and "
            "FDAI_PANTHEON_APPROVER_ACTIONS_JSON"
        )
    policy = ReportLineRoutingPolicy(
        action_types=frozenset(quorum),
        quorum_by_action=quorum,
    )
    router = ReportLineApprovalRouter(
        graphs=ReportingLineService(store),
        eligibility=CurrentReportLineEligibility(role_eligibility, authorizer),
        policy=policy,
    )
    return ReportLineRuntime(
        router=router,
        consent=ApprovalContactConsentService(store),
        escalation_eligibility=ReportLineAwareRungEligibility(
            base=role_eligibility,
            router=router,
        ),
    )


__all__ = [
    "CurrentReportLineEligibility",
    "ReportLineAwareRungEligibility",
    "ReportLineRuntime",
    "build_report_line_runtime",
]
