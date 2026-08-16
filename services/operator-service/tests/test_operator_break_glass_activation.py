"""Break-Glass activation endpoint: audit only, never elevation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fdai_operator_service.families.iam import IamFamilyBindings, make_iam_family_routes
from fdai_operator_service.families.iam.capabilities import IamCapability, capabilities_for
from fdai_operator_service.families.iam.contracts import (
    BreakGlassActivationCommand,
    BreakGlassActivationRecord,
    IamPrincipal,
)
from fdai_service_contracts import OperatorRole
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.testclient import TestClient

ACTIVATION_PATH = "/system/break-glass/activation"


async def authorize(request: Request) -> IamPrincipal:
    raw_role = request.headers.get("x-test-role", OperatorRole.READER.value)
    roles = frozenset() if raw_role == "unassigned" else frozenset({OperatorRole(raw_role)})
    return IamPrincipal(oid=request.headers.get("x-test-oid", "operator-1"), roles=roles)


class RecordingBreakGlass:
    def __init__(self) -> None:
        self.command: BreakGlassActivationCommand | None = None

    async def activate(self, command: BreakGlassActivationCommand) -> BreakGlassActivationRecord:
        self.command = command
        return BreakGlassActivationRecord(
            activation_id="activation-1",
            actor_oid=command.actor_oid,
            incident_id=command.incident_id,
            activated_at=command.activated_at,
            expires_at=command.expires_at,
        )


def _client(**overrides: object) -> TestClient:
    values: dict[str, object] = {"authorize": authorize, "authenticate": authorize}
    values.update(overrides)
    return TestClient(
        Starlette(routes=make_iam_family_routes(IamFamilyBindings(**values)))  # type: ignore[arg-type]
    )


def _body(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "incident_id": "INC-4711",
        "reason": "Primary approver channel is unreachable during a Sev1.",
        "expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
    }
    payload.update(overrides)
    return payload


def _post(client: TestClient, *, role: str = "BreakGlass", **overrides: object):
    return client.post(ACTIVATION_PATH, headers={"x-test-role": role}, json=_body(**overrides))


# ---------------------------------------------------------------------------
# Capability boundary
# ---------------------------------------------------------------------------


def test_only_break_glass_carries_the_activation_capability() -> None:
    assert IamCapability.ACTIVATE_BREAK_GLASS in capabilities_for([OperatorRole.BREAK_GLASS])
    for role in (
        OperatorRole.READER,
        OperatorRole.CONTRIBUTOR,
        OperatorRole.APPROVER,
        OperatorRole.OWNER,
    ):
        assert IamCapability.ACTIVATE_BREAK_GLASS not in capabilities_for([role])


def test_owner_and_approver_are_denied() -> None:
    client = _client(break_glass=RecordingBreakGlass())
    assert _post(client, role="Owner").status_code == 403
    assert _post(client, role="Approver").status_code == 403


def test_activation_never_grants_hil_approval_capability() -> None:
    capabilities = capabilities_for([OperatorRole.BREAK_GLASS])
    assert IamCapability.APPROVE_RUNTIME_HIL not in capabilities


# ---------------------------------------------------------------------------
# Fail-closed request validation
# ---------------------------------------------------------------------------


def test_unconfigured_store_fails_closed() -> None:
    assert _post(_client()).status_code == 503


def test_incident_id_is_required() -> None:
    client = _client(break_glass=RecordingBreakGlass())
    assert _post(client, incident_id="").status_code == 400
    assert _post(client, incident_id="   ").status_code == 400
    assert _post(client, incident_id=4711).status_code == 400


def test_reason_is_required() -> None:
    client = _client(break_glass=RecordingBreakGlass())
    assert _post(client, reason="").status_code == 400


def test_expiry_must_be_a_future_offset_aware_timestamp() -> None:
    client = _client(break_glass=RecordingBreakGlass())
    past = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
    naive = datetime.now(UTC).replace(tzinfo=None).isoformat()
    assert _post(client, expires_at=past).status_code == 400
    assert _post(client, expires_at=naive).status_code == 400
    assert _post(client, expires_at="not-a-timestamp").status_code == 400
    assert _post(client, expires_at=None).status_code == 400


def test_expiry_beyond_the_maximum_activation_is_rejected() -> None:
    client = _client(break_glass=RecordingBreakGlass())
    far = (datetime.now(UTC) + timedelta(days=2)).isoformat()
    assert _post(client, expires_at=far).status_code == 400


# ---------------------------------------------------------------------------
# Recorded activation
# ---------------------------------------------------------------------------


def test_activation_records_actor_incident_and_expiry() -> None:
    outbox = RecordingBreakGlass()
    client = _client(break_glass=outbox)
    expires_at = (datetime.now(UTC) + timedelta(hours=1)).isoformat()

    response = client.post(
        ACTIVATION_PATH,
        headers={"x-test-role": "BreakGlass", "x-test-oid": "glass-1"},
        json=_body(expires_at=expires_at),
    )

    assert response.status_code == 201
    assert outbox.command is not None
    assert outbox.command.actor_oid == "glass-1"
    assert outbox.command.incident_id == "INC-4711"
    assert outbox.command.expires_at > outbox.command.activated_at


def test_activation_projection_carries_no_grant_or_identity() -> None:
    client = _client(break_glass=RecordingBreakGlass())

    payload = _post(client).json()

    assert payload["grants_hil_approval"] is False
    assert payload["grants_executor_identity"] is False
    assert set(payload) == {
        "activation_id",
        "actor_oid",
        "incident_id",
        "activated_at",
        "expires_at",
        "grants_hil_approval",
        "grants_executor_identity",
    }


def test_route_is_post_only() -> None:
    client = _client(break_glass=RecordingBreakGlass())
    assert client.get(ACTIVATION_PATH, headers={"x-test-role": "BreakGlass"}).status_code == 405
