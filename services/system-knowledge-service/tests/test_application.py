from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import UTC, datetime
from pathlib import Path

from fdai_system_knowledge_service.application import create_app
from fdai_system_knowledge_service.config import TeamsTransport
from fdai_system_knowledge_service.runtime import (
    KnowledgeTurnResult,
    OutgoingWebhookTurnResult,
)
from httpx import ASGITransport, AsyncClient


class _Runtime:
    def __init__(self) -> None:
        self.transport = TeamsTransport.BOT_FRAMEWORK
        self.ready = False
        self.closed = False
        self.bodies: list[bytes] = []

    async def start(self) -> None:
        self.ready = True

    async def aclose(self) -> None:
        self.ready = False
        self.closed = True

    async def handle(
        self,
        *,
        body: bytes,
        authorization: str,
        received_at: datetime,
    ) -> KnowledgeTurnResult:
        assert authorization == "Bearer service-token"
        assert received_at.tzinfo is not None
        self.bodies.append(body)
        return KnowledgeTurnResult(state="delivered")


async def test_app_exposes_only_health_and_teams_message_routes() -> None:
    runtime = _Runtime()
    app = create_app(runtime=runtime)

    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            live = await client.get("/health/live")
            ready = await client.get("/health/ready")
            delivered = await client.post(
                "/api/teams/messages",
                content=b"{}",
                headers={
                    "content-type": "application/json",
                    "authorization": "Bearer service-token",
                },
            )
            missing = await client.get("/v1/query")

    assert live.status_code == ready.status_code == 200
    assert delivered.status_code == 202
    assert delivered.json() == {"status": "delivered"}
    assert runtime.bodies == [b"{}"]
    assert missing.status_code == 404
    assert runtime.closed is True


async def test_app_rejects_non_json_and_oversized_body_before_runtime() -> None:
    runtime = _Runtime()
    app = create_app(runtime=runtime)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        media = await client.post("/api/teams/messages", content=b"{}")
        large = await client.post(
            "/api/teams/messages",
            content=b"x" * 256_001,
            headers={"content-type": "application/json"},
        )

    assert media.status_code == 415
    assert large.status_code == 413
    assert runtime.bodies == []


class _OutgoingRuntime(_Runtime):
    def __init__(self) -> None:
        super().__init__()
        self.transport = TeamsTransport.OUTGOING_WEBHOOK

    async def handle(
        self,
        *,
        body: bytes,
        authorization: str,
        received_at: datetime,
    ) -> OutgoingWebhookTurnResult:
        assert authorization == "HMAC example"
        assert received_at.tzinfo is not None
        self.bodies.append(body)
        return OutgoingWebhookTurnResult(
            state="responded",
            payload={"type": "message", "text": "verified answer"},
        )


async def test_app_returns_outgoing_webhook_response_and_disables_bot_route() -> None:
    runtime = _OutgoingRuntime()
    app = create_app(runtime=runtime)

    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/api/teams/outgoing-webhook",
                content=b"{}",
                headers={
                    "content-type": "application/json",
                    "authorization": "HMAC example",
                },
            )
            bot = await client.post(
                "/api/teams/messages",
                content=b"{}",
                headers={"content-type": "application/json"},
            )

    assert response.status_code == 200
    assert response.json() == {"type": "message", "text": "verified answer"}
    assert bot.status_code == 404
    assert runtime.bodies == [b"{}"]


async def test_real_outgoing_webhook_chain_returns_cited_replay_safe_answer(
    tmp_path: Path,
) -> None:
    signing_key = b"k" * 32
    body = json.dumps(
        {
            "type": "message",
            "id": "message-example",
            "timestamp": datetime.now(UTC).isoformat(),
            "channelId": "msteams",
            "locale": "en-US",
            "conversation": {
                "id": "conversation-example",
                "conversationType": "channel",
                "tenantId": "tenant-example",
            },
            "recipient": {"id": "outgoing-webhook-example"},
            "from": {"aadObjectId": "aad-user-example"},
            "channelData": {
                "tenant": {"id": "tenant-example"},
                "team": {"id": "team-example"},
                "channel": {"id": "channel-example"},
            },
            "text": "<at>FDAI-bot</at> How does FDAI keep actions safe?",
            "entities": [
                {
                    "type": "mention",
                    "text": "<at>FDAI-bot</at>",
                    "mentioned": {
                        "id": "outgoing-webhook-example",
                        "name": "FDAI-bot",
                    },
                }
            ],
        },
        separators=(",", ":"),
    ).encode()
    signature = base64.b64encode(hmac.new(signing_key, body, hashlib.sha256).digest()).decode()
    app = create_app(
        {
            "FDAI_EXECUTION_VENUE": "local",
            "FDAI_SYSTEM_KNOWLEDGE_LEDGER_PATH": str(tmp_path / "ledger.sqlite3"),
            "FDAI_SYSTEM_KNOWLEDGE_TEAMS_TRANSPORT": "outgoing_webhook",
            "FDAI_SYSTEM_KNOWLEDGE_TEAMS_TENANT_ID": "tenant-example",
            "FDAI_SYSTEM_KNOWLEDGE_TEAMS_TEAM_IDS_JSON": '["team-example"]',
            "FDAI_SYSTEM_KNOWLEDGE_TEAMS_CHANNEL_IDS_JSON": '["channel-example"]',
            "FDAI_SYSTEM_KNOWLEDGE_TEAMS_PRINCIPAL_MAP_JSON": (
                '{"aad-user-example":"knowledge-reader-example"}'
            ),
            "FDAI_SYSTEM_KNOWLEDGE_TEAMS_OUTGOING_HMAC_SECRET": base64.b64encode(
                signing_key
            ).decode(),
        }
    )

    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            first = await client.post(
                "/api/teams/outgoing-webhook",
                content=body,
                headers={
                    "content-type": "application/json",
                    "authorization": f"HMAC {signature}",
                },
            )
            replay = await client.post(
                "/api/teams/outgoing-webhook",
                content=body,
                headers={
                    "content-type": "application/json",
                    "authorization": f"HMAC {signature}",
                },
            )

    assert first.status_code == replay.status_code == 200
    assert replay.json() == first.json()
    assert first.json()["type"] == "message"
    assert "`execution_authority=false`" in first.json()["text"]
    assert first.json()["attachments"][0]["content"]["version"] == "1.4"
