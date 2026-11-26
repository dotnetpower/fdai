from __future__ import annotations

import base64
import dataclasses
import hashlib
import hmac
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import fdai_system_knowledge_service.application as application_module
import fdai_system_knowledge_service.main as main_module
import fdai_system_knowledge_service.server as server_module
import pytest
from fdai_service_contracts.venue import ExecutionVenue
from fdai_system_knowledge_service.application import create_app, create_runtime
from fdai_system_knowledge_service.catalog import load_catalog
from fdai_system_knowledge_service.config import (
    CLAIM_CONTAINER_URL_ENV,
    SystemKnowledgeSettings,
    TeamsTransport,
)
from fdai_system_knowledge_service.runtime import (
    KnowledgeTurnResult,
    OutgoingWebhookTurnResult,
)
from fdai_system_knowledge_service.teams import TeamsIngressError, TeamsPublishError
from httpx import ASGITransport, AsyncClient

FIXED_TIME = datetime(2026, 9, 9, tzinfo=UTC)
REPO_ROOT = Path(__file__).resolve().parents[3]
CATALOG_PATH = (
    REPO_ROOT
    / "services/system-knowledge-service/src/fdai_system_knowledge_service/data/catalog.json"
)


class _FixedDatetime(datetime):
    @classmethod
    def now(cls, tz: Any = None) -> datetime:
        del tz
        return FIXED_TIME


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
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(application_module, "datetime", _FixedDatetime)
    signing_key = b"k" * 32
    body = json.dumps(
        {
            "type": "message",
            "id": "message-example",
            "timestamp": FIXED_TIME.isoformat(),
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
    assert first.headers["x-fdai-claim-state"] == "responded"
    assert replay.headers["x-fdai-claim-state"] == "duplicate"
    assert replay.json() == first.json()
    assert first.json()["type"] == "message"
    assert "`execution_authority=false`" in first.json()["text"]
    assert first.json()["attachments"][0]["content"]["version"] == "1.4"


def _bot_env(*, venue: str, tmp_path: Path, source_revision: str) -> dict[str, str]:
    values = {
        "FDAI_EXECUTION_VENUE": venue,
        "FDAI_SYSTEM_KNOWLEDGE_LEDGER_PATH": str(tmp_path / "bot.sqlite3"),
        "FDAI_SYSTEM_KNOWLEDGE_TEAMS_APPLICATION_ID": "application-example",
        "FDAI_SYSTEM_KNOWLEDGE_TEAMS_BOT_ID": "28:application-example",
        "FDAI_SYSTEM_KNOWLEDGE_TEAMS_TENANT_ID": "tenant-example",
        "FDAI_SYSTEM_KNOWLEDGE_TEAMS_TEAM_IDS_JSON": '["team-example"]',
        "FDAI_SYSTEM_KNOWLEDGE_TEAMS_CHANNEL_IDS_JSON": '["channel-example"]',
        "FDAI_SYSTEM_KNOWLEDGE_TEAMS_SERVICE_URLS_JSON": (
            '["https://smba.trafficmanager.net/example"]'
        ),
        "FDAI_SYSTEM_KNOWLEDGE_TEAMS_PRINCIPAL_MAP_JSON": (
            '{"aad-user-example":"knowledge-reader-example"}'
        ),
        "FDAI_SYSTEM_KNOWLEDGE_TEAMS_JWKS_URL": "https://login.example.com/keys",
    }
    if venue == "local":
        values["FDAI_SYSTEM_KNOWLEDGE_TEAMS_CLIENT_SECRET"] = "local-secret"
    else:
        values["FDAI_SYSTEM_KNOWLEDGE_SOURCE_REVISION"] = source_revision
        values["FDAI_SYSTEM_KNOWLEDGE_MI_CLIENT_ID"] = "application-example"
        values[CLAIM_CONTAINER_URL_ENV] = "https://storage.example.com/claims"
    return values


async def test_composed_runtime_and_create_runtime_branches(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog = load_catalog(CATALOG_PATH)
    local_settings = SystemKnowledgeSettings.parse(
        _bot_env(venue="local", tmp_path=tmp_path, source_revision=catalog.source_revision)
    )
    composed = create_runtime(local_settings)
    assert composed.transport is TeamsTransport.BOT_FRAMEWORK
    assert composed.ready is False

    inner = composed._runtime  # type: ignore[attr-defined]

    async def _noop_start() -> None:
        inner._ready = True

    async def _fake_handle(
        *,
        body: bytes,
        authorization: str,
        received_at: datetime,
    ) -> KnowledgeTurnResult:
        del body, authorization, received_at
        return KnowledgeTurnResult(state="delivered")

    monkeypatch.setattr(inner, "start", _noop_start)
    monkeypatch.setattr(inner, "handle", _fake_handle)
    await composed.start()
    assert composed.ready is True
    res = await composed.handle(body=b"{}", authorization="******", received_at=FIXED_TIME)
    assert res == KnowledgeTurnResult(state="delivered")
    await composed.aclose()

    failing_composed = create_runtime(local_settings)

    async def _boom_start() -> None:
        raise RuntimeError("start-failed")

    monkeypatch.setattr(failing_composed._runtime, "start", _boom_start)  # type: ignore[attr-defined]
    with pytest.raises(RuntimeError, match="start-failed"):
        await failing_composed.start()

    deployed_settings = SystemKnowledgeSettings.parse(
        _bot_env(venue="deployed", tmp_path=tmp_path, source_revision=catalog.source_revision)
    )

    class _FakeContainerClient:
        async def close(self) -> None:
            return None

    monkeypatch.setattr(
        application_module.ContainerClient,
        "from_container_url",
        lambda *_args, **_kwargs: _FakeContainerClient(),
    )
    deployed_runtime = create_runtime(deployed_settings)
    await deployed_runtime.aclose()

    no_container_settings = dataclasses.replace(deployed_settings, claim_container_url=None)
    with pytest.raises(RuntimeError, match="claim container is unavailable"):
        create_runtime(no_container_settings)

    bad_teams_settings = dataclasses.replace(local_settings, teams="invalid")  # type: ignore[arg-type]
    with pytest.raises(RuntimeError, match="Teams transport settings are unavailable"):
        create_runtime(bad_teams_settings)

    assert local_settings.execution_venue is ExecutionVenue.LOCAL


async def test_app_route_error_responses_and_entrypoints(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _ErrorBotRuntime(_Runtime):
        def __init__(self, exc: Exception) -> None:
            super().__init__()
            self._exc = exc

        async def handle(self, **_kwargs: Any) -> KnowledgeTurnResult:
            raise self._exc

    ingress_app = create_app(
        runtime=_ErrorBotRuntime(TeamsIngressError("bad", code="invalid_payload", http_status=400))
    )
    publish_app = create_app(
        runtime=_ErrorBotRuntime(
            TeamsPublishError("down", code="provider_rejected", ambiguous=False)
        )
    )
    async with AsyncClient(
        transport=ASGITransport(app=ingress_app), base_url="http://test"
    ) as client:
        unready = await client.get("/health/ready")
        ing_resp = await client.post(
            "/api/teams/messages",
            content=b"{}",
            headers={"content-type": "application/json"},
        )
        wh_disabled = await client.post(
            "/api/teams/outgoing-webhook",
            content=b"{}",
            headers={"content-type": "application/json"},
        )
    async with AsyncClient(
        transport=ASGITransport(app=publish_app), base_url="http://test"
    ) as client:
        pub_resp = await client.post(
            "/api/teams/messages",
            content=b"{}",
            headers={"content-type": "application/json"},
        )

    assert unready.status_code == 503
    assert ing_resp.status_code == 400
    assert wh_disabled.status_code == 404
    assert pub_resp.status_code == 503

    class _CustomOutgoingRuntime(_OutgoingRuntime):
        def __init__(self, outcome: object) -> None:
            super().__init__()
            self._outcome = outcome

        async def handle(self, **_kwargs: Any) -> Any:
            if isinstance(self._outcome, Exception):
                raise self._outcome
            return self._outcome

    wh_app = create_app(runtime=_OutgoingRuntime())
    async with AsyncClient(transport=ASGITransport(app=wh_app), base_url="http://test") as client:
        wh_media = await client.post("/api/teams/outgoing-webhook", content=b"{}")
        wh_large = await client.post(
            "/api/teams/outgoing-webhook",
            content=b"x" * 256_001,
            headers={"content-type": "application/json"},
        )
    assert wh_media.status_code == 415
    assert wh_large.status_code == 413

    timeout_app = create_app(runtime=_CustomOutgoingRuntime(TimeoutError("deadline")))
    async with AsyncClient(
        transport=ASGITransport(app=timeout_app), base_url="http://test"
    ) as client:
        timeout_resp = await client.post(
            "/api/teams/outgoing-webhook",
            content=b"{}",
            headers={"content-type": "application/json"},
        )
    assert timeout_resp.status_code == 503
    assert timeout_resp.json()["error"]["code"] == "outgoing_webhook_deadline_exceeded"

    wh_ing_app = create_app(
        runtime=_CustomOutgoingRuntime(
            TeamsIngressError("unauth", code="invalid_webhook_signature", http_status=401)
        )
    )
    async with AsyncClient(
        transport=ASGITransport(app=wh_ing_app), base_url="http://test"
    ) as client:
        wh_ing_resp = await client.post(
            "/api/teams/outgoing-webhook",
            content=b"{}",
            headers={"content-type": "application/json"},
        )
    assert wh_ing_resp.status_code == 401

    invalid_res_app = create_app(runtime=_CustomOutgoingRuntime("not-a-turn-result"))
    async with AsyncClient(
        transport=ASGITransport(app=invalid_res_app), base_url="http://test"
    ) as client:
        with pytest.raises(RuntimeError, match="invalid result"):
            await client.post(
                "/api/teams/outgoing-webhook",
                content=b"{}",
                headers={"content-type": "application/json"},
            )

    catalog = load_catalog(CATALOG_PATH)
    settings = SystemKnowledgeSettings.parse(
        _bot_env(venue="local", tmp_path=tmp_path, source_revision=catalog.source_revision)
    )
    served: dict[str, object] = {}
    monkeypatch.setattr(
        server_module.uvicorn,
        "run",
        lambda app, *, host, port, access_log: served.update(
            {"app": app, "host": host, "port": port, "access_log": access_log}
        ),
    )
    assert server_module.serve(wh_app, settings) == 0
    assert served["host"] == settings.host
    assert served["port"] == settings.port
    assert served["access_log"] is False

    monkeypatch.setattr(main_module, "record_runtime_scope_receipt", lambda *_a, **_k: None)
    monkeypatch.setattr(main_module.SystemKnowledgeSettings, "parse", lambda _env: settings)
    monkeypatch.setattr(main_module, "create_runtime", lambda _s: _Runtime())
    monkeypatch.setattr(main_module, "serve", lambda _app, _s: 0)
    assert main_module.main() == 0
