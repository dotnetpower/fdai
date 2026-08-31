"""Focused proof for the Operator-owned Microsoft Teams approval receiver.

Every case drives the real route, the real Bot Framework service-token
verifier, the real Entra callback authority, and the real shared decision
service. Tokens are genuine RS256 JWTs signed by an ephemeral in-process key,
so the activity -> authority -> decision path is exercised end to end without
any network call.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fdai_operator_service.auth import OperatorAuthenticator
from fdai_operator_service.families.conversation.channel_edge.teams_auth import (
    TeamsServiceTokenVerifier,
    TeamsTokenConfig,
)
from fdai_operator_service.families.iam import IamFamilyBindings, make_iam_family_routes
from fdai_operator_service.families.iam.contracts import (
    HilDecisionCommand,
    HilDecisionOutboxRequest,
    HilDecisionReceipt,
    HilPendingItem,
)
from fdai_operator_service.families.iam.errors import IamUnavailableError
from fdai_operator_service.families.iam.hil_callback import HilCallbackConfig, compute_hmac
from fdai_operator_service.families.iam.hil_callback_audit import (
    HilCallbackAuditRecord,
    HilCallbackOutcome,
)
from fdai_operator_service.families.iam.hil_callback_authority import (
    EntraHilCallbackAuthority,
    HilCallbackAuthorityConfig,
)
from fdai_operator_service.families.iam.hil_callback_context import HilCallbackContext
from fdai_operator_service.families.iam.hil_teams_callback import (
    HIL_DECISION_ACTION,
    TeamsHilCallbackConfig,
    TeamsHilCallbackNormalizer,
)
from fdai_service_contracts import OperatorPrincipal, OperatorRole
from starlette.applications import Starlette
from starlette.testclient import TestClient

BOT_APPLICATION_ID = "approval-bot"
OPERATOR_AUDIENCE = "api://operator"
ISSUER = "https://login.microsoftonline.com/tenant/v2.0"
TENANT_ID = "tenant-1"
TEAM_ID = "approval-team"
CHANNEL_ID = "approval-channel"
SERVICE_URL = "https://smba.trafficmanager.invalid/amer"
TEAMS_ACTOR = "teams-aad-object-id"
APPROVER_OID = "approver-1"
GROUP_IDS = {
    OperatorRole.READER: "readers",
    OperatorRole.CONTRIBUTOR: "contributors",
    OperatorRole.APPROVER: "approvers",
    OperatorRole.OWNER: "owners",
    OperatorRole.BREAK_GLASS: "break-glass",
}
TEAMS_ROUTE = "/hil/teams-activity"


class _Identity:
    """Sign and verify synthetic Bot service and delegated user tokens."""

    def __init__(self) -> None:
        self._key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.key_id = "test-key-1"
        self._pem = self._key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )

    def jwks(self) -> Sequence[Mapping[str, Any]]:
        public = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(self._key.public_key()))
        public.update({"kid": self.key_id, "use": "sig", "alg": "RS256"})
        return (public,)

    def service_token(self, *, service_url: str = SERVICE_URL, audience: str | None = None) -> str:
        now = datetime.now(tz=UTC)
        return jwt.encode(
            {
                "iss": "https://api.botframework.com",
                "aud": audience or BOT_APPLICATION_ID,
                "serviceurl": service_url,
                "nbf": int((now - timedelta(seconds=10)).timestamp()),
                "exp": int((now + timedelta(minutes=5)).timestamp()),
            },
            self._pem,
            algorithm="RS256",
            headers={"kid": self.key_id},
        )

    def delegated_token(
        self,
        *,
        oid: str = APPROVER_OID,
        roles: Sequence[str] = ("Approver",),
        azp: str = BOT_APPLICATION_ID,
    ) -> str:
        now = datetime.now(tz=UTC)
        return jwt.encode(
            {
                "iss": ISSUER,
                "aud": OPERATOR_AUDIENCE,
                "oid": oid,
                "idtyp": "user",
                "roles": list(roles),
                "azp": azp,
                "exp": int((now + timedelta(minutes=5)).timestamp()),
            },
            self._pem,
            algorithm="RS256",
            headers={"kid": self.key_id},
        )

    def verify(self, token: str) -> Mapping[str, object]:
        claims: Mapping[str, object] = jwt.decode(
            token,
            self._key.public_key(),
            algorithms=["RS256"],
            audience=OPERATOR_AUDIENCE,
            issuer=ISSUER,
            options={"require": ["exp", "iss", "aud"]},
        )
        return claims


class _Jwks:
    def __init__(self, identity: _Identity) -> None:
        self._identity = identity

    async def get_keys(self) -> Sequence[Mapping[str, Any]]:
        return self._identity.jwks()


class _Registry:
    def __init__(
        self,
        *,
        submitter_oid: str = "submitter-1",
        metadata: Mapping[str, str] | None = None,
        expires_at: datetime | None = None,
    ) -> None:
        self.pending = HilPendingItem(
            approval_id="approval-1",
            idempotency_key="hil-key-1",
            submitter_oid=submitter_oid,
            metadata=dict(metadata or {}),
        )
        self.context = HilCallbackContext(
            approval_id="approval-1",
            correlation_id="correlation-1",
            idempotency_key="hil-key-1",
            action_hash="action-hash-1",
            expires_at=expires_at or datetime.now(tz=UTC) + timedelta(minutes=10),
            submitter_oid=submitter_oid,
            metadata=dict(metadata or {}),
        )
        self.command: HilDecisionCommand | None = None
        self.receipt: HilDecisionReceipt | None = None

    async def get_pending_by_approval_id(self, approval_id: str) -> HilPendingItem | None:
        return self.pending if approval_id == self.pending.approval_id else None

    async def get_decision_by_approval_id(self, approval_id: str) -> HilDecisionReceipt | None:
        return self.receipt if self.receipt and approval_id == self.receipt.approval_id else None

    async def get_callback_context(self, approval_id: str) -> HilCallbackContext | None:
        return self.context if approval_id == self.context.approval_id else None

    async def record_decision(self, command: HilDecisionCommand) -> HilDecisionReceipt:
        self.command = command
        self.receipt = HilDecisionReceipt(
            approval_id="approval-1",
            idempotency_key=command.idempotency_key,
            decision=command.decision,
            approver_oid=command.approver_oid,
            decided_at=command.decided_at,
            receipt_ref="receipt-1",
            justification=command.justification,
        )
        return self.receipt

    async def mark_delivered(self, receipt: HilDecisionReceipt) -> HilDecisionReceipt:
        self.receipt = replace(receipt, delivered=True)
        return self.receipt


class _Outbox:
    def __init__(self) -> None:
        self.requests: list[HilDecisionOutboxRequest] = []

    async def enqueue(self, request: HilDecisionOutboxRequest) -> None:
        self.requests.append(request)


class _Audit:
    def __init__(self) -> None:
        self.records: list[HilCallbackAuditRecord] = []

    async def append_callback_audit(self, record: HilCallbackAuditRecord) -> None:
        self.records.append(record)


def _authority(identity: _Identity) -> EntraHilCallbackAuthority:
    return EntraHilCallbackAuthority(
        authenticator=OperatorAuthenticator(verifier=identity.verify, group_ids=GROUP_IDS),
        config=HilCallbackAuthorityConfig.from_environment(
            {
                "FDAI_TEAMS_APPLICATION_ID": BOT_APPLICATION_ID,
                "FDAI_TEAMS_APPROVAL_TEAM_ID": TEAM_ID,
                "FDAI_TEAMS_APPROVAL_CHANNEL_ID": CHANNEL_ID,
                "FDAI_TEAMS_PRINCIPAL_MAP_JSON": json.dumps({TEAMS_ACTOR: APPROVER_OID}),
            },
            group_ids=GROUP_IDS,
        ),
    )


def _normalizer(identity: _Identity) -> TeamsHilCallbackNormalizer:
    return TeamsHilCallbackNormalizer(
        config=TeamsHilCallbackConfig(
            application_id=BOT_APPLICATION_ID,
            tenant_id=TENANT_ID,
            team_id=TEAM_ID,
            channel_id=CHANNEL_ID,
            allowed_service_urls=frozenset({SERVICE_URL}),
        ),
        tokens=TeamsServiceTokenVerifier(
            config=TeamsTokenConfig(application_id=BOT_APPLICATION_ID),
            jwks=_Jwks(identity),
        ),
    )


async def _authorize(_request: Any, *_roles: object) -> OperatorPrincipal:
    return OperatorPrincipal(
        subject_id=APPROVER_OID,
        roles=frozenset({OperatorRole.OWNER}),
    )


def _client(
    identity: _Identity,
    registry: _Registry,
    outbox: _Outbox,
    audit: _Audit,
) -> TestClient:
    bindings = IamFamilyBindings(
        authorize=_authorize,
        authenticate=_authorize,
        hil_registry=registry,  # type: ignore[arg-type]
        hil_outbox=outbox,  # type: ignore[arg-type]
        hil_config=HilCallbackConfig(secret="test-secret"),
        hil_authority=_authority(identity),
        hil_audit=audit,  # type: ignore[arg-type]
        hil_context=registry,  # type: ignore[arg-type]
        hil_teams_normalizer=_normalizer(identity),
    )
    return TestClient(Starlette(routes=list(make_iam_family_routes(bindings))))


def _activity(
    identity: _Identity,
    *,
    decision: str = "approve",
    approval_id: str = "approval-1",
    data_overrides: Mapping[str, object] | None = None,
    drop_data_fields: Sequence[str] = (),
    channel_data: Mapping[str, Any] | None = None,
    activity_type: str = "invoke",
    activity_name: str = "adaptiveCard/action",
    verb: str = HIL_DECISION_ACTION,
    service_url: str = SERVICE_URL,
    delegated_token: str | None = None,
    include_authentication: bool = True,
) -> bytes:
    data: dict[str, object] = {
        "decision": decision,
        "justification": "Verified rollback and blast radius.",
        "approval_id": approval_id,
        "correlation_id": "correlation-1",
        "idempotency_key": "hil-key-1",
        "action_hash": "action-hash-1",
        "audience": f"teams:{TEAM_ID}:{CHANNEL_ID}",
    }
    data.update(data_overrides or {})
    for field in drop_data_fields:
        data.pop(field, None)
    value: dict[str, Any] = {
        "action": {"type": "Action.Execute", "verb": verb, "data": data},
        "trigger": "manual",
    }
    if include_authentication:
        value["authentication"] = {
            "token": delegated_token or identity.delegated_token(),
        }
    payload = {
        "type": activity_type,
        "name": activity_name,
        "id": "activity-1",
        "channelId": "msteams",
        "serviceUrl": service_url,
        "from": {"aadObjectId": TEAMS_ACTOR},
        "conversation": {"id": "19:thread@thread.tacv2"},
        "channelData": dict(
            channel_data
            or {
                "tenant": {"id": TENANT_ID},
                "team": {"id": TEAM_ID},
                "channel": {"id": CHANNEL_ID},
            }
        ),
        "value": value,
    }
    return json.dumps(payload, separators=(",", ":")).encode()


def test_teams_activity_reaches_authority_and_records_the_decision() -> None:
    identity = _Identity()
    registry = _Registry()
    outbox = _Outbox()
    audit = _Audit()
    client = _client(identity, registry, outbox, audit)

    response = client.post(
        TEAMS_ROUTE,
        content=_activity(identity),
        headers={"Authorization": f"Bearer {identity.service_token()}"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["decision"] == "approve"
    assert body["delivered"] is True
    assert body["correlation_id"] == "correlation-1"
    assert registry.command is not None
    # The recorded approver comes from the OBO token, not from card data.
    assert registry.command.approver_oid == APPROVER_OID
    assert registry.command.justification == "Verified rollback and blast radius."
    assert len(outbox.requests) == 1
    assert [record.outcome for record in audit.records] == [
        HilCallbackOutcome.PENDING,
        HilCallbackOutcome.ACCEPTED,
    ]
    assert audit.records[-1].authority_basis == "teams_sso_obo+entra_app_role"


def test_teams_activity_without_delegated_token_is_refused() -> None:
    identity = _Identity()
    registry = _Registry()
    client = _client(identity, registry, _Outbox(), _Audit())

    response = client.post(
        TEAMS_ROUTE,
        content=_activity(identity, include_authentication=False),
        headers={"Authorization": f"Bearer {identity.service_token()}"},
    )

    assert response.status_code == 400
    assert registry.command is None


def test_teams_activity_without_bot_service_token_is_unauthorized() -> None:
    identity = _Identity()
    registry = _Registry()
    audit = _Audit()
    client = _client(identity, registry, _Outbox(), audit)

    missing = client.post(TEAMS_ROUTE, content=_activity(identity))
    forged = client.post(
        TEAMS_ROUTE,
        content=_activity(identity),
        headers={"Authorization": f"Bearer {identity.delegated_token()}"},
    )

    assert missing.status_code == 401
    assert forged.status_code == 401
    assert registry.command is None
    assert audit.records == []


@pytest.mark.parametrize(
    ("overrides", "status"),
    [
        ({"data_overrides": {"provider_actor_id": "attacker"}}, 400),
        ({"data_overrides": {"roles": "Owner"}}, 400),
        ({"data_overrides": {"approver_oid": "attacker"}}, 400),
        ({"drop_data_fields": ("audience",)}, 400),
        ({"data_overrides": {"approval_id": "approval-2"}}, 404),
        ({"data_overrides": {"audience": "teams:other:other"}}, 403),
        ({"data_overrides": {"decision": "maybe"}}, 400),
        ({"verb": "attacker.verb"}, 400),
        ({"activity_type": "message"}, 400),
        ({"activity_name": "composeExtension/query"}, 400),
        ({"service_url": "https://smba.invalid/other"}, 403),
    ],
)
def test_untrusted_card_and_envelope_fields_never_grant_authority(
    overrides: Mapping[str, Any],
    status: int,
) -> None:
    identity = _Identity()
    registry = _Registry()
    outbox = _Outbox()
    client = _client(identity, registry, outbox, _Audit())

    response = client.post(
        TEAMS_ROUTE,
        content=_activity(identity, **overrides),
        headers={"Authorization": f"Bearer {identity.service_token()}"},
    )

    assert response.status_code == status
    assert registry.command is None
    assert outbox.requests == []


@pytest.mark.parametrize(
    "channel_data",
    [
        {
            "tenant": {"id": "other-tenant"},
            "team": {"id": TEAM_ID},
            "channel": {"id": CHANNEL_ID},
        },
        {
            "tenant": {"id": TENANT_ID},
            "team": {"id": "other-team"},
            "channel": {"id": CHANNEL_ID},
        },
        {
            "tenant": {"id": TENANT_ID},
            "team": {"id": TEAM_ID},
            "channel": {"id": "other-channel"},
        },
    ],
)
def test_activity_outside_the_configured_group_connected_channel_is_refused(
    channel_data: Mapping[str, Any],
) -> None:
    identity = _Identity()
    registry = _Registry()
    client = _client(identity, registry, _Outbox(), _Audit())

    response = client.post(
        TEAMS_ROUTE,
        content=_activity(identity, channel_data=channel_data),
        headers={"Authorization": f"Bearer {identity.service_token()}"},
    )

    assert response.status_code == 403
    assert registry.command is None


def test_delegated_token_from_another_client_or_actor_is_refused() -> None:
    identity = _Identity()
    registry = _Registry()
    client = _client(identity, registry, _Outbox(), _Audit())

    wrong_client = client.post(
        TEAMS_ROUTE,
        content=_activity(identity, delegated_token=identity.delegated_token(azp="other-app")),
        headers={"Authorization": f"Bearer {identity.service_token()}"},
    )
    wrong_actor = client.post(
        TEAMS_ROUTE,
        content=_activity(identity, delegated_token=identity.delegated_token(oid="someone-else")),
        headers={"Authorization": f"Bearer {identity.service_token()}"},
    )
    break_glass = client.post(
        TEAMS_ROUTE,
        content=_activity(
            identity,
            delegated_token=identity.delegated_token(roles=("BreakGlass",)),
        ),
        headers={"Authorization": f"Bearer {identity.service_token()}"},
    )

    assert wrong_client.status_code == 403
    assert wrong_client.json()["error"]["kind"] == "wrong_client"
    assert wrong_actor.status_code == 403
    assert wrong_actor.json()["error"]["kind"] == "wrong_actor"
    assert break_glass.status_code == 403
    assert break_glass.json()["error"]["kind"] == "capability_forbidden"
    assert registry.command is None


def test_teams_self_approval_and_workflow_role_floor_are_enforced() -> None:
    identity = _Identity()
    self_registry = _Registry(submitter_oid=APPROVER_OID.upper())
    self_response = _client(identity, self_registry, _Outbox(), _Audit()).post(
        TEAMS_ROUTE,
        content=_activity(identity),
        headers={"Authorization": f"Bearer {identity.service_token()}"},
    )
    assert self_response.status_code == 403
    assert self_response.json()["error"]["kind"] == "self_approval_forbidden"
    assert self_registry.command is None

    role_registry = _Registry(metadata={"decision_route": "workflow", "required_role": "owner"})
    role_response = _client(identity, role_registry, _Outbox(), _Audit()).post(
        TEAMS_ROUTE,
        content=_activity(identity),
        headers={"Authorization": f"Bearer {identity.service_token()}"},
    )
    assert role_response.status_code == 403
    assert role_response.json()["error"]["kind"] == "role_forbidden"
    assert role_registry.command is None


def test_expired_teams_approval_fails_closed_with_audit() -> None:
    identity = _Identity()
    registry = _Registry(expires_at=datetime.now(tz=UTC) - timedelta(seconds=1))
    audit = _Audit()
    response = _client(identity, registry, _Outbox(), audit).post(
        TEAMS_ROUTE,
        content=_activity(identity),
        headers={"Authorization": f"Bearer {identity.service_token()}"},
    )

    assert response.status_code == 410
    assert registry.command is None
    assert audit.records[-1].outcome is HilCallbackOutcome.EXPIRED


def test_teams_activity_replay_is_idempotent() -> None:
    identity = _Identity()
    registry = _Registry()
    outbox = _Outbox()
    client = _client(identity, registry, outbox, _Audit())
    body = _activity(identity)
    headers = {"Authorization": f"Bearer {identity.service_token()}"}

    first = client.post(TEAMS_ROUTE, content=body, headers=headers)
    replay = client.post(TEAMS_ROUTE, content=body, headers=headers)

    assert first.status_code == replay.status_code == 200
    assert first.json()["already_recorded"] is False
    assert replay.json()["already_recorded"] is True
    assert replay.json()["receipt_ref"] == first.json()["receipt_ref"]
    assert len(outbox.requests) == 1


def test_signed_callback_refuses_a_teams_channel_claim() -> None:
    """A shared HMAC secret must not let a caller assert a Teams actor."""
    identity = _Identity()
    registry = _Registry()
    outbox = _Outbox()
    config = HilCallbackConfig(secret="test-secret")
    client = _client(identity, registry, outbox, _Audit())
    body = json.dumps(
        {
            "decision": "approve",
            "justification": "Relayed approval.",
            "channel": "teams",
            "provider_actor_id": TEAMS_ACTOR,
            "audience": f"teams:{TEAM_ID}:{CHANNEL_ID}",
            "correlation_id": "correlation-1",
            "idempotency_key": "hil-key-1",
            "action_hash": "action-hash-1",
        },
        separators=(",", ":"),
    ).encode()
    timestamp = datetime.now(tz=UTC).isoformat()

    response = client.post(
        "/hil/approval-1/decision",
        content=body,
        headers={
            "Authorization": f"Bearer {identity.delegated_token()}",
            "X-FDAI-Timestamp": timestamp,
            "X-FDAI-Signature": "sha256="
            + compute_hmac(
                secret=config.secret,
                timestamp=timestamp,
                approval_id="approval-1",
                payload=body,
            ),
        },
    )

    assert response.status_code == 400
    assert response.json()["error"]["kind"] == "wrong_transport"
    assert registry.command is None
    assert outbox.requests == []


def test_teams_receiver_config_requires_a_complete_surface() -> None:
    assert (
        TeamsHilCallbackConfig.from_environment(
            {"FDAI_TEAMS_TENANT_ID": TENANT_ID},
            application_id="",
            team_id=TEAM_ID,
            channel_id=CHANNEL_ID,
        )
        is None
    )
    with pytest.raises(ValueError, match="tenant and allowed Bot service URLs"):
        TeamsHilCallbackConfig.from_environment(
            {},
            application_id=BOT_APPLICATION_ID,
            team_id=TEAM_ID,
            channel_id=CHANNEL_ID,
        )
    config = TeamsHilCallbackConfig.from_environment(
        {
            "FDAI_TEAMS_TENANT_ID": TENANT_ID,
            "FDAI_TEAMS_ALLOWED_SERVICE_URLS_JSON": json.dumps([SERVICE_URL]),
        },
        application_id=BOT_APPLICATION_ID,
        team_id=TEAM_ID,
        channel_id=CHANNEL_ID,
    )
    assert config is not None
    assert config.approval_audience == f"teams:{TEAM_ID}:{CHANNEL_ID}"


def test_teams_route_is_unavailable_until_the_normalizer_is_composed() -> None:
    identity = _Identity()
    registry = _Registry()
    bindings = IamFamilyBindings(
        authorize=_authorize,
        authenticate=_authorize,
        hil_registry=registry,  # type: ignore[arg-type]
        hil_outbox=_Outbox(),  # type: ignore[arg-type]
        hil_config=HilCallbackConfig(secret="test-secret"),
        hil_authority=_authority(identity),
        hil_audit=_Audit(),  # type: ignore[arg-type]
        hil_context=registry,  # type: ignore[arg-type]
    )
    client = TestClient(Starlette(routes=list(make_iam_family_routes(bindings))))

    response = client.post(
        TEAMS_ROUTE,
        content=_activity(identity),
        headers={"Authorization": f"Bearer {identity.service_token()}"},
    )

    assert response.status_code == 503


def test_receipt_reports_undelivered_when_delivery_state_cannot_be_written() -> None:
    """Broker acceptance without a delivery checkpoint stays replayable."""

    class UnwritableRegistry(_Registry):
        async def mark_delivered(self, receipt: HilDecisionReceipt) -> HilDecisionReceipt:
            raise IamUnavailableError("HIL delivery receipt store is unavailable")

    identity = _Identity()
    registry = UnwritableRegistry()
    outbox = _Outbox()
    client = _client(identity, registry, outbox, _Audit())

    response = client.post(
        TEAMS_ROUTE,
        content=_activity(identity),
        headers={"Authorization": f"Bearer {identity.service_token()}"},
    )

    assert response.status_code == 200
    # The broker already accepted the record, so the callback does not fail the
    # human. The durable receipt stays undelivered for the lease-fenced worker.
    assert response.json()["delivered"] is False
    assert len(outbox.requests) == 1


def test_broker_failure_reports_a_durable_redrive_rather_than_a_lost_decision() -> None:
    class FailingOutbox(_Outbox):
        async def enqueue(self, request: HilDecisionOutboxRequest) -> None:
            await super().enqueue(request)
            raise RuntimeError("synthetic broker outage")

    identity = _Identity()
    registry = _Registry()
    outbox = FailingOutbox()
    client = _client(identity, registry, outbox, _Audit())

    response = client.post(
        TEAMS_ROUTE,
        content=_activity(identity),
        headers={"Authorization": f"Bearer {identity.service_token()}"},
    )

    assert response.status_code == 503
    assert response.json()["error"]["kind"] == "decision_publish_failed"
    assert "redriven from the durable outbox" in response.json()["error"]["message"]
    assert registry.command is not None
