from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest

from fdai.delivery.identity import EntraHumanAccessProvisioner
from fdai.shared.providers.human_access import (
    HumanAccessOperation,
    HumanAccessOutcome,
    HumanAccessPlan,
)
from fdai.shared.providers.workload_identity import IdentityToken


class FakeIdentity:
    def __init__(self) -> None:
        self.audiences: list[str] = []

    async def get_token(self, audience: str) -> IdentityToken:
        self.audiences.append(audience)
        return IdentityToken(
            token="graph-token",
            expires_at=datetime.now(UTC) + timedelta(minutes=5),
            audience=audience,
        )


def _plan() -> HumanAccessPlan:
    return HumanAccessPlan(
        case_id="case-1",
        subject_id="user-1",
        group_id="group-reader",
        operation=HumanAccessOperation.GRANT,
        idempotency_key="human-access:case-1",
    )


async def test_entra_access_applies_and_verifies_allowlisted_membership() -> None:
    member = False
    mutations = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal member, mutations
        assert request.headers["authorization"] == "Bearer graph-token"
        path = request.url.path
        if path == "/v1.0/users/user-1":
            return httpx.Response(200, json={"id": "user-1", "accountEnabled": True})
        if path == "/v1.0/groups/group-reader":
            return httpx.Response(
                200,
                json={
                    "id": "group-reader",
                    "securityEnabled": True,
                    "groupTypes": [],
                    "isAssignableToRole": False,
                },
            )
        if path == "/v1.0/groups/group-reader/members/user-1":
            return httpx.Response(200 if member else 404, json={"id": "user-1"})
        if path == "/v1.0/groups/group-reader/members/$ref":
            mutations += 1
            member = True
            return httpx.Response(204)
        raise AssertionError(path)

    identity = FakeIdentity()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = EntraHumanAccessProvisioner(
            client=client,
            identity=identity,
            allowed_group_ids=frozenset({"group-reader"}),
        )
        first = await adapter.apply(_plan())
        second = await adapter.apply(_plan())
        verified = await adapter.verify(_plan())

    assert first.outcome is HumanAccessOutcome.APPLIED
    assert second.outcome is HumanAccessOutcome.ALREADY_APPLIED
    assert verified is True
    assert mutations == 1
    assert set(identity.audiences) == {"https://graph.microsoft.com/.default"}


async def test_entra_access_refuses_unallowlisted_group_before_token() -> None:
    identity = FakeIdentity()
    async with httpx.AsyncClient() as client:
        adapter = EntraHumanAccessProvisioner(
            client=client,
            identity=identity,
            allowed_group_ids=frozenset({"group-reader"}),
        )
        plan = HumanAccessPlan(
            case_id="case-1",
            subject_id="user-1",
            group_id="arbitrary-group",
            operation=HumanAccessOperation.GRANT,
            idempotency_key="key-1",
        )
        with pytest.raises(PermissionError, match="not allowlisted"):
            await adapter.apply(plan)
    assert identity.audiences == []


async def test_entra_access_refuses_role_assignable_group() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1.0/users/user-1":
            return httpx.Response(200, json={"id": "user-1", "accountEnabled": True})
        if request.url.path == "/v1.0/groups/group-reader":
            return httpx.Response(
                200,
                json={
                    "id": "group-reader",
                    "securityEnabled": True,
                    "groupTypes": [],
                    "isAssignableToRole": True,
                },
            )
        raise AssertionError(request.url.path)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = EntraHumanAccessProvisioner(
            client=client,
            identity=FakeIdentity(),
            allowed_group_ids=frozenset({"group-reader"}),
        )
        with pytest.raises(PermissionError, match="role-assignable"):
            await adapter.apply(_plan())


async def test_entra_access_refuses_dynamic_group() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1.0/users/user-1":
            return httpx.Response(200, json={"id": "user-1", "accountEnabled": True})
        if request.url.path == "/v1.0/groups/group-reader":
            return httpx.Response(
                200,
                json={
                    "id": "group-reader",
                    "securityEnabled": True,
                    "groupTypes": ["DynamicMembership"],
                    "isAssignableToRole": False,
                },
            )
        raise AssertionError(request.url.path)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = EntraHumanAccessProvisioner(
            client=client,
            identity=FakeIdentity(),
            allowed_group_ids=frozenset({"group-reader"}),
        )
        with pytest.raises(PermissionError, match="dynamic groups"):
            await adapter.apply(_plan())


@pytest.mark.parametrize(
    "group_payload",
    [
        {"id": "group-reader", "securityEnabled": True, "isAssignableToRole": False},
        {"id": "group-reader", "securityEnabled": True, "groupTypes": []},
        {
            "id": "group-reader",
            "securityEnabled": True,
            "groupTypes": [False],
            "isAssignableToRole": False,
        },
    ],
)
async def test_entra_access_refuses_incomplete_group_classification(
    group_payload: dict[str, object],
) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1.0/users/user-1":
            return httpx.Response(200, json={"id": "user-1", "accountEnabled": True})
        if request.url.path == "/v1.0/groups/group-reader":
            return httpx.Response(200, json=group_payload)
        raise AssertionError(request.url.path)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = EntraHumanAccessProvisioner(
            client=client,
            identity=FakeIdentity(),
            allowed_group_ids=frozenset({"group-reader"}),
        )
        with pytest.raises(ValueError, match="classification"):
            await adapter.apply(_plan())


async def test_entra_access_waits_for_membership_convergence() -> None:
    membership_reads = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal membership_reads
        if request.url.path == "/v1.0/groups/group-reader/members/user-1":
            membership_reads += 1
            return httpx.Response(
                200 if membership_reads >= 3 else 404,
                json={"id": "user-1"},
            )
        raise AssertionError(request.url.path)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = EntraHumanAccessProvisioner(
            client=client,
            identity=FakeIdentity(),
            allowed_group_ids=frozenset({"group-reader"}),
            verification_attempts=3,
            verification_delay_seconds=0,
        )
        assert await adapter.verify(_plan()) is True
    assert membership_reads == 3


async def test_entra_access_rejects_wrong_membership_subject() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id": "other-user"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = EntraHumanAccessProvisioner(
            client=client,
            identity=FakeIdentity(),
            allowed_group_ids=frozenset({"group-reader"}),
            verification_attempts=1,
        )
        with pytest.raises(ValueError, match="did not match"):
            await adapter.verify(_plan())


async def test_entra_access_refuses_inactive_user() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1.0/users/user-1":
            return httpx.Response(200, json={"id": "user-1", "accountEnabled": False})
        raise AssertionError(request.url.path)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = EntraHumanAccessProvisioner(
            client=client,
            identity=FakeIdentity(),
            allowed_group_ids=frozenset({"group-reader"}),
        )
        with pytest.raises(ValueError, match="inactive"):
            await adapter.apply(_plan())


async def test_entra_access_fails_closed_on_graph_permission_denial() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"error": {"message": "sensitive provider detail"}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = EntraHumanAccessProvisioner(
            client=client,
            identity=FakeIdentity(),
            allowed_group_ids=frozenset({"group-reader"}),
        )
        with pytest.raises(httpx.HTTPStatusError) as error:
            await adapter.apply(_plan())
    assert "sensitive provider detail" not in str(error.value)


async def test_entra_access_retries_transient_graph_response() -> None:
    user_reads = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal user_reads
        if request.url.path == "/v1.0/users/user-1":
            user_reads += 1
            if user_reads == 1:
                return httpx.Response(429, headers={"Retry-After": "0"})
            return httpx.Response(200, json={"id": "user-1", "accountEnabled": True})
        if request.url.path == "/v1.0/groups/group-reader":
            return httpx.Response(
                200,
                json={
                    "id": "group-reader",
                    "securityEnabled": True,
                    "groupTypes": [],
                    "isAssignableToRole": False,
                },
            )
        if request.url.path == "/v1.0/groups/group-reader/members/user-1":
            return httpx.Response(200, json={"id": "user-1"})
        raise AssertionError(request.url.path)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = EntraHumanAccessProvisioner(
            client=client,
            identity=FakeIdentity(),
            allowed_group_ids=frozenset({"group-reader"}),
        )
        receipt = await adapter.apply(_plan())
    assert receipt.outcome is HumanAccessOutcome.ALREADY_APPLIED
    assert user_reads == 2


async def test_entra_access_revoke_and_restore_are_exact_inverses() -> None:
    member = True
    mutations: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal member
        path = request.url.path
        if path == "/v1.0/users/user-1":
            return httpx.Response(200, json={"id": "user-1", "accountEnabled": True})
        if path == "/v1.0/groups/group-reader":
            return httpx.Response(
                200,
                json={
                    "id": "group-reader",
                    "securityEnabled": True,
                    "groupTypes": [],
                    "isAssignableToRole": False,
                },
            )
        if path == "/v1.0/groups/group-reader/members/user-1":
            return httpx.Response(200 if member else 404, json={"id": "user-1"})
        if path == "/v1.0/groups/group-reader/members/user-1/$ref":
            mutations.append("revoke")
            member = False
            return httpx.Response(204)
        if path == "/v1.0/groups/group-reader/members/$ref":
            mutations.append("grant")
            member = True
            return httpx.Response(204)
        raise AssertionError(path)

    plan = HumanAccessPlan(
        case_id="case-1",
        subject_id="user-1",
        group_id="group-reader",
        operation=HumanAccessOperation.REVOKE,
        idempotency_key="human-access:case-1:revoke",
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = EntraHumanAccessProvisioner(
            client=client,
            identity=FakeIdentity(),
            allowed_group_ids=frozenset({"group-reader"}),
            verification_delay_seconds=0,
        )
        revoked = await adapter.apply(plan)
        assert await adapter.verify(plan) is True
        restored = await adapter.rollback(plan)

    assert revoked.outcome is HumanAccessOutcome.APPLIED
    assert restored.outcome is HumanAccessOutcome.ROLLED_BACK
    assert member is True
    assert mutations == ["revoke", "grant"]


async def test_entra_access_converges_duplicate_add_race() -> None:
    membership_reads = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal membership_reads
        path = request.url.path
        if path == "/v1.0/users/user-1":
            return httpx.Response(200, json={"id": "user-1", "accountEnabled": True})
        if path == "/v1.0/groups/group-reader":
            return httpx.Response(
                200,
                json={
                    "id": "group-reader",
                    "securityEnabled": True,
                    "groupTypes": [],
                    "isAssignableToRole": False,
                },
            )
        if path == "/v1.0/groups/group-reader/members/user-1":
            membership_reads += 1
            return httpx.Response(
                404 if membership_reads == 1 else 200,
                json={"id": "user-1"},
            )
        if path == "/v1.0/groups/group-reader/members/$ref":
            return httpx.Response(400, json={"error": {"code": "Request_BadRequest"}})
        raise AssertionError(path)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = EntraHumanAccessProvisioner(
            client=client,
            identity=FakeIdentity(),
            allowed_group_ids=frozenset({"group-reader"}),
        )
        receipt = await adapter.apply(_plan())

    assert receipt.outcome is HumanAccessOutcome.ALREADY_APPLIED
    assert membership_reads == 2


async def test_entra_access_revokes_disabled_user_membership() -> None:
    member = True
    revoke_plan = HumanAccessPlan(
        case_id="case-1",
        subject_id="user-1",
        group_id="group-reader",
        operation=HumanAccessOperation.REVOKE,
        idempotency_key="human-access:case-1:revoke",
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal member
        path = request.url.path
        if path == "/v1.0/users/user-1":
            return httpx.Response(200, json={"id": "user-1", "accountEnabled": False})
        if path == "/v1.0/groups/group-reader":
            return httpx.Response(
                200,
                json={
                    "id": "group-reader",
                    "securityEnabled": True,
                    "groupTypes": [],
                    "isAssignableToRole": False,
                },
            )
        if path == "/v1.0/groups/group-reader/members/user-1":
            return httpx.Response(200 if member else 404, json={"id": "user-1"})
        if path == "/v1.0/groups/group-reader/members/user-1/$ref":
            member = False
            return httpx.Response(204)
        raise AssertionError(path)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = EntraHumanAccessProvisioner(
            client=client,
            identity=FakeIdentity(),
            allowed_group_ids=frozenset({"group-reader"}),
        )
        receipt = await adapter.apply(revoke_plan)
        verified = await adapter.verify(revoke_plan)

    assert receipt.outcome is HumanAccessOutcome.APPLIED
    assert verified is True
