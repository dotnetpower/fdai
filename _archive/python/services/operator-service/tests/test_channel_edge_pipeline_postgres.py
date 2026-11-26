"""Live PostgreSQL join for the Operator semantic channel pipeline."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import runpy
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import patch
from uuid import uuid4

import httpx
import jwt
import psycopg
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fdai_operator_service.families.conversation.channel_delivery_models import (
    ChannelDeliveryState,
    ChannelKind,
)
from fdai_operator_service.families.conversation.channel_edge.models import (
    AuthenticatedInboundTurn,
    ChannelDeliveryReceipt,
    InboundChannelTurn,
)
from fdai_operator_service.families.conversation.channel_edge.pipeline import (
    ChannelDeliveryPipeline,
    ChannelPrincipalContext,
)
from fdai_operator_service.families.conversation.channel_edge.publishers import (
    ChannelAccessToken,
    TeamsResponsePublisher,
)
from fdai_operator_service.families.conversation.channel_edge.queues import (
    TeamsEndpointRegistry,
    TeamsIngressQueue,
)
from fdai_operator_service.families.conversation.channel_edge.runtime import (
    ChannelEdgeRuntime,
    create_channel_edge_app,
)
from fdai_operator_service.families.conversation.channel_edge.teams_auth import (
    TeamsServiceTokenVerifier,
    TeamsTokenConfig,
)
from fdai_operator_service.families.conversation.channel_edge.teams_ingress import (
    TeamsIngressConfig,
    TeamsIngressVerifier,
)
from fdai_operator_service.families.conversation.channel_edge.worker import (
    ChannelDeliveryWorker,
    ChannelDeliveryWorkerConfig,
)
from fdai_operator_service.families.conversation.channel_message_ledger import (
    PostgresChannelMessageLedger,
    PostgresChannelMessageLedgerConfig,
)
from fdai_operator_service.families.conversation.contracts import (
    ConversationProposal,
    ConversationResponse,
    ConversationStreamRequest,
    OutboxReceipt,
    PrincipalScope,
    StreamEvent,
)
from fdai_operator_service.families.conversation.postgres_channel_binding import (
    PostgresChannelBindingConfig,
    PostgresPrincipalChannelBindingStore,
)
from fdai_operator_service.families.conversation.postgres_channel_delivery import (
    PostgresChannelDeliveryConfig,
    PostgresChannelDeliveryStore,
)
from fdai_operator_service.families.conversation.presentation_artifact_v3 import (
    assemble_presentation_artifact_v3,
)
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

_NOW = datetime(2026, 8, 19, 21, 0, tzinfo=UTC)
_ROOT = Path(__file__).resolve().parents[3]
_BASE_MIGRATION = _ROOT / "alembic/versions/20260720_0047_conversation_delivery.py"
_EDGE_MIGRATION = (
    _ROOT
    / "service-migrations/branches/operator-service/versions"
    / "20260819_operator_a3_channel_delivery.py"
)


def _dsn(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        pytest.skip(f"{name} is unset")
    return value.replace("postgresql+psycopg://", "postgresql://", 1)


@pytest.fixture(scope="module", autouse=True)
def _ensure_channel_postgres_dsns() -> Iterator[None]:
    if os.environ.get("FDAI_ADMIN_DATABASE_URL", "").strip():
        yield
        return
    raw_base = os.environ.get("FDAI_DATABASE_URL", "").strip()
    if not raw_base:
        yield
        return
    base_dsn = raw_base.replace("postgresql+psycopg://", "postgresql://", 1)
    params = conninfo_to_dict(base_dsn)
    if params.get("host") not in {"127.0.0.1", "localhost", "::1"}:
        pytest.fail("channel PostgreSQL integration tests require a loopback fixture")
    dbname = f"fdai_channel_edge_{uuid4().hex[:12]}"
    statements: list[str] = []
    for path in (_BASE_MIGRATION, _EDGE_MIGRATION):
        module = runpy.run_path(str(path))
        with patch("alembic.op.execute", side_effect=statements.append):
            module["upgrade"]()
    with psycopg.connect(base_dsn, autocommit=True) as admin:
        admin.execute(
            """DO $roles$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='fdai_operator') THEN
                CREATE ROLE fdai_operator NOLOGIN NOSUPERUSER NOBYPASSRLS;
            END IF;
            END; $roles$"""
        )
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(dbname)))
    disposable_admin = make_conninfo(base_dsn, dbname=dbname)
    disposable_operator = make_conninfo(disposable_admin, options="-c role=fdai_operator")
    prev_admin = os.environ.get("FDAI_ADMIN_DATABASE_URL")
    prev_db = os.environ.get("FDAI_DATABASE_URL")
    try:
        with psycopg.connect(disposable_admin) as conn:
            conn.execute("GRANT USAGE ON SCHEMA public TO fdai_operator")
            for statement in statements:
                conn.execute(statement)
        os.environ["FDAI_ADMIN_DATABASE_URL"] = disposable_admin
        os.environ["FDAI_DATABASE_URL"] = disposable_operator
        yield
    finally:
        if prev_admin is None:
            os.environ.pop("FDAI_ADMIN_DATABASE_URL", None)
        else:
            os.environ["FDAI_ADMIN_DATABASE_URL"] = prev_admin
        if prev_db is None:
            os.environ.pop("FDAI_DATABASE_URL", None)
        else:
            os.environ["FDAI_DATABASE_URL"] = prev_db
        with psycopg.connect(base_dsn, autocommit=True) as admin:
            admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(dbname)))


class _Principals:
    async def resolve(self, principal_id: str) -> ChannelPrincipalContext:
        return ChannelPrincipalContext(
            scope=PrincipalScope(principal_id, frozenset({"Reader"})),
            scope_ref="scope://pipeline/live",
        )


class _Semantic:
    async def append(self, proposal: ConversationProposal) -> OutboxReceipt:
        return OutboxReceipt(
            proposal_id="pipeline-live-proposal",
            duplicate=False,
            response=ConversationResponse(body={"accepted": True}, status_code=202),
        )

    async def open(self, request: ConversationStreamRequest) -> _Stream:
        del request
        return _Stream()


class _Stream:
    def __init__(self) -> None:
        self._sent = False

    def __aiter__(self) -> _Stream:
        return self

    async def __anext__(self) -> StreamEvent:
        if self._sent:
            raise StopAsyncIteration
        self._sent = True
        return StreamEvent(
            event="done",
            event_id="1",
            data={
                "status": "answered",
                "answer": "The live pipeline evidence is verified.",
                "verification": {
                    "status": "verified",
                    "authority": "ontology-query",
                    "evidence_refs": ["evidence:pipeline-live"],
                },
            },
        )

    async def aclose(self) -> None:
        return None


class _Publisher:
    async def send(self, message):  # type: ignore[no-untyped-def]
        return ChannelDeliveryReceipt(
            channel_kind=message.channel_kind,
            channel_id=message.channel_id,
            message_id="pipeline-live-provider-message",
            degraded_to_text=message.degraded_to_text,
        )


@pytest.mark.integration
async def test_operator_pipeline_joins_all_durable_delivery_owners() -> None:
    admin_dsn = _dsn("FDAI_ADMIN_DATABASE_URL")
    operator_dsn = _dsn("FDAI_DATABASE_URL")
    suffix = uuid4().hex
    channel_id = f"pipeline-channel-{suffix}"
    message_id = f"pipeline-message-{suffix}"
    principal_id = f"pipeline-principal-{suffix}"
    inbound_key = hashlib.sha256(f"slack\0{channel_id}\0{message_id}".encode()).hexdigest()
    delivery_id = f"channel-delivery:{inbound_key}"
    messages = PostgresChannelMessageLedger(
        config=PostgresChannelMessageLedgerConfig(dsn=operator_dsn)
    )
    bindings = PostgresPrincipalChannelBindingStore(
        config=PostgresChannelBindingConfig(dsn=operator_dsn)
    )
    deliveries = PostgresChannelDeliveryStore(
        config=PostgresChannelDeliveryConfig(dsn=operator_dsn)
    )
    semantic = _Semantic()
    pipeline = ChannelDeliveryPipeline(
        messages=messages,
        principals=_Principals(),
        bindings=bindings,
        deliveries=deliveries,
        semantic_outbox=semantic,
        semantic_streams=semantic,
        publishers={ChannelKind.SLACK: _Publisher()},
        clock=lambda: _NOW,
    )
    worker = ChannelDeliveryWorker(
        store=deliveries,
        handler=pipeline,
        config=ChannelDeliveryWorkerConfig(channels=(ChannelKind.SLACK,)),
        clock=lambda: _NOW,
    )
    authenticated = AuthenticatedInboundTurn(
        turn=InboundChannelTurn(
            channel_kind=ChannelKind.SLACK,
            channel_id=channel_id,
            message_id=message_id,
            sender_id=f"pipeline-sender-{suffix}",
            text="Verify the live pipeline evidence.",
            thread_id=f"pipeline-thread-{suffix}",
        ),
        principal_id=principal_id,
        verification_ref=f"pipeline-verification-{suffix}",
    )
    try:
        assert await messages.probe_readiness() is True
        assert await bindings.probe_readiness() is True
        assert await deliveries.probe_readiness() is True
        await worker.initialize()
        first = await pipeline.process(authenticated)
        duplicate = await pipeline.process(authenticated)

        assert first.state is ChannelDeliveryState.DELIVERED
        assert duplicate == type(duplicate)(delivery_id, ChannelDeliveryState.DELIVERED, True)
        snapshot = await deliveries.snapshot(limit=500)
        attempts = [item for item in snapshot.attempts if item.delivery_id == delivery_id]
        acknowledgements = [
            item for item in snapshot.acknowledgements if item.delivery_id == delivery_id
        ]
        assert len(attempts) == 1
        assert attempts[0].outcome is ChannelDeliveryState.DELIVERED
        assert len(acknowledgements) == 1
        assert acknowledgements[0].provider_message_id == "pipeline-live-provider-message"
        async with await psycopg.AsyncConnection.connect(operator_dsn) as connection:
            claim = await connection.execute(
                "SELECT state FROM conversation_channel_message_claim WHERE idempotency_key = %s",
                (inbound_key,),
            )
            assert await claim.fetchone() == ("completed",)
    finally:
        async with await psycopg.AsyncConnection.connect(admin_dsn) as connection:
            await connection.execute(
                "DELETE FROM conversation_outbound_delivery WHERE delivery_id = %s",
                (delivery_id,),
            )
            await connection.execute(
                "DELETE FROM principal_conversation_binding WHERE principal_id = %s",
                (principal_id,),
            )
            await connection.execute(
                "DELETE FROM conversation_channel_message_claim WHERE idempotency_key = %s",
                (inbound_key,),
            )
            await connection.commit()


class _LifecycleNoop:
    async def start(self) -> None:
        return None

    async def aclose(self) -> None:
        return None

    def workers_ready(self) -> bool:
        return True


class _TeamsTokenProvider:
    async def get_token(self, audience: str) -> ChannelAccessToken:
        return ChannelAccessToken(token="fixture", audience=audience)


class _TeamsSemantic:
    def __init__(self) -> None:
        self.proposals: list[ConversationProposal] = []

    async def append(self, proposal: ConversationProposal) -> OutboxReceipt:
        self.proposals.append(proposal)
        return OutboxReceipt(
            proposal_id=f"teams-a3-proposal-{len(self.proposals)}",
            duplicate=False,
            response=ConversationResponse(body={"accepted": True}, status_code=202),
        )

    async def open(self, request: ConversationStreamRequest) -> _TeamsV3Stream:
        del request
        return _TeamsV3Stream()


class _TeamsV3Stream:
    def __init__(self) -> None:
        self._sent = False

    def __aiter__(self) -> _TeamsV3Stream:
        return self

    async def __anext__(self) -> StreamEvent:
        if self._sent:
            raise StopAsyncIteration
        self._sent = True
        evidence_ref = "ontology-function:teams-a3-parity"
        artifact = assemble_presentation_artifact_v3(
            layout="operational_brief",
            blocks=(
                {
                    "slot_id": "overview",
                    "kind": "summary",
                    "title": "Teams A3 runtime parity",
                    "emphasis": "primary",
                    "collapsed": False,
                    "evidence_refs": [evidence_ref],
                    "data": {
                        "items": [
                            {
                                "label": "Channel state",
                                "value": "validated",
                                "tone": "positive",
                            },
                            {
                                "label": "Execution authority",
                                "value": "none",
                                "tone": "neutral",
                            },
                        ]
                    },
                },
                {
                    "slot_id": "limitations",
                    "kind": "callout",
                    "title": "Operational boundary",
                    "emphasis": "supporting",
                    "collapsed": False,
                    "evidence_refs": [evidence_ref],
                    "data": {
                        "tone": "warning",
                        "lines": ["Draft and read-only turns never carry executor authority."],
                    },
                },
            ),
            evidence_refs=(evidence_ref,),
            locale="en",
            input_kinds=("verified_semantic_result", "presentation_context"),
        )
        return StreamEvent(
            event="done",
            event_id="1",
            data={
                "status": "answered",
                "answer": "Teams A3 edge verified with schema-v3 operational brief.",
                "verification": {
                    "status": "verified",
                    "authority": "ontology-query",
                    "evidence_refs": [evidence_ref],
                },
                "presentation_artifact": artifact,
            },
        )

    async def aclose(self) -> None:
        return None


@pytest.mark.integration
async def test_teams_a3_edge_runtime_round_trip_schema_v3_edit_and_restart_dedup_postgres() -> None:
    admin_dsn = _dsn("FDAI_ADMIN_DATABASE_URL")
    operator_dsn = _dsn("FDAI_DATABASE_URL")
    suffix = uuid4().hex
    service_url = "https://smba.trafficmanager.invalid/amer"
    tenant_id = f"teams-tenant-{suffix}"
    aad_oid = f"teams-aad-{suffix}"
    principal_id = f"teams-principal-{suffix}"
    conversation_id = f"19:teams-conv-{suffix}@thread.tacv2"
    activity_id = f"teams-msg-{suffix}"
    inbound_key = hashlib.sha256(f"teams\0{conversation_id}\0{activity_id}".encode()).hexdigest()
    delivery_id = f"channel-delivery:{inbound_key}"
    ambiguous_delivery_id = f"channel-delivery:teams-ambiguous-{suffix}"

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private_key.public_key()))
    public_jwk.update({"kid": "teams-edge-kid", "use": "sig", "alg": "RS256"})

    class _Jwks:
        async def get_keys(self) -> tuple[dict[str, Any], ...]:
            return (public_jwk,)

    now = datetime.now(UTC).replace(microsecond=0)
    service_jwt = jwt.encode(
        {
            "iss": "https://api.botframework.com",
            "aud": "teams-a3-bot-app",
            "serviceurl": service_url,
            "nbf": int((now - timedelta(seconds=10)).timestamp()),
            "exp": int((now + timedelta(minutes=5)).timestamp()),
        },
        private_pem,
        algorithm="RS256",
        headers={"kid": "teams-edge-kid"},
    )
    provider_requests: list[tuple[str, str, dict[str, Any]]] = []

    def _connector_transport(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        provider_requests.append((request.method, str(request.url), body))
        if request.method == "PUT":
            return httpx.Response(200, json={"id": "teams-activity-v3-1-edited"})
        return httpx.Response(201, json={"id": "teams-activity-v3-1"})

    semantic = _TeamsSemantic()

    def _build_runtime(
        http_client: httpx.AsyncClient,
        *,
        clock_now: datetime,
    ) -> tuple[
        ChannelEdgeRuntime,
        PostgresChannelMessageLedger,
        PostgresPrincipalChannelBindingStore,
        PostgresChannelDeliveryStore,
        TeamsResponsePublisher,
    ]:
        messages = PostgresChannelMessageLedger(
            config=PostgresChannelMessageLedgerConfig(dsn=operator_dsn)
        )
        bindings = PostgresPrincipalChannelBindingStore(
            config=PostgresChannelBindingConfig(dsn=operator_dsn)
        )
        deliveries = PostgresChannelDeliveryStore(
            config=PostgresChannelDeliveryConfig(dsn=operator_dsn)
        )
        endpoints = TeamsEndpointRegistry(allowed_service_urls=frozenset({service_url}))
        teams_queue = TeamsIngressQueue(
            ingress=TeamsIngressVerifier(
                config=TeamsIngressConfig(
                    tenant_id=tenant_id,
                    allowed_service_urls=frozenset({service_url}),
                    principal_by_aad_object_id={aad_oid: principal_id},
                ),
                tokens=TeamsServiceTokenVerifier(
                    config=TeamsTokenConfig(application_id="teams-a3-bot-app"),
                    jwks=_Jwks(),
                ),
            ),
            endpoints=endpoints,
        )
        publisher = TeamsResponsePublisher(
            http_client=http_client,
            identity=_TeamsTokenProvider(),
            endpoints=endpoints,
        )
        pipeline = ChannelDeliveryPipeline(
            messages=messages,
            principals=_Principals(),
            bindings=bindings,
            deliveries=deliveries,
            semantic_outbox=semantic,
            semantic_streams=semantic,
            publishers={ChannelKind.TEAMS: publisher},
            clock=lambda: clock_now,
        )
        worker = ChannelDeliveryWorker(
            store=deliveries,
            handler=pipeline,
            config=ChannelDeliveryWorkerConfig(
                channels=(ChannelKind.TEAMS,),
                idle_seconds=0.02,
            ),
            clock=lambda: clock_now,
        )
        runtime = ChannelEdgeRuntime(
            enabled_channels=frozenset({ChannelKind.TEAMS}),
            pipeline=pipeline,
            worker=worker,
            semantic_transport=_LifecycleNoop(),
            semantic_bridge=_LifecycleNoop(),
            teams_queue=teams_queue,
            readiness_checks=(
                messages.probe_readiness,
                bindings.probe_readiness,
                deliveries.probe_readiness,
            ),
        )
        return runtime, messages, bindings, deliveries, publisher

    activity_body = json.dumps(
        {
            "type": "message",
            "id": activity_id,
            "channelId": "msteams",
            "serviceUrl": service_url,
            "from": {"id": f"29:{suffix}", "aadObjectId": aad_oid},
            "conversation": {
                "id": conversation_id,
                "tenantId": tenant_id,
            },
            "channelData": {"tenant": {"id": tenant_id}},
            "text": "<at>FDAI</at> Summarize the verified Teams A3 runtime parity.",
        }
    ).encode("utf-8")

    try:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(_connector_transport)
        ) as provider_http:
            runtime1, _messages1, _bindings1, deliveries1, publisher1 = _build_runtime(
                provider_http,
                clock_now=now,
            )
            app1 = create_channel_edge_app(runtime1)
            async with app1.router.lifespan_context(app1):
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app1),
                    base_url="http://channel-edge.local",
                ) as edge_client:
                    ready_resp = await edge_client.get("/health/ready")
                    assert ready_resp.status_code == 200
                    post_resp = await edge_client.post(
                        "/webhooks/teams/activities",
                        content=activity_body,
                        headers={
                            "authorization": f"Bearer {service_jwt}",
                            "content-type": "application/json",
                        },
                    )
                    assert post_resp.status_code == 202
                    for _ in range(50):
                        snap = await deliveries1.snapshot(limit=500)
                        if any(
                            item.delivery_id == delivery_id
                            and item.state is ChannelDeliveryState.DELIVERED
                            for item in snap.deliveries
                        ):
                            break
                        await asyncio.sleep(0.02)

                assert len(provider_requests) == 1
                method, url, posted_card = provider_requests[0]
                assert method == "POST"
                assert url.endswith("/activities")
                assert posted_card["type"] == "message"
                card_content = posted_card["attachments"][0]["content"]
                assert card_content["version"] == "1.5"
                fallback_text = str(card_content["body"][0]["text"])
                assert "Teams A3 edge verified with schema-v3 operational brief." in fallback_text
                assert "Draft and read-only turns never carry executor authority." in fallback_text
                assert "Execution authority: none" in fallback_text
                assert any(block.get("type") == "Container" for block in card_content["body"])

                # Verify Teams edit/progress update over PUT .../activities/{activity_id}
                from fdai_operator_service.families.conversation.channel_edge.models import (
                    RenderedChannelMessage,
                )

                edit_receipt = await publisher1.send(
                    RenderedChannelMessage(
                        channel_kind=ChannelKind.TEAMS,
                        channel_id=conversation_id,
                        payload=posted_card,
                        degraded_to_text=False,
                        edit_message_id="teams-activity-v3-1",
                    )
                )
                assert edit_receipt.message_id == "teams-activity-v3-1-edited"
                assert len(provider_requests) == 2
                assert provider_requests[1][0] == "PUT"
                assert provider_requests[1][1].endswith("/activities/teams-activity-v3-1")

            # Restart a second runtime instance against the same PostgreSQL tables
            # and verify both replay deduplication and interrupted sending -> ambiguous recovery.
            from fdai_operator_service.families.conversation.channel_delivery_models import (
                ChannelDeliveryRecord,
                channel_response_digest,
            )

            active_bindings = await _bindings1.list_for_principal(principal_id=principal_id)
            assert len(active_bindings) == 1
            interrupted_response = {
                "status": "answered",
                "answer": "Interrupted Teams send before restart.",
                "verification": {
                    "status": "verified",
                    "authority": "ontology-query",
                    "evidence_refs": ["ontology-function:teams-a3-parity"],
                },
                "execution_authority": False,
            }
            await deliveries1.put(
                ChannelDeliveryRecord(
                    delivery_id=ambiguous_delivery_id,
                    idempotency_key=ambiguous_delivery_id,
                    principal_id=principal_id,
                    scope_ref="scope://pipeline/live",
                    conversation_id=active_bindings[0].conversation_id,
                    binding_id=active_bindings[0].binding_id,
                    channel_kind=ChannelKind.TEAMS,
                    response=interrupted_response,
                    response_digest=channel_response_digest(interrupted_response),
                    state=ChannelDeliveryState.PENDING,
                    created_at=now,
                    due_at=now,
                    expires_at=now + timedelta(minutes=10),
                    retention_until=now + timedelta(days=1),
                )
            )
            claimed_interrupted = await deliveries1.claim_due(
                channel_kind=ChannelKind.TEAMS,
                worker_id="crashed-worker",
                now=now,
                lease_seconds=1,
                limit=1,
            )
            assert (
                len(claimed_interrupted) == 1
                and claimed_interrupted[0].delivery_id == ambiguous_delivery_id
            )

            restart_now = now + timedelta(seconds=5)
            runtime2, _messages2, _bindings2, deliveries2, _publisher2 = _build_runtime(
                provider_http,
                clock_now=restart_now,
            )
            app2 = create_channel_edge_app(runtime2)
            async with app2.router.lifespan_context(app2):
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app2),
                    base_url="http://channel-edge.local",
                ) as edge_client2:
                    replay_resp = await edge_client2.post(
                        "/webhooks/teams/activities",
                        content=activity_body,
                        headers={
                            "authorization": f"Bearer {service_jwt}",
                            "content-type": "application/json",
                        },
                    )
                    assert replay_resp.status_code == 202
                    await asyncio.sleep(0.05)

            assert len(semantic.proposals) == 1
            assert len(provider_requests) == 2
            final_snap = await deliveries2.snapshot(limit=500)
            delivered_rows = [
                item for item in final_snap.deliveries if item.delivery_id == delivery_id
            ]
            ambiguous_rows = [
                item for item in final_snap.deliveries if item.delivery_id == ambiguous_delivery_id
            ]
            assert len(delivered_rows) == 1
            assert delivered_rows[0].state is ChannelDeliveryState.DELIVERED
            assert len(ambiguous_rows) == 1
            assert ambiguous_rows[0].state is ChannelDeliveryState.AMBIGUOUS
            assert ambiguous_rows[0].duplicate_risk is True
            assert [
                item.provider_message_id
                for item in final_snap.acknowledgements
                if item.delivery_id == delivery_id
            ] == ["teams-activity-v3-1"]
    finally:
        async with await psycopg.AsyncConnection.connect(admin_dsn) as connection:
            await connection.execute(
                "DELETE FROM conversation_outbound_delivery WHERE delivery_id = ANY(%s)",
                ([delivery_id, ambiguous_delivery_id],),
            )
            await connection.execute(
                "DELETE FROM principal_conversation_binding WHERE principal_id = %s",
                (principal_id,),
            )
            await connection.execute(
                "DELETE FROM conversation_channel_message_claim WHERE idempotency_key = %s",
                (inbound_key,),
            )
            await connection.commit()
