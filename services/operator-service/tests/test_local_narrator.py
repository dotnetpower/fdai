"""Focused tests for the real local Azure CLI narrator adapter."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from fdai_operator_service.adapters.local_narrator import LocalAzureNarratorAdapters
from fdai_operator_service.environment import LOCAL_AZURE_NARRATOR_ENV, OperatorEnvironment
from fdai_operator_service.families.conversation.contracts import (
    ConversationBoundaryError,
    ConversationQuery,
    ConversationResponse,
    ConversationStreamRequest,
    PrincipalScope,
)


class FallbackAdapters:
    async def read(self, query: ConversationQuery) -> ConversationResponse:
        return ConversationResponse({"operation": query.operation})

    async def open(self, request: ConversationStreamRequest):  # type: ignore[no-untyped-def]
        del request
        raise AssertionError("fallback stream MUST NOT handle chat.stream")


class RecordingHttpClient:
    def __init__(self, answer: str = "Grounded local narrator answer.") -> None:
        self.answer = answer
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def post(self, url: str, **kwargs: object) -> httpx.Response:
        self.calls.append((url, kwargs))
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": self.answer}}]},
        )


def _artifact(path: Path) -> Path:
    path.write_text(
        json.dumps(
            {
                "narrator": {
                    "endpoint": "https://example.openai.azure.com",
                    "deployment": "narrator-gpt-5-mini",
                    "api_version": "2024-08-01-preview",
                }
            }
        ),
        encoding="utf-8",
    )
    return path


async def test_local_narrator_calls_provider_and_emits_canonical_turn(tmp_path: Path) -> None:
    client = RecordingHttpClient()

    async def token_provider(audience: str) -> str:
        assert audience == "https://cognitiveservices.azure.com/"
        return "test-token"

    fallback = FallbackAdapters()
    adapter = LocalAzureNarratorAdapters.from_environment(
        {"LLM_RESOLVED_MODELS_PATH": str(_artifact(tmp_path / "models.json"))},
        fallback_projections=fallback,
        fallback_streams=fallback,
        token_provider=token_provider,
        http_client=client,
    )
    source = await adapter.open(
        ConversationStreamRequest(
            operation="chat.stream",
            scope=PrincipalScope("operator-1", frozenset({"Owner"})),
            body={"prompt": "What is visible?", "view_context": {"headline": "Dashboard"}},
        )
    )
    events = [event async for event in source]

    assert [event.event for event in events] == ["token", "done"]
    assert events[1].data["answer"] == "Grounded local narrator answer."
    assert events[1].data["source"] == "llm:narrator-gpt-5-mini"
    verification = events[1].data["verification"]
    assert isinstance(verification, dict)
    assert verification["status"] == "unverified"
    assert len(client.calls) == 1
    _, kwargs = client.calls[0]
    assert kwargs["headers"] == {
        "Authorization": "Bearer test-token",
        "Content-Type": "application/json",
    }
    assert "max_completion_tokens" in kwargs["json"]  # type: ignore[operator]
    assert "temperature" not in kwargs["json"]  # type: ignore[operator]


async def test_local_narrator_health_requires_a_real_token(tmp_path: Path) -> None:
    async def unavailable_token(_audience: str) -> str:
        raise ConversationBoundaryError(503, "token_unavailable", "token unavailable")

    fallback = FallbackAdapters()
    adapter = LocalAzureNarratorAdapters.from_environment(
        {"LLM_RESOLVED_MODELS_PATH": str(_artifact(tmp_path / "models.json"))},
        fallback_projections=fallback,
        fallback_streams=fallback,
        token_provider=unavailable_token,
        http_client=RecordingHttpClient(),
    )
    result = await adapter.read(
        ConversationQuery(operation="chat.health", scope=PrincipalScope("operator-1"))
    )

    assert result.body == {
        "available": False,
        "mode": "unavailable",
        "model": None,
        "endpoint": None,
    }


async def test_local_narrator_delegates_non_health_projection(tmp_path: Path) -> None:
    fallback = FallbackAdapters()
    adapter = LocalAzureNarratorAdapters.from_environment(
        {"LLM_RESOLVED_MODELS_PATH": str(_artifact(tmp_path / "models.json"))},
        fallback_projections=fallback,
        fallback_streams=fallback,
        token_provider=lambda _audience: _token(),
        http_client=RecordingHttpClient(),
    )
    result = await adapter.read(
        ConversationQuery(operation="user.context", scope=PrincipalScope("operator-1"))
    )
    assert result.body == {"operation": "user.context"}


async def _token() -> str:
    return "test-token"


def test_local_narrator_flag_is_dev_only() -> None:
    base = {
        "FDAI_ENTRA_TENANT_ID": "tenant",
        "FDAI_API_AUDIENCE": "audience",
        "FDAI_RBAC_READERS_GROUP_ID": "reader",
        "FDAI_RBAC_CONTRIBUTORS_GROUP_ID": "contributor",
        "FDAI_RBAC_APPROVERS_GROUP_ID": "approver",
        "FDAI_RBAC_OWNERS_GROUP_ID": "owner",
        "FDAI_RBAC_BREAK_GLASS_GROUP_ID": "break-glass",
        LOCAL_AZURE_NARRATOR_ENV: "1",
    }
    with pytest.raises(ValueError, match="requires RUNTIME_ENV=dev"):
        OperatorEnvironment.parse({**base, "RUNTIME_ENV": "prod"})
    assert OperatorEnvironment.parse({**base, "RUNTIME_ENV": "dev"}).local_azure_narrator is True


def test_local_narrator_rejects_non_azure_token_destination(tmp_path: Path) -> None:
    path = tmp_path / "models.json"
    path.write_text(
        json.dumps(
            {
                "narrator": {
                    "endpoint": "https://attacker.example.com",
                    "deployment": "narrator-gpt-4o-mini",
                }
            }
        ),
        encoding="utf-8",
    )
    fallback = FallbackAdapters()

    with pytest.raises(ValueError, match="no usable narrator candidate"):
        LocalAzureNarratorAdapters.from_environment(
            {"LLM_RESOLVED_MODELS_PATH": str(path)},
            fallback_projections=fallback,
            fallback_streams=fallback,
            token_provider=lambda _audience: _token(),
            http_client=RecordingHttpClient(),
        )
