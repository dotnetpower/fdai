"""Principal-timezone current-time ChatOps tool tests."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.testclient import TestClient

from fdai.delivery.read_api.read_model import InMemoryConsoleReadModel
from fdai.delivery.read_api.routes.chat import ChatBackend
from fdai.delivery.read_api.routes.chat_current_time import (
    CurrentTimeChatTools,
    current_time_evidence_refs,
    render_current_time_answer,
)
from fdai.delivery.read_api.routes.chat_registration import append_chat_routes
from fdai.delivery.read_api.routes.chat_route_common import _uses_evidence_fast_path
from fdai.delivery.read_api.routes.chat_verification import verify_answer
from fdai.shared.providers.testing import InMemoryUserPreferenceStore
from fdai.shared.providers.user_context import UserPreferenceRecord

NOW = datetime(2026, 7, 23, 8, 42, 9, tzinfo=UTC)


async def _preferences(timezone: str | None) -> InMemoryUserPreferenceStore:
    store = InMemoryUserPreferenceStore()
    await store.put(
        UserPreferenceRecord(
            principal_id="principal-example",
            revision=1,
            locale="ko",
            timezone=timezone,
        )
    )
    return store


class _ForbiddenBackend(ChatBackend):
    async def answer(
        self,
        *,
        prompt: str,
        view_context: dict[str, Any],
        history: list[dict[str, str]],
    ) -> dict[str, str]:
        raise AssertionError("current-time fast path must not call the model backend")


async def _allow(_request: Request) -> str:
    return "principal-example"


async def test_current_time_uses_principal_iana_timezone() -> None:
    tools = CurrentTimeChatTools(preferences=await _preferences("Asia/Seoul"), clock=lambda: NOW)

    evidence = await tools.resolve("지금 몇시야?", principal_id="principal-example")

    assert evidence is not None
    result = evidence["result"]
    assert result["timestamp"] == "2026-07-23T17:42:09+09:00"
    assert result["timezone"] == "Asia/Seoul"
    assert result["timezone_source"] == "principal_preference"
    context = {"_tool_evidence": evidence}
    assert _uses_evidence_fast_path(context) is True
    assert render_current_time_answer(evidence, locale="ko") == (
        "현재 시각은 2026-07-23 17:42:09 (Asia/Seoul)입니다."
    )
    assert current_time_evidence_refs(evidence) == (
        "server-clock:2026-07-23T17:42:09+09:00:Asia/Seoul",
    )
    verified = verify_answer("", context, locale="ko")
    assert verified.status == "corrected"
    assert verified.answer == "현재 시각은 2026-07-23 17:42:09 (Asia/Seoul)입니다."
    assert verified.authority == "server_clock"
    assert verified.reason_code == "current_time_grounded"


async def test_current_time_falls_back_to_explicit_utc() -> None:
    tools = CurrentTimeChatTools(preferences=await _preferences(None), clock=lambda: NOW)

    evidence = await tools.resolve("what time is it now?", principal_id="principal-example")

    assert evidence is not None
    assert evidence["result"]["timezone"] == "UTC"
    assert evidence["result"]["timezone_source"] == "utc_fallback"
    assert render_current_time_answer(evidence, locale="en") == (
        "The current time is 2026-07-23 08:42:09 (UTC)."
    )


async def test_non_time_question_uses_fallback() -> None:
    class _Fallback:
        async def resolve(self, prompt: str, *, principal_id: str):  # type: ignore[no-untyped-def]
            return {"tool": "fallback", "result": {"prompt": prompt}}

    tools = CurrentTimeChatTools(
        preferences=await _preferences("Asia/Seoul"),
        clock=lambda: NOW,
        fallback=_Fallback(),
    )

    evidence = await tools.resolve("show inventory", principal_id="principal-example")

    assert evidence == {"tool": "fallback", "result": {"prompt": "show inventory"}}


def test_registered_chat_route_answers_current_time_without_model() -> None:
    preferences = InMemoryUserPreferenceStore()

    async def seed() -> None:
        await preferences.put(
            UserPreferenceRecord(
                principal_id="principal-example",
                revision=1,
                locale="ko",
                timezone="Asia/Seoul",
            )
        )

    import asyncio

    asyncio.run(seed())
    routes: list[Any] = []
    append_chat_routes(
        routes,
        backend=_ForbiddenBackend(),
        agent_delegate=None,
        answer_preference_store=preferences,
        authorize=_allow,
        read_model=InMemoryConsoleReadModel(),
        core_paths=(),
        panel_paths=(),
        logger=__import__("logging").getLogger("fdai.tests.current-time"),
    )

    response = TestClient(Starlette(routes=routes)).post(
        "/chat",
        json={"prompt": "지금 몇시야?"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert "Asia/Seoul" in payload["answer"]
    assert payload["verification"]["authority"] == "server_clock"
    assert payload["verification"]["reason_code"] == "current_time_grounded"
