from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.hil_resume import EscalationDuty
from fdai.core.human_reporting import (
    ApprovalContactConsentService,
    ApprovalContactConsentState,
    ReportingGraphEdge,
    ReportingGraphSnapshot,
    ReportingLineModelError,
    ReportLineApprovalRouter,
    ReportLineRouteUnavailableError,
    ReportLineRoutingPolicy,
)
from fdai.shared.providers.testing import InMemoryStateStore

NOW = datetime(2026, 9, 16, 1, 0, tzinfo=UTC)


class Graphs:
    async def current_graph(self, *, at: datetime | None = None) -> ReportingGraphSnapshot:
        assert at is not None
        return ReportingGraphSnapshot(
            revision="a" * 64,
            observed_at=at,
            edges=(
                ReportingGraphEdge(
                    case_id="case-a",
                    edge_digest="b" * 64,
                    subject_ref="person-a",
                    manager_ref="person-b",
                    effective_from=NOW - timedelta(days=1),
                    effective_until=NOW + timedelta(days=1),
                ),
                ReportingGraphEdge(
                    case_id="case-b",
                    edge_digest="c" * 64,
                    subject_ref="person-b",
                    manager_ref="person-c",
                    effective_from=NOW - timedelta(days=1),
                    effective_until=NOW + timedelta(days=1),
                ),
            ),
        )


class Eligibility:
    def __init__(self, eligible: set[str]) -> None:
        self.eligible = eligible
        self.seen: list[str] = []

    async def is_eligible(
        self,
        *,
        subject_ref: str,
        minimum_role: str,
        action_type: str,
        scope_ref: str,
        at: datetime,
    ) -> bool:
        assert minimum_role == "Approver"
        assert action_type == "ops.restart-service"
        assert scope_ref == "scope://service/example"
        assert at == NOW
        self.seen.append(subject_ref)
        return subject_ref in self.eligible


async def test_router_selects_nearest_eligible_ancestor() -> None:
    eligibility = Eligibility({"person-c"})
    router = ReportLineApprovalRouter(
        graphs=Graphs(),
        eligibility=eligibility,
        policy=ReportLineRoutingPolicy(
            action_types=frozenset({"ops.restart-service"}),
            quorum_by_action={},
        ),
    )

    plan = await router.plan(
        requester_ref="PERSON-A",
        action_type="ops.restart-service",
        scope_ref="scope://service/example",
        minimum_role="Approver",
        at=NOW,
    )

    assert plan is not None
    assert [item.subject_ref for item in plan.rungs] == ["person-c"]
    assert plan.rungs[0].duty is EscalationDuty.PRIMARY
    assert eligibility.seen == ["person-b", "person-c"]


@pytest.mark.parametrize("quorum", [0, 2, 4, True])
def test_policy_rejects_unsupported_quorum(quorum: int) -> None:
    with pytest.raises(ValueError, match="quorum 1"):
        ReportLineRoutingPolicy(
            action_types=frozenset({"ops.restart-service"}),
            quorum_by_action={"ops.restart-service": quorum},
        )


async def test_router_converts_depth_overflow_to_route_unavailable() -> None:
    router = ReportLineApprovalRouter(
        graphs=Graphs(),
        eligibility=Eligibility({"person-b", "person-c"}),
        policy=ReportLineRoutingPolicy(
            action_types=frozenset({"ops.restart-service"}),
            quorum_by_action={},
        ),
        maximum_depth=1,
    )

    with pytest.raises(ReportLineRouteUnavailableError, match="traversal bound"):
        await router.plan(
            requester_ref="person-a",
            action_type="ops.restart-service",
            scope_ref="scope://service/example",
            minimum_role="Approver",
            at=NOW,
        )


async def test_router_leaves_unselected_actions_on_existing_route() -> None:
    router = ReportLineApprovalRouter(
        graphs=Graphs(),
        eligibility=Eligibility(set()),
        policy=ReportLineRoutingPolicy(action_types=frozenset(), quorum_by_action={}),
    )

    assert (
        await router.plan(
            requester_ref="person-a",
            action_type="ops.restart-service",
            scope_ref="scope://service/example",
            minimum_role="Approver",
            at=NOW,
        )
        is None
    )


async def test_contact_consent_is_requester_only_scoped_and_short_lived() -> None:
    service = ApprovalContactConsentService(InMemoryStateStore(), ttl=timedelta(minutes=5))
    pending = await service.request(
        requester_ref="person-a",
        action_digest="a" * 64,
        route_digest="b" * 64,
        graph_revision="c" * 64,
        now=NOW,
    )
    assert pending.state is ApprovalContactConsentState.PENDING

    with pytest.raises(PermissionError, match="only the requester"):
        await service.decide(
            consent_id=pending.consent_id,
            requester_ref="person-b",
            consent=True,
            expected_revision=0,
            now=NOW + timedelta(minutes=1),
        )

    consented = await service.decide(
        consent_id=pending.consent_id,
        requester_ref="PERSON-A",
        consent=True,
        expected_revision=0,
        now=NOW + timedelta(minutes=1),
    )
    assert consented.state is ApprovalContactConsentState.CONSENTED
    assert consented.to_dict()["approval_authority"] is False


async def test_contact_consent_cannot_be_decided_after_expiry() -> None:
    service = ApprovalContactConsentService(InMemoryStateStore(), ttl=timedelta(minutes=5))
    pending = await service.request(
        requester_ref="person-a",
        action_digest="a" * 64,
        route_digest="b" * 64,
        graph_revision="c" * 64,
        now=NOW,
    )

    with pytest.raises(ReportingLineModelError, match="expired"):
        await service.decide(
            consent_id=pending.consent_id,
            requester_ref="person-a",
            consent=True,
            expected_revision=0,
            now=NOW + timedelta(minutes=5),
        )


async def test_contact_consent_exact_replay_returns_the_recorded_choice() -> None:
    service = ApprovalContactConsentService(InMemoryStateStore(), ttl=timedelta(minutes=5))
    pending = await service.request(
        requester_ref="person-a",
        action_digest="a" * 64,
        route_digest="b" * 64,
        graph_revision="c" * 64,
        now=NOW,
    )
    first = await service.decide(
        consent_id=pending.consent_id,
        requester_ref="person-a",
        consent=True,
        expected_revision=0,
        now=NOW + timedelta(minutes=1),
    )

    replay = await service.decide(
        consent_id=pending.consent_id,
        requester_ref="person-a",
        consent=True,
        expected_revision=0,
        now=NOW + timedelta(minutes=2),
    )

    assert replay == first
