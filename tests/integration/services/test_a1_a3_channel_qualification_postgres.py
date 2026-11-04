"""PostgreSQL and cross-service qualification for Teams and Slack A1/A3 channels (#941)."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import runpy
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx
import jwt
import psycopg
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fdai.core.hil_resume.integrity import action_payload_hash
from fdai.delivery.chatops.slack_adapter import (
    SLACK_POST_URL,
    SlackHilAdapter,
    SlackHilAdapterConfig,
)
from fdai.delivery.chatops.slack_request_outbox import DurableSlackApprovalChannel
from fdai.delivery.chatops.teams_adapter import (
    HIL_DECISION_ACTION,
    TeamsHilAdapter,
    TeamsHilAdapterConfig,
)
from fdai.delivery.persistence.postgres import PostgresStateStore, PostgresStateStoreConfig
from fdai.delivery.persistence.state_store_hil_registry import StateStoreHilApprovalRegistry
from fdai.runtime.consumers import _consume_hil_decisions
from fdai.shared.providers.hil_channel import HilApprovalRequest, HilChannelError
from fdai.shared.providers.testing.event_bus import InMemoryEventBus
from fdai.shared.providers.testing.workload_identity import StaticWorkloadIdentity
from fdai_operator_service.auth import OperatorAuthenticator
from fdai_operator_service.families.conversation.channel_edge.teams_auth import (
    TeamsServiceTokenVerifier,
    TeamsTokenConfig,
)
from fdai_operator_service.families.iam.hil_callback_authority import (
    EntraHilCallbackAuthority,
    HilCallbackAuthorityConfig,
)
from fdai_operator_service.families.iam.hil_decision_outbox import (
    DurableHilDecisionOutboxPublisher,
    HilDecisionOutboxDrainer,
)
from fdai_operator_service.families.iam.hil_teams_callback import (
    TeamsHilCallbackConfig,
    TeamsHilCallbackNormalizer,
    make_hil_teams_callback_route,
)
from fdai_operator_service.families.iam.slack_handoff import (
    PostgresSlackHandoffStore,
    make_slack_handoff_routes,
)
from fdai_operator_service.postgres_family_store import (
    PostgresFamilyStore,
    PostgresFamilyStoreConfig,
)
from fdai_operator_service.postgres_hil_decision import PostgresHilDecisionStore
from fdai_operator_service.postgres_iam import PostgresIamAdapters
from fdai_service_contracts import OperatorRole
from starlette.applications import Starlette

_support = runpy.run_path(str(Path(__file__).with_name("test_assignment_receipt_postgres.py")))
database, _role = _support["database"], _support["_role"]

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def _bind_validation_dsn_for_disposable_db() -> Iterator[None]:
    if os.environ.get("FDAI_ASSIGNMENT_TEST_DSN", "").strip():
        yield
        return
    raw = os.environ.get("FDAI_DATABASE_URL", "").strip()
    if not raw:
        yield
        return
    os.environ["FDAI_ASSIGNMENT_TEST_DSN"] = raw.replace(
        "postgresql+psycopg://", "postgresql://", 1
    )
    try:
        yield
    finally:
        os.environ.pop("FDAI_ASSIGNMENT_TEST_DSN", None)


SUBMITTER_OID = "00000000-0000-0000-0000-00000000b001"
APPROVER_OID = "00000000-0000-0000-0000-00000000b002"
SLACK_TEAM_ID = "T941QUAL"
SLACK_CHANNEL_ID = "C941QUAL01"
SLACK_USER_ID = "U941APPROVER"
SLACK_SIGNING_SECRET = "fixture"  # noqa: S105 - synthetic test key
TEAMS_TEAM_ID = "team-941-a1"
TEAMS_CHANNEL_ID = "channel-941-a1"
TEAMS_AUDIENCE = f"teams:{TEAMS_TEAM_ID}:{TEAMS_CHANNEL_ID}"
TEAMS_TENANT_ID = "00000000-0000-0000-0000-00000000b010"
TEAMS_BOT_APP_ID = "00000000-0000-0000-0000-00000000b011"
TEAMS_SERVICE_URL = "https://smba.trafficmanager.invalid/amer"
OPERATOR_AUDIENCE = "api://synthetic-operator-941"
ENTRA_ISSUER = f"https://login.microsoftonline.com/{TEAMS_TENANT_ID}/v2.0"
HIL_TOPIC = "fdai.hil.decisions"


class _EphemeralRsaIdentity:
    def __init__(self) -> None:
        self._key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.kid = "qual-941-kid"
        self._pem = self._key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        self._public = self._key.public_key()

    def jwks(self) -> tuple[dict[str, Any], ...]:
        jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(self._public))
        jwk.update({"kid": self.kid, "use": "sig", "alg": "RS256"})
        return (jwk,)

    def bot_service_token(self, *, now: datetime, service_url: str = TEAMS_SERVICE_URL) -> str:
        return jwt.encode(
            {
                "iss": "https://api.botframework.com",
                "aud": TEAMS_BOT_APP_ID,
                "serviceurl": service_url,
                "nbf": int((now - timedelta(seconds=10)).timestamp()),
                "exp": int((now + timedelta(minutes=5)).timestamp()),
            },
            self._pem,
            algorithm="RS256",
            headers={"kid": self.kid},
        )

    def entra_user_token(
        self,
        *,
        now: datetime,
        oid: str,
        auth_time: datetime,
        azp: str = TEAMS_BOT_APP_ID,
        roles: tuple[str, ...] = ("Approver",),
    ) -> str:
        return jwt.encode(
            {
                "iss": ENTRA_ISSUER,
                "aud": OPERATOR_AUDIENCE,
                "oid": oid,
                "idtyp": "user",
                "azp": azp,
                "roles": list(roles),
                "auth_time": int(auth_time.timestamp()),
                "nbf": int((now - timedelta(seconds=5)).timestamp()),
                "exp": int((now + timedelta(minutes=5)).timestamp()),
            },
            self._pem,
            algorithm="RS256",
            headers={"kid": self.kid},
        )

    def verify_operator_token(self, token: str) -> dict[str, object]:
        claims: dict[str, object] = jwt.decode(
            token,
            self._public,
            algorithms=["RS256"],
            audience=OPERATOR_AUDIENCE,
            issuer=ENTRA_ISSUER,
            options={"require": ["exp", "iss", "aud"]},
        )
        return claims


def _seed_action_park(
    dsn: str,
    *,
    approval_id: str,
    now: datetime,
    submitter_oid: str = SUBMITTER_OID,
) -> tuple[HilApprovalRequest, dict[str, Any]]:
    action_dict = {
        "action_id": f"action-{approval_id}",
        "action_type": "azure.aks.scale_nodepool",
        "target_resource_id": f"resource-{approval_id}",
    }
    action_hash = action_payload_hash(action_dict)
    idempotency_key = f"idem-{approval_id}"
    correlation_id = f"corr-{approval_id}"
    expires_at = (now + timedelta(minutes=20)).isoformat()
    park = {
        "approval_id": approval_id,
        "status": "pending",
        "correlation_id": correlation_id,
        "idempotency_key": idempotency_key,
        "request_fingerprint": action_hash,
        "action_hash": action_hash,
        "submitter_oid": submitter_oid,
        "parked_at": now.isoformat(),
        "action": action_dict,
        "approval_context": {
            "expires_at": expires_at,
            "required_role": "approver",
        },
        "metadata": {
            "decision_route": "action",
            "required_role": "approver",
            "correlation_id": correlation_id,
            "action_hash": action_hash,
            "expires_at": expires_at,
        },
    }
    with psycopg.connect(dsn) as conn:
        conn.execute(
            "INSERT INTO state_kv (key, value) VALUES (%s, %s::jsonb)",
            (f"hil_park:{approval_id}", json.dumps(park)),
        )
    request = HilApprovalRequest(
        approval_id=approval_id,
        correlation_id=correlation_id,
        action_id=action_dict["action_id"],
        action_type=action_dict["action_type"],
        rule_ids=("rule-941",),
        target_resource_ref=action_dict["target_resource_id"],
        blast_radius_summary="single nodepool",
        action_hash=action_hash,
        metadata={"idempotency_key": idempotency_key},
    )
    return request, park


class _CoreActionCoordinator:
    def __init__(self, store: PostgresStateStore) -> None:
        self.store = store
        self.resolved: list[dict[str, Any]] = []

    async def read_operator_decision_receipt(self, approval_id: str) -> Any:
        return await self.store.read_state(f"operator-hil-decision:{approval_id}")

    async def resolve(self, **kwargs: Any) -> Any:
        self.resolved.append(kwargs)
        return None


def _signed_slack_click(
    action: dict[str, Any],
    *,
    trigger_id: str,
    now: datetime,
) -> tuple[bytes, dict[str, str]]:
    payload = {
        "type": "block_actions",
        "team": {"id": SLACK_TEAM_ID},
        "user": {"id": SLACK_USER_ID},
        "trigger_id": trigger_id,
        "actions": [action],
    }
    raw = urlencode({"payload": json.dumps(payload, separators=(",", ":"))}).encode("utf-8")
    stamp = str(int(now.timestamp()))
    sig = hmac.new(
        SLACK_SIGNING_SECRET.encode("utf-8"),
        b"v0:" + stamp.encode("utf-8") + b":" + raw,
        hashlib.sha256,
    ).hexdigest()
    return raw, {
        "content-type": "application/x-www-form-urlencoded",
        "x-slack-request-timestamp": stamp,
        "x-slack-signature": f"v0={sig}",
    }


async def test_slack_a1_durable_outbox_handoff_nonce_race_and_decision_round_trip_postgres(
    database: str,
) -> None:
    now = datetime.now(UTC).replace(microsecond=0)
    core_store = PostgresStateStore(
        config=PostgresStateStoreConfig(dsn=_role(database, "fdai_core"))
    )
    operator_cfg = PostgresFamilyStoreConfig(dsn=_role(database, "fdai_operator"))
    operator_family = PostgresFamilyStore(operator_cfg)
    operator_iam = PostgresIamAdapters(
        operator_family,
        hil_decisions=PostgresHilDecisionStore(operator_cfg),
    )
    handoff_store = PostgresSlackHandoffStore(operator_cfg)

    approve_req, _ = _seed_action_park(database, approval_id="slack-a1-approve", now=now)
    reject_req, _ = _seed_action_park(database, approval_id="slack-a1-reject", now=now)
    unknown_req, _ = _seed_action_park(database, approval_id="slack-a1-unknown", now=now)

    posted_payloads: list[dict[str, Any]] = []
    should_fail = False

    def _slack_transport(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        posted_payloads.append(body)
        if should_fail:
            raise httpx.ReadTimeout("simulated ambiguous Slack timeout")
        ts = f"179375000{len(posted_payloads)}.000100"
        return httpx.Response(200, json={"ok": True, "channel": SLACK_CHANNEL_ID, "ts": ts})

    async with httpx.AsyncClient(transport=httpx.MockTransport(_slack_transport)) as slack_http:
        adapter = SlackHilAdapter(
            config=SlackHilAdapterConfig(
                api_url=SLACK_POST_URL,
                channel_id=SLACK_CHANNEL_ID,
                bot_token="fixture",
            ),
            http_client=slack_http,
        )
        outbox_channel = DurableSlackApprovalChannel(
            adapter=adapter,
            store=core_store,
            clock=lambda: now,
        )
        approve_receipt = await outbox_channel.send(approve_req)
        reject_receipt = await outbox_channel.send(reject_req)
        assert approve_receipt.channel_ref.startswith(f"slack:{SLACK_CHANNEL_ID}/")
        assert reject_receipt.channel_ref.startswith(f"slack:{SLACK_CHANNEL_ID}/")

        # Verify ambiguous/interrupted send is held as unknown and never reposted on restart
        should_fail = True
        with pytest.raises(HilChannelError, match="unknown"):
            await outbox_channel.send(unknown_req)
        should_fail = False
        unknown_state = await core_store.read_state(
            DurableSlackApprovalChannel._key("slack-a1-unknown", "initial")
        )
        assert unknown_state is not None and unknown_state["status"] == "unknown"
        restarted_outbox = DurableSlackApprovalChannel(
            adapter=adapter,
            store=core_store,
            clock=lambda: now + timedelta(minutes=1),
        )
        assert await restarted_outbox.reconcile_once() is False
        assert len(posted_payloads) == 3

    buttons_approve = posted_payloads[0]["blocks"][-1]["elements"]
    buttons_reject = posted_payloads[1]["blocks"][-1]["elements"]
    assert buttons_approve[0]["action_id"] == "fdai_hil_approve"
    assert buttons_reject[1]["action_id"] == "fdai_hil_reject"

    identity = _EphemeralRsaIdentity()
    authority_cfg = HilCallbackAuthorityConfig.from_environment(
        {
            "FDAI_SLACK_TEAM_ID": SLACK_TEAM_ID,
            "FDAI_SLACK_PRINCIPAL_MAP_JSON": json.dumps({SLACK_USER_ID: APPROVER_OID}),
        },
        group_ids={role: f"group-{role.value}" for role in OperatorRole},
    )
    bus = InMemoryEventBus()

    class _BusPublisher:
        async def publish(self, topic: str, key: str, payload: dict[str, object]) -> None:
            await bus.publish(topic, key, payload)

    decision_outbox = DurableHilDecisionOutboxPublisher(
        durable=operator_iam,
        publisher=_BusPublisher(),  # type: ignore[arg-type]
        topic=HIL_TOPIC,
        ledger=operator_iam,
        registry=operator_iam,
    )
    clock = [now]
    slack_app = Starlette(
        routes=make_slack_handoff_routes(
            store=handoff_store,
            signing_secret=SLACK_SIGNING_SECRET,
            config=authority_cfg,
            authenticator=OperatorAuthenticator(
                verifier=identity.verify_operator_token,
                group_ids={},
            ),
            registry=operator_iam,
            outbox=decision_outbox,
            audit=operator_iam,
            context_reader=operator_iam,
            console_origin="http://localhost:5273",
            clock=lambda: clock[0],
        )
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=slack_app),
        base_url="http://operator.local",
    ) as client:
        # 1. Prove concurrent PostgreSQL nonce CAS race allows at most 1 winner
        race_req, _ = _seed_action_park(database, approval_id="slack-a1-race", now=now)
        race_raw, race_headers = _signed_slack_click(
            {"type": "button", "action_id": "fdai_hil_approve", "value": race_req.approval_id},
            trigger_id="trigger-race-941",
            now=now,
        )
        race_click = await client.post(
            "/hil/slack/interaction",
            content=race_raw,
            headers=race_headers,
        )
        assert race_click.status_code == 200
        race_token = parse_qs(urlsplit(race_click.json()["text"].split()[-1]).query)["handoff"][0]
        race_digest = hashlib.sha256(race_token.encode("utf-8")).hexdigest()
        race_outcomes = await asyncio.gather(
            handoff_store.consume(race_digest),
            handoff_store.consume(race_digest),
            handoff_store.consume(race_digest),
        )
        assert sorted(race_outcomes) == [False, False, True]

        # 2. Complete authenticated Slack approve + reject round trips
        for button, expected_decision, trig in (
            (buttons_approve[0], "approve", "trigger-approve-941"),
            (buttons_reject[1], "reject", "trigger-reject-941"),
        ):
            raw, headers = _signed_slack_click(button, trigger_id=trig, now=clock[0])
            click_resp = await client.post("/hil/slack/interaction", content=raw, headers=headers)
            assert click_resp.status_code == 200
            # Duplicate click with same trigger_id is rejected
            dup_click = await client.post("/hil/slack/interaction", content=raw, headers=headers)
            assert dup_click.status_code == 409
            handoff_url = click_resp.json()["text"].split()[-1]
            token = parse_qs(urlsplit(handoff_url).query)["handoff"][0]
            route = f"/hil/slack/handoff/{token}"

            # Stale auth_time and wrong OID fail closed without consuming the nonce
            stale_jwt = identity.entra_user_token(
                now=clock[0] + timedelta(seconds=2),
                oid=APPROVER_OID,
                auth_time=clock[0] - timedelta(seconds=10),
            )
            wrong_jwt = identity.entra_user_token(
                now=clock[0] + timedelta(seconds=2),
                oid="00000000-0000-0000-0000-00000000b999",
                auth_time=clock[0] + timedelta(seconds=2),
            )
            clock[0] = now + timedelta(seconds=2)
            for bad_jwt in (stale_jwt, wrong_jwt):
                denied = await client.post(
                    route,
                    headers={"authorization": f"Bearer {bad_jwt}"},
                    json={"justification": "Reviewed blast radius and rollback."},
                )
                assert denied.status_code == 403

            fresh_jwt = identity.entra_user_token(
                now=clock[0],
                oid=APPROVER_OID,
                auth_time=clock[0],
            )
            decided = await client.post(
                route,
                headers={"authorization": f"Bearer {fresh_jwt}"},
                json={"justification": f"Slack A1 {expected_decision} verified."},
            )
            assert decided.status_code in (200, 202)
            assert decided.json()["decision"] == expected_decision

            # Consumed token cannot be replayed
            replay = await client.post(
                route,
                headers={"authorization": f"Bearer {fresh_jwt}"},
                json={"justification": "Replay attempt."},
            )
            assert replay.status_code == 410
            clock[0] = now

    coordinator = _CoreActionCoordinator(core_store)
    workflow_registry = StateStoreHilApprovalRegistry(store=core_store, clock=lambda: now)
    await _consume_hil_decisions(
        bus=bus,
        topic=HIL_TOPIC,
        coordinator=coordinator,
        stop=asyncio.Event(),
        workflow_registry=workflow_registry,
    )
    resolved_by_id = {item["approval_id"]: item for item in coordinator.resolved}
    assert set(resolved_by_id) == {"slack-a1-approve", "slack-a1-reject"}
    assert resolved_by_id["slack-a1-approve"]["decision"].value == "approve"
    assert resolved_by_id["slack-a1-reject"]["decision"].value == "reject"
    assert resolved_by_id["slack-a1-approve"]["approver_oid"] == APPROVER_OID


async def test_teams_a1_bot_activity_obo_round_trip_and_broker_replay_postgres(
    database: str,
) -> None:
    now = datetime.now(UTC).replace(microsecond=0)
    core_store = PostgresStateStore(
        config=PostgresStateStoreConfig(dsn=_role(database, "fdai_core"))
    )
    operator_cfg = PostgresFamilyStoreConfig(dsn=_role(database, "fdai_operator"))
    operator_family = PostgresFamilyStore(operator_cfg)
    operator_iam = PostgresIamAdapters(
        operator_family,
        hil_decisions=PostgresHilDecisionStore(operator_cfg),
    )

    approve_req, _ = _seed_action_park(database, approval_id="teams-a1-approve", now=now)
    reject_req, _ = _seed_action_park(database, approval_id="teams-a1-reject", now=now)

    rendered_cards: list[dict[str, Any]] = []

    def _teams_bot_transport(request: httpx.Request) -> httpx.Response:
        rendered_cards.append(json.loads(request.content.decode("utf-8")))
        return httpx.Response(201, json={"id": f"teams-card-{len(rendered_cards)}"})

    bot_identity = StaticWorkloadIdentity(
        audience="https://api.botframework.com/.default",
        token="fixture",  # noqa: S106 - synthetic test token
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(_teams_bot_transport)) as bot_http:
        teams_adapter = TeamsHilAdapter(
            config=TeamsHilAdapterConfig(
                webhook_url=f"{TEAMS_SERVICE_URL}/v3/conversations/{TEAMS_CHANNEL_ID}/activities",
                approval_audience=TEAMS_AUDIENCE,
            ),
            http_client=bot_http,
            identity=bot_identity,
        )
        await teams_adapter.send(approve_req)
        await teams_adapter.send(reject_req)
    assert len(rendered_cards) == 2

    identity = _EphemeralRsaIdentity()

    class _Jwks:
        async def get_keys(self) -> tuple[dict[str, Any], ...]:
            return identity.jwks()

    authority_cfg = HilCallbackAuthorityConfig.from_environment(
        {
            "FDAI_TEAMS_APPLICATION_ID": TEAMS_BOT_APP_ID,
            "FDAI_TEAMS_APPROVAL_TEAM_ID": TEAMS_TEAM_ID,
            "FDAI_TEAMS_APPROVAL_CHANNEL_ID": TEAMS_CHANNEL_ID,
            "FDAI_TEAMS_PRINCIPAL_MAP_JSON": json.dumps({APPROVER_OID: APPROVER_OID}),
        },
        group_ids={role: f"group-{role.value}" for role in OperatorRole},
    )
    authority = EntraHilCallbackAuthority(
        authenticator=OperatorAuthenticator(
            verifier=identity.verify_operator_token,
            group_ids={},
        ),
        config=authority_cfg,
    )
    normalizer = TeamsHilCallbackNormalizer(
        config=TeamsHilCallbackConfig(
            application_id=TEAMS_BOT_APP_ID,
            tenant_id=TEAMS_TENANT_ID,
            team_id=TEAMS_TEAM_ID,
            channel_id=TEAMS_CHANNEL_ID,
            allowed_service_urls=frozenset({TEAMS_SERVICE_URL}),
        ),
        tokens=TeamsServiceTokenVerifier(
            config=TeamsTokenConfig(application_id=TEAMS_BOT_APP_ID),
            jwks=_Jwks(),
        ),
    )

    bus = InMemoryEventBus()
    broker_down = [True]

    class _FlakyBusPublisher:
        async def publish(self, topic: str, key: str, payload: dict[str, object]) -> None:
            if broker_down[0]:
                raise RuntimeError("simulated transient broker outage")
            await bus.publish(topic, key, payload)

    flaky_publisher = _FlakyBusPublisher()
    decision_outbox = DurableHilDecisionOutboxPublisher(
        durable=operator_iam,
        publisher=flaky_publisher,  # type: ignore[arg-type]
        topic=HIL_TOPIC,
        ledger=operator_iam,
        registry=operator_iam,
    )
    drainer = HilDecisionOutboxDrainer(
        store=operator_family,
        registry=operator_iam,
        publisher=flaky_publisher,  # type: ignore[arg-type]
        topic=HIL_TOPIC,
    )
    teams_app = Starlette(
        routes=[
            make_hil_teams_callback_route(
                normalizer=normalizer,
                authority=authority,
                registry=operator_iam,
                outbox=decision_outbox,
                audit=operator_iam,
                context_reader=operator_iam,
                clock=lambda: now,
            )
        ]
    )

    def _invoke_activity(
        *,
        approval_id: str,
        action_hash: str,
        idempotency_key: str,
        correlation_id: str,
        decision: str,
        actor_oid: str = APPROVER_OID,
        extra_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        obo_jwt = identity.entra_user_token(
            now=now,
            oid=actor_oid,
            auth_time=now,
        )
        action_data: dict[str, Any] = {
            "approval_id": approval_id,
            "correlation_id": correlation_id,
            "idempotency_key": idempotency_key,
            "action_hash": action_hash,
            "decision": decision,
            "audience": TEAMS_AUDIENCE,
            "justification": f"Teams A1 {decision} verified.",
        }
        if extra_data:
            action_data.update(extra_data)
        return {
            "type": "invoke",
            "name": "adaptiveCard/action",
            "id": f"invoke-{approval_id}-{decision}",
            "timestamp": now.isoformat().replace("+00:00", "Z"),
            "serviceUrl": TEAMS_SERVICE_URL,
            "channelId": "msteams",
            "from": {"id": "29:teams-user", "aadObjectId": actor_oid},
            "conversation": {"id": f"{TEAMS_CHANNEL_ID};messageid=1", "tenantId": TEAMS_TENANT_ID},
            "channelData": {
                "tenant": {"id": TEAMS_TENANT_ID},
                "team": {"id": TEAMS_TEAM_ID},
                "channel": {"id": TEAMS_CHANNEL_ID},
            },
            "value": {
                "action": {
                    "type": "Action.Execute",
                    "verb": HIL_DECISION_ACTION,
                    "data": action_data,
                },
                "authentication": {"token": obo_jwt},
            },
        }

    service_jwt = identity.bot_service_token(now=now)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=teams_app),
        base_url="http://operator.local",
    ) as client:
        # Tampered card with extra field is refused before authority/decision
        tampered = await client.post(
            "/hil/teams-activity",
            headers={"authorization": f"Bearer {service_jwt}"},
            json=_invoke_activity(
                approval_id=approve_req.approval_id,
                action_hash=approve_req.action_hash,
                idempotency_key=approve_req.metadata["idempotency_key"],
                correlation_id=approve_req.correlation_id,
                decision="approve",
                extra_data={"roles": ["Owner"]},
            ),
        )
        assert tampered.status_code == 400

        # Approve while broker is down -> 503 delivery pending (durably persisted in outbox)
        approve_resp = await client.post(
            "/hil/teams-activity",
            headers={"authorization": f"Bearer {service_jwt}"},
            json=_invoke_activity(
                approval_id=approve_req.approval_id,
                action_hash=approve_req.action_hash,
                idempotency_key=approve_req.metadata["idempotency_key"],
                correlation_id=approve_req.correlation_id,
                decision="approve",
            ),
        )
        assert approve_resp.status_code == 503
        persisted_approve = await operator_iam.get_decision_by_approval_id(approve_req.approval_id)
        assert persisted_approve is not None and persisted_approve.delivered is False

        # Restore broker, drain outbox for approve, and submit reject with broker healthy
        broker_down[0] = False
        assert await drainer.run_once() is True

        reject_resp = await client.post(
            "/hil/teams-activity",
            headers={"authorization": f"Bearer {service_jwt}"},
            json=_invoke_activity(
                approval_id=reject_req.approval_id,
                action_hash=reject_req.action_hash,
                idempotency_key=reject_req.metadata["idempotency_key"],
                correlation_id=reject_req.correlation_id,
                decision="reject",
            ),
        )
        assert reject_resp.status_code == 200
        assert reject_resp.json()["delivered"] is True

    coordinator = _CoreActionCoordinator(core_store)
    workflow_registry = StateStoreHilApprovalRegistry(store=core_store, clock=lambda: now)
    await _consume_hil_decisions(
        bus=bus,
        topic=HIL_TOPIC,
        coordinator=coordinator,
        stop=asyncio.Event(),
        workflow_registry=workflow_registry,
    )
    resolved_by_id = {item["approval_id"]: item for item in coordinator.resolved}
    assert set(resolved_by_id) == {"teams-a1-approve", "teams-a1-reject"}
    assert resolved_by_id["teams-a1-approve"]["decision"].value == "approve"
    assert resolved_by_id["teams-a1-reject"]["decision"].value == "reject"
    assert resolved_by_id["teams-a1-approve"]["approver_oid"] == APPROVER_OID
