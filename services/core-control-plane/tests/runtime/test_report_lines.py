from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fdai.core.hil_resume.rung_eligibility import DirectoryRungEligibility
from fdai.core.human_reporting import (
    ReportingGraphEdge,
    ReportingGraphSnapshot,
    ReportLineApprovalRouter,
    ReportLineRoutingPolicy,
)
from fdai.runtime.approval_policy import (
    approver_authorizer_from_environment,
    report_line_scope_authorizer_from_environment,
)
from fdai.runtime.report_lines import (
    CurrentReportLineEligibility,
    ReportLineAwareRungEligibility,
    build_report_line_runtime,
)
from fdai.shared.providers.human_identity import (
    HumanIdentity,
    IdentityRosterEntry,
    StaticHumanIdentityDirectory,
)
from fdai.shared.providers.testing import InMemoryStateStore


class Directory:
    async def get_by_subject_id(self, subject_id: str):
        del subject_id
        return None

    async def list_role_roster(self, role_group_ids, *, limit):
        del role_group_ids, limit
        return ()


ROUTES = {"FDAI_REPORT_LINE_APPROVAL_ROUTES_JSON": '{"ops.restart-service":1}'}
APPROVERS = {"FDAI_PANTHEON_APPROVER_ACTIONS_JSON": '{"person-a":["ops.restart-service"]}'}
SCOPES = {
    "FDAI_REPORT_LINE_APPROVER_SCOPES_JSON": (
        '{"person-a":{"ops.restart-service":["scope://service/example"]}}'
    )
}


class Graphs:
    def __init__(self) -> None:
        self.edge_digest = "a" * 64

    async def current_graph(self, *, at=None):
        assert at is not None
        return ReportingGraphSnapshot(
            revision="b" * 64,
            observed_at=at,
            edges=(
                ReportingGraphEdge(
                    case_id="case-a",
                    edge_digest=self.edge_digest,
                    subject_ref="person-a",
                    manager_ref="person-b",
                    effective_from=datetime(2020, 1, 1, tzinfo=UTC),
                    effective_until=datetime(2100, 1, 1, tzinfo=UTC),
                ),
            ),
        )


def test_approver_policy_is_exact_and_case_normalized() -> None:
    authorizer = approver_authorizer_from_environment(
        {"FDAI_PANTHEON_APPROVER_ACTIONS_JSON": ('{"Person-A":["ops.restart-service"]}')}
    )

    assert authorizer is not None
    assert authorizer("person-a", "ops.restart-service") is True
    assert authorizer("person-a", "ops.other") is False


def test_report_line_scope_policy_is_exact() -> None:
    authorizer = report_line_scope_authorizer_from_environment(SCOPES)

    assert authorizer is not None
    assert authorizer("PERSON-A", "ops.restart-service", "scope://service/example")
    assert not authorizer("person-a", "ops.restart-service", "scope://service/other")
    assert not authorizer("person-a", "ops.other", "scope://service/example")


def test_report_line_runtime_is_disabled_without_selected_actions() -> None:
    assert (
        build_report_line_runtime(
            store=InMemoryStateStore(),
            environment={},
            role_eligibility=None,
        )
        is None
    )


def test_report_line_runtime_requires_role_and_action_policy_sources() -> None:
    with pytest.raises(ValueError, match="requires current directory"):
        build_report_line_runtime(
            store=InMemoryStateStore(),
            environment=ROUTES,
            role_eligibility=None,
        )


@pytest.mark.parametrize("quorum", [0, 2, True, "1"])
def test_report_line_runtime_rejects_unsupported_quorum(quorum: object) -> None:
    with pytest.raises(ValueError, match="quorum 1"):
        build_report_line_runtime(
            store=InMemoryStateStore(),
            environment={
                **APPROVERS,
                **SCOPES,
                "FDAI_REPORT_LINE_APPROVAL_ROUTES_JSON": (
                    '{"ops.restart-service":' + str(quorum).lower() + "}"
                    if not isinstance(quorum, str)
                    else '{"ops.restart-service":"1"}'
                ),
            },
            role_eligibility=DirectoryRungEligibility(
                directory=Directory(),
                role_group_ids={"Approver": "group-a", "Owner": "group-b"},
            ),
        )


def test_report_line_runtime_binds_shadow_first_services() -> None:
    runtime = build_report_line_runtime(
        store=InMemoryStateStore(),
        environment={
            **ROUTES,
            **APPROVERS,
            **SCOPES,
        },
        role_eligibility=DirectoryRungEligibility(
            directory=Directory(),
            role_group_ids={"Approver": "group-a", "Owner": "group-b"},
        ),
    )

    assert runtime is not None
    assert runtime.router.policy.selects("ops.restart-service") is True
    assert runtime.consent.ttl.total_seconds() == 300
    assert datetime.now(tz=UTC).tzinfo is UTC


def test_report_line_runtime_requires_explicit_scope_policy() -> None:
    with pytest.raises(ValueError, match="APPROVER_SCOPES"):
        build_report_line_runtime(
            store=InMemoryStateStore(),
            environment={**ROUTES, **APPROVERS},
            role_eligibility=DirectoryRungEligibility(
                directory=Directory(),
                role_group_ids={"Approver": "group-a", "Owner": "group-b"},
            ),
        )


async def test_escalation_eligibility_revalidates_path_role_action_and_scope() -> None:
    directory = StaticHumanIdentityDirectory(
        identities=(
            HumanIdentity(
                provider="entra",
                subject_id="person-b",
                username="person-b@example.com",
                display_name="Person B",
            ),
        ),
        roster=(
            IdentityRosterEntry(
                provider="entra",
                subject_id="person-b",
                display_name="Person B",
                principal_type="person",
                roles=("Approver",),
            ),
        ),
    )
    base = DirectoryRungEligibility(
        directory=directory,
        role_group_ids={"Approver": "group-a", "Owner": "group-b"},
    )
    graphs = Graphs()
    router = ReportLineApprovalRouter(
        graphs=graphs,
        eligibility=CurrentReportLineEligibility(
            base,
            lambda principal, action: principal == "person-b" and action == "ops.restart-service",
            lambda principal, action, scope: (
                principal == "person-b"
                and action == "ops.restart-service"
                and scope == "scope://service/example"
            ),
        ),
        policy=ReportLineRoutingPolicy(
            action_types=frozenset({"ops.restart-service"}),
            quorum_by_action={"ops.restart-service": 1},
        ),
    )
    plan = await router.plan(
        requester_ref="person-a",
        action_type="ops.restart-service",
        scope_ref="scope://service/example",
        minimum_role="Approver",
        at=datetime(2026, 9, 16, tzinfo=UTC),
    )
    assert plan is not None
    eligibility = ReportLineAwareRungEligibility(base=base, router=router)
    context = {
        "submitter_oid": "person-a",
        "action": {
            "action_type": "ops.restart-service",
            "target_resource_ref": "scope://service/example",
        },
        "report_line_route": plan.to_dict(),
    }

    assert await eligibility.is_eligible(
        subject_ref="person-b",
        minimum_role="Approver",
        context=context,
        at=datetime(2026, 9, 16, tzinfo=UTC),
    )
    assert not await eligibility.is_eligible(
        subject_ref="person-b",
        minimum_role="Approver",
        context={**context, "action": {}},
        at=datetime(2026, 9, 16, tzinfo=UTC),
    )
    graphs.edge_digest = "c" * 64
    assert not await eligibility.is_eligible(
        subject_ref="person-b",
        minimum_role="Approver",
        context=context,
        at=datetime(2026, 9, 16, tzinfo=UTC),
    )
