from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fdai.core.hil_resume.rung_eligibility import DirectoryRungEligibility
from fdai.runtime.approval_policy import (
    approver_authorizer_from_environment,
    report_line_scope_authorizer_from_environment,
)
from fdai.runtime.report_lines import build_report_line_runtime
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
