from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

import pytest

from fdai.core.rbac.access_request import (
    AccessOperation,
    AccessRequestConflictError,
    AccessRequestError,
    AccessRequestPermissionError,
    AccessRequestService,
    AccessReviewDecision,
)
from fdai.core.rbac.resolver import Principal
from fdai.core.rbac.roles import Role
from fdai.shared.providers.testing.state_store import InMemoryStateStore


class FailingAtomicStore(InMemoryStateStore):
    async def write_state_with_audit_if_absent(
        self,
        key: str,
        value: Mapping[str, Any],
        audit_entry: Mapping[str, Any],
    ) -> bool:
        del key, value, audit_entry
        raise RuntimeError("audit unavailable")


@pytest.fixture
def store() -> InMemoryStateStore:
    return InMemoryStateStore()


@pytest.fixture
def service(store: InMemoryStateStore) -> AccessRequestService:
    return AccessRequestService(store=store)


def principal(oid: str, role: Role) -> Principal:
    return Principal(oid=oid, roles=frozenset({role}))


async def submit(
    service: AccessRequestService,
    *,
    actor: Principal | None = None,
    idempotency_key: str = "request-1",
    role: Role = Role.READER,
    justification: str = "Required for the on-call support rotation.",
):
    return await service.submit(
        principal=actor or principal("requester-1", Role.CONTRIBUTOR),
        idempotency_key=idempotency_key,
        identity_provider="entra",
        target_subject_id="target-1",
        target_username="user@example.com",
        operation=AccessOperation.GRANT,
        role=role,
        justification=justification,
        now=datetime(2026, 7, 16, tzinfo=UTC),
    )


async def test_submit_is_idempotent_and_audited_once(
    service: AccessRequestService,
    store: InMemoryStateStore,
) -> None:
    first = await submit(service)
    second = await submit(service)

    assert second == first
    entries = tuple(store.audit_entries)
    assert len(entries) == 1
    assert entries[0]["entry"]["action_kind"] == "iam.access-requested"
    assert store.verify_chain()


async def test_submit_does_not_leave_state_when_atomic_audit_fails() -> None:
    store = FailingAtomicStore()
    service = AccessRequestService(store=store)

    with pytest.raises(RuntimeError, match="audit unavailable"):
        await submit(service)

    assert await store.read_states("rbac:access-request:", limit=10) == ()
    assert tuple(store.audit_entries) == ()


async def test_reused_idempotency_key_with_different_intent_is_rejected(
    service: AccessRequestService,
) -> None:
    await submit(service)

    with pytest.raises(AccessRequestConflictError, match="payload conflict"):
        await submit(service, role=Role.OWNER)


async def test_reader_and_break_glass_requests_are_rejected(
    service: AccessRequestService,
) -> None:
    with pytest.raises(AccessRequestPermissionError, match="author-draft-pr"):
        await submit(service, actor=principal("reader-1", Role.READER))
    with pytest.raises(AccessRequestError, match="BreakGlass"):
        await submit(service, role=Role.BREAK_GLASS)


async def test_unassigned_principal_can_only_request_reader_for_self(
    service: AccessRequestService,
) -> None:
    unassigned = Principal(oid="target-1")
    created = await service.submit(
        principal=unassigned,
        idempotency_key="first-login-1",
        identity_provider="entra",
        target_subject_id="target-1",
        target_username="user@example.com",
        operation=AccessOperation.GRANT,
        role=Role.READER,
        justification="Initial console access request.",
        self_service=True,
        now=datetime(2026, 7, 16, tzinfo=UTC),
    )
    assert created.requester_oid == "target-1"
    assert created.role is Role.READER

    for target_subject_id, operation, role in (
        ("other-user", AccessOperation.GRANT, Role.READER),
        ("target-1", AccessOperation.GRANT, Role.CONTRIBUTOR),
        ("target-1", AccessOperation.REVOKE, Role.READER),
    ):
        with pytest.raises(AccessRequestPermissionError):
            await service.submit(
                principal=unassigned,
                idempotency_key=(f"blocked-{target_subject_id}-{operation.value}-{role.value}"),
                identity_provider="entra",
                target_subject_id=target_subject_id,
                target_username="user@example.com",
                operation=operation,
                role=role,
                justification="Initial console access request.",
                self_service=True,
                now=datetime(2026, 7, 16, tzinfo=UTC),
            )


async def test_short_justification_is_rejected(service: AccessRequestService) -> None:
    with pytest.raises(AccessRequestError, match="at least 20"):
        await submit(service, justification="too short")


async def test_owner_can_request_an_exclusive_role_set(
    service: AccessRequestService,
) -> None:
    created = await service.submit(
        principal=principal("owner-1", Role.OWNER),
        idempotency_key="set-role-1",
        identity_provider="entra",
        target_subject_id="target-1",
        target_username="user@example.com",
        operation=AccessOperation.SET,
        role=Role.APPROVER,
        justification="Owner requested Approver role for Example User.",
        now=datetime(2026, 7, 16, tzinfo=UTC),
    )

    assert created.operation is AccessOperation.SET
    assert created.role is Role.APPROVER


async def test_owner_sees_all_requests_but_contributor_sees_only_own(
    service: AccessRequestService,
) -> None:
    await submit(service, actor=principal("requester-1", Role.CONTRIBUTOR))
    await submit(
        service,
        actor=principal("requester-2", Role.CONTRIBUTOR),
        idempotency_key="request-2",
    )

    owner_items = await service.list_requests(
        principal=principal("owner-1", Role.OWNER),
    )
    contributor_items = await service.list_requests(
        principal=principal("requester-1", Role.CONTRIBUTOR),
    )

    assert {item.requester_oid for item in owner_items} == {"requester-1", "requester-2"}
    assert [item.requester_oid for item in contributor_items] == ["requester-1"]


async def test_owner_reviews_request_and_requester_cannot_self_approve(
    service: AccessRequestService,
    store: InMemoryStateStore,
) -> None:
    request = await submit(service, actor=principal("requester-1", Role.CONTRIBUTOR))

    with pytest.raises(AccessRequestPermissionError, match="own request"):
        await service.review(
            principal=principal("requester-1", Role.OWNER),
            request_id=request.request_id,
            decision=AccessReviewDecision.APPROVE,
            justification="Reviewed against the support access policy.",
            now=datetime(2026, 7, 16, 1, tzinfo=UTC),
        )

    reviewed = await service.review(
        principal=principal("owner-2", Role.OWNER),
        request_id=request.request_id,
        decision=AccessReviewDecision.APPROVE,
        justification="Reviewed against the support access policy.",
        now=datetime(2026, 7, 16, 1, tzinfo=UTC),
    )

    assert reviewed.status.value == "approved"
    assert reviewed.reviewed_by == "owner-2"
    assert reviewed.review_justification == "Reviewed against the support access policy."
    action_kinds = [entry["entry"]["action_kind"] for entry in store.audit_entries]
    assert action_kinds == ["iam.access-requested", "iam.access-reviewed"]

    replay = await service.review(
        principal=principal("owner-2", Role.OWNER),
        request_id=request.request_id,
        decision=AccessReviewDecision.APPROVE,
        justification="Reviewed against the support access policy.",
        now=datetime(2026, 7, 16, 2, tzinfo=UTC),
    )
    assert replay.reviewed_at == datetime(2026, 7, 16, 1, tzinfo=UTC)
    assert len(tuple(store.audit_entries)) == 2


async def test_owner_can_review_request_older_than_two_hundred_records(
    service: AccessRequestService,
) -> None:
    oldest = await submit(service, idempotency_key="request-000")
    for index in range(1, 202):
        await submit(service, idempotency_key=f"request-{index:03d}")

    reviewed = await service.review(
        principal=principal("owner-2", Role.OWNER),
        request_id=oldest.request_id,
        decision=AccessReviewDecision.APPROVE,
        justification="Reviewed against the support access policy.",
        now=datetime(2026, 7, 16, 1, tzinfo=UTC),
    )

    assert reviewed.status.value == "approved"


async def test_a_recased_object_id_cannot_approve_its_own_request(
    service: AccessRequestService,
) -> None:
    """An object id is the same principal however it is cased, so a raw string
    comparison let a requester approve their own request under another
    spelling.
    """
    request = await submit(service, actor=principal("requester-1", Role.CONTRIBUTOR))

    with pytest.raises(AccessRequestPermissionError, match="own request"):
        await service.review(
            principal=principal("REQUESTER-1", Role.OWNER),
            request_id=request.request_id,
            decision=AccessReviewDecision.APPROVE,
            justification="Reviewed against the support access policy.",
            now=datetime(2026, 7, 16, 1, tzinfo=UTC),
        )
