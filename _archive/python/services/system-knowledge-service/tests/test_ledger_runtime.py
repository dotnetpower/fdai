from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import pytest
from fdai_system_knowledge_service.catalog import load_catalog
from fdai_system_knowledge_service.config import TeamsTransport
from fdai_system_knowledge_service.ledger import MessageLedger
from fdai_system_knowledge_service.runtime import (
    OutgoingWebhookKnowledgeRuntime,
    SystemKnowledgeRuntime,
)
from fdai_system_knowledge_service.search import SystemKnowledgeIndex
from fdai_system_knowledge_service.teams import TeamsPublishError, VerifiedKnowledgeTurn

REPO_ROOT = Path(__file__).resolve().parents[3]
CATALOG_PATH = (
    REPO_ROOT
    / "services/system-knowledge-service/src/fdai_system_knowledge_service/data/catalog.json"
)
FIXED_TIME = datetime(2026, 9, 9, tzinfo=UTC)


class _Ingress:
    def __init__(self, turn: VerifiedKnowledgeTurn | None) -> None:
        self.turn = turn
        self.warmed = False

    async def warm(self) -> None:
        self.warmed = True

    async def parse(self, **_kwargs: object) -> VerifiedKnowledgeTurn | None:
        return self.turn


class _Publisher:
    def __init__(self, error: Exception | None = None) -> None:
        self.calls = 0
        self.closed = False
        self.payload: object | None = None
        self.error = error

    async def send(self, **kwargs: object) -> str:
        self.calls += 1
        self.payload = kwargs["payload"]
        if self.error is not None:
            raise self.error
        return "reply-example"

    async def aclose(self) -> None:
        self.closed = True


def _turn(
    *,
    query: str = "How does FDAI keep actions safe?",
    locale: Literal["en", "ko"] = "en",
    message_id: str = "message-example",
) -> VerifiedKnowledgeTurn:
    return VerifiedKnowledgeTurn(
        conversation_id="conversation-example",
        message_id=message_id,
        sender_id="aad-user-example",
        principal_id="knowledge-reader-example",
        principal_scope_digest="sha256:" + ("a" * 64),
        service_url="https://smba.trafficmanager.net/example",
        query=query,
        locale=locale,
        verification_ref="teams-service-key:key-example",
    )


async def test_runtime_delivers_once_and_suppresses_duplicate_after_restart(tmp_path: Path) -> None:
    ledger_path = tmp_path / "ledger.sqlite3"
    publisher = _Publisher()
    ingress = _Ingress(_turn())
    runtime = SystemKnowledgeRuntime(
        ingress=ingress,  # type: ignore[arg-type]
        index=SystemKnowledgeIndex(load_catalog(CATALOG_PATH)),
        ledger=MessageLedger(ledger_path),
        publisher=publisher,  # type: ignore[arg-type]
    )
    assert runtime.transport is TeamsTransport.BOT_FRAMEWORK
    assert runtime.ready is False
    await runtime.start()
    assert runtime.ready is True

    first = await runtime.handle(
        body=b"",
        authorization="Bearer token",
        received_at=FIXED_TIME,
    )
    duplicate = await runtime.handle(
        body=b"{}",
        authorization="Bearer token",
        received_at=FIXED_TIME,
    )
    await runtime.aclose()
    assert runtime.ready is False

    restarted = MessageLedger(ledger_path)
    await restarted.start()

    assert ingress.warmed is True
    assert first.state == "delivered"
    assert duplicate.duplicate is True
    assert publisher.calls == 1
    assert publisher.closed is True
    assert await restarted.state(_turn().message_key) == "delivered"


async def test_startup_turns_interrupted_send_into_ambiguous_terminal(tmp_path: Path) -> None:
    ledger_path = tmp_path / "ledger.sqlite3"
    ledger = MessageLedger(ledger_path)
    await ledger.start()
    assert await ledger.claim("message-key") is True
    await ledger.mark_sending("message-key", "sha256:" + ("b" * 64))

    restarted = MessageLedger(ledger_path)
    await restarted.start()

    assert await restarted.state("message-key") == "ambiguous"
    assert await restarted.claim("message-key") is False


async def test_outgoing_webhook_returns_deterministic_response_on_replay(tmp_path: Path) -> None:
    ledger = MessageLedger(tmp_path / "outgoing.sqlite3")
    runtime = OutgoingWebhookKnowledgeRuntime(
        ingress=_Ingress(_turn()),  # type: ignore[arg-type]
        index=SystemKnowledgeIndex(load_catalog(CATALOG_PATH)),
        ledger=ledger,
    )
    assert runtime.transport is TeamsTransport.OUTGOING_WEBHOOK
    assert runtime.ready is False
    await runtime.start()
    assert runtime.ready is True

    first = await runtime.handle(
        body=b"first",
        authorization="HMAC example",
        received_at=FIXED_TIME,
    )
    replay = await runtime.handle(
        body=b"replay",
        authorization="HMAC example",
        received_at=FIXED_TIME,
    )
    await runtime.aclose()
    assert runtime.ready is False

    assert first.state == "responded"
    assert replay.state == "duplicate"
    assert replay.duplicate is True
    assert replay.payload == first.payload
    assert first.payload["type"] == "message"
    assert "replyToId" not in first.payload
    assert await ledger.state(_turn().message_key) == "delivered"


async def test_outgoing_webhook_preserves_ambiguous_state_after_restart(tmp_path: Path) -> None:
    ledger_path = tmp_path / "outgoing-ambiguous.sqlite3"
    seed_ledger = MessageLedger(ledger_path)
    await seed_ledger.start()
    turn = _turn()
    assert await seed_ledger.claim(turn.message_key) is True
    await seed_ledger.mark_sending(turn.message_key, "sha256:" + ("c" * 64))
    await seed_ledger.aclose()

    restarted_ledger = MessageLedger(ledger_path)
    runtime = OutgoingWebhookKnowledgeRuntime(
        ingress=_Ingress(turn),  # type: ignore[arg-type]
        index=SystemKnowledgeIndex(load_catalog(CATALOG_PATH)),
        ledger=restarted_ledger,
    )
    await runtime.start()
    replay = await runtime.handle(
        body=b"replay-after-restart",
        authorization="HMAC example",
        received_at=FIXED_TIME,
    )
    await runtime.aclose()

    assert replay.state == "ambiguous"
    assert replay.duplicate is True
    assert await restarted_ledger.state(turn.message_key) == "ambiguous"


async def test_ledger_and_runtime_failure_paths(tmp_path: Path) -> None:
    ledger = MessageLedger(tmp_path / "failures.sqlite3")
    await ledger.start()
    assert await ledger.claim("k1") is True
    await ledger.release_retryable("k1")
    assert await ledger.state("k1") is None

    assert await ledger.claim("k2") is True
    await ledger.mark_sending("k2", "sha256:" + ("b" * 64))
    await ledger.mark_ambiguous("k2")
    assert await ledger.state("k2") == "ambiguous"

    with pytest.raises(RuntimeError, match="retry release lost ownership"):
        await ledger.release_retryable("k2")
    with pytest.raises(RuntimeError, match="transition lost ownership"):
        await ledger.mark_delivered("k2", "act-1")

    index = SystemKnowledgeIndex(load_catalog(CATALOG_PATH))

    ignored_runtime = SystemKnowledgeRuntime(
        ingress=_Ingress(None),  # type: ignore[arg-type]
        index=index,
        ledger=ledger,
        publisher=_Publisher(),  # type: ignore[arg-type]
    )
    ignored = await ignored_runtime.handle(
        body=b"{}",
        authorization="token",
        received_at=FIXED_TIME,
    )
    assert ignored.state == "ignored"

    for locale, msg_id in (("ko", "ko-empty"), ("en", "en-empty")):
        rt = SystemKnowledgeRuntime(
            ingress=_Ingress(_turn(query="", locale=locale, message_id=msg_id)),  # type: ignore[arg-type]
            index=index,
            ledger=ledger,
            publisher=_Publisher(),  # type: ignore[arg-type]
        )
        res = await rt.handle(body=b"{}", authorization="token", received_at=FIXED_TIME)
        assert res.state == "delivered"

    amb_turn = _turn(message_id="msg-amb")
    amb_rt = SystemKnowledgeRuntime(
        ingress=_Ingress(amb_turn),  # type: ignore[arg-type]
        index=index,
        ledger=ledger,
        publisher=_Publisher(TeamsPublishError("timeout", code="transport_error", ambiguous=True)),  # type: ignore[arg-type]
    )
    amb_res = await amb_rt.handle(body=b"{}", authorization="token", received_at=FIXED_TIME)
    assert amb_res.state == "ambiguous"
    assert await ledger.state(amb_turn.message_key) == "ambiguous"

    retry_turn = _turn(message_id="msg-retry")
    retry_rt = SystemKnowledgeRuntime(
        ingress=_Ingress(retry_turn),  # type: ignore[arg-type]
        index=index,
        ledger=ledger,
        publisher=_Publisher(
            TeamsPublishError("rejected", code="provider_rejected", ambiguous=False)
        ),  # type: ignore[arg-type]
    )
    with pytest.raises(TeamsPublishError):
        await retry_rt.handle(body=b"{}", authorization="token", received_at=FIXED_TIME)
    assert await ledger.state(retry_turn.message_key) is None

    val_turn = _turn(message_id="msg-val")
    val_rt = SystemKnowledgeRuntime(
        ingress=_Ingress(val_turn),  # type: ignore[arg-type]
        index=index,
        ledger=ledger,
        publisher=_Publisher(ValueError("bad value")),  # type: ignore[arg-type]
    )
    with pytest.raises(ValueError, match="bad value"):
        await val_rt.handle(body=b"{}", authorization="token", received_at=FIXED_TIME)
    assert await ledger.state(val_turn.message_key) is None


async def test_runtime_aclose_and_outgoing_webhook_error_paths(tmp_path: Path) -> None:
    ledger = MessageLedger(tmp_path / "webhook-errors.sqlite3")
    await ledger.start()
    index = SystemKnowledgeIndex(load_catalog(CATALOG_PATH))

    class _FailingPublisher(_Publisher):
        async def aclose(self) -> None:
            raise RuntimeError("pub-close-boom")

    class _FailingLedger(MessageLedger):
        async def aclose(self) -> None:
            raise RuntimeError("ledger-close-boom")

    with pytest.raises(RuntimeError, match="pub-close-boom"):
        await SystemKnowledgeRuntime(
            ingress=_Ingress(None),  # type: ignore[arg-type]
            index=index,
            ledger=ledger,
            publisher=_FailingPublisher(),  # type: ignore[arg-type]
        ).aclose()

    with pytest.raises(RuntimeError, match="ledger-close-boom"):
        await SystemKnowledgeRuntime(
            ingress=_Ingress(None),  # type: ignore[arg-type]
            index=index,
            ledger=_FailingLedger(tmp_path / "f1.sqlite3"),
            publisher=_Publisher(),  # type: ignore[arg-type]
        ).aclose()

    with pytest.raises(RuntimeError, match="pub-close-boom"):
        await SystemKnowledgeRuntime(
            ingress=_Ingress(None),  # type: ignore[arg-type]
            index=index,
            ledger=_FailingLedger(tmp_path / "f2.sqlite3"),
            publisher=_FailingPublisher(),  # type: ignore[arg-type]
        ).aclose()

    none_webhook = OutgoingWebhookKnowledgeRuntime(
        ingress=_Ingress(None),  # type: ignore[arg-type]
        index=index,
        ledger=ledger,
    )
    with pytest.raises(RuntimeError, match="unavailable"):
        await none_webhook.handle(body=b"{}", authorization="HMAC x", received_at=FIXED_TIME)

    for locale, msg_id in (("ko", "wh-ko-empty"), ("en", "wh-en-empty")):
        wh_rt = OutgoingWebhookKnowledgeRuntime(
            ingress=_Ingress(_turn(query="", locale=locale, message_id=msg_id)),  # type: ignore[arg-type]
            index=index,
            ledger=ledger,
        )
        wh_res = await wh_rt.handle(body=b"{}", authorization="HMAC x", received_at=FIXED_TIME)
        assert wh_res.state == "responded"

    class _SendFailLedger(MessageLedger):
        async def mark_sending(self, key: str, response_digest: str) -> None:
            del key, response_digest
            raise ValueError("send-fail")

    send_fail_ledger = _SendFailLedger(tmp_path / "sf.sqlite3")
    await send_fail_ledger.start()
    sf_turn = _turn(message_id="sf-msg")
    sf_rt = OutgoingWebhookKnowledgeRuntime(
        ingress=_Ingress(sf_turn),  # type: ignore[arg-type]
        index=index,
        ledger=send_fail_ledger,
    )
    with pytest.raises(ValueError, match="send-fail"):
        await sf_rt.handle(body=b"{}", authorization="HMAC x", received_at=FIXED_TIME)
    assert await send_fail_ledger.state(sf_turn.message_key) is None

    class _DeliverFailLedger(MessageLedger):
        async def mark_delivered(self, key: str, provider_activity_id: str) -> None:
            del key, provider_activity_id
            raise RuntimeError("deliver-fail")

    deliver_fail_ledger = _DeliverFailLedger(tmp_path / "df.sqlite3")
    await deliver_fail_ledger.start()
    df_turn = _turn(message_id="df-msg")
    df_rt = OutgoingWebhookKnowledgeRuntime(
        ingress=_Ingress(df_turn),  # type: ignore[arg-type]
        index=index,
        ledger=deliver_fail_ledger,
    )
    with pytest.raises(RuntimeError, match="deliver-fail"):
        await df_rt.handle(body=b"{}", authorization="HMAC x", received_at=FIXED_TIME)
    assert await deliver_fail_ledger.state(df_turn.message_key) == "ambiguous"
