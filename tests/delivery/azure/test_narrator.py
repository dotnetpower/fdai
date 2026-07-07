"""AzureOpenAINarratorModel - real chat.completions narrator adapter."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest

from aiopspilot.core.conversation.narrator import default_tool_schemas
from aiopspilot.delivery.azure.llm.narrator import (
    AzureOpenAINarratorModel,
    AzureOpenAINarratorModelConfig,
)
from aiopspilot.shared.providers.workload_identity import IdentityToken


class _FakeIdentity:
    def __init__(self, token: str = "tok") -> None:  # noqa: S107 - test fake, not a real secret
        self._token = token
        self.audiences: list[str] = []

    def get_token_sync(self, audience: str) -> IdentityToken:
        self.audiences.append(audience)
        return IdentityToken(
            token=self._token,
            expires_at=datetime.now(tz=UTC) + timedelta(hours=1),
            audience=audience,
        )


def _make_client(
    handler_fn: Any,
) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler_fn))


def _make_narrator(
    *,
    handler_fn: Any,
    endpoint: str = "https://oai.example.com",
    deployment: str = "t2.reasoner.primary",
) -> AzureOpenAINarratorModel:
    return AzureOpenAINarratorModel(
        identity=_FakeIdentity(),
        http_client=_make_client(handler_fn),
        config=AzureOpenAINarratorModelConfig(
            endpoint=endpoint,
            deployment=deployment,
        ),
    )


def _envelope(content: str) -> dict[str, Any]:
    return {
        "choices": [
            {
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ]
    }


class TestValidation:
    def test_http_endpoint_rejected(self) -> None:
        with pytest.raises(ValueError, match="absolute https URL"):
            AzureOpenAINarratorModelConfig(endpoint="oai.example.com", deployment="d")
            AzureOpenAINarratorModel(
                identity=_FakeIdentity(),
                http_client=_make_client(lambda r: httpx.Response(200)),
                config=AzureOpenAINarratorModelConfig(endpoint="oai.example.com", deployment="d"),
            )

    def test_empty_deployment_rejected(self) -> None:
        with pytest.raises(ValueError, match="deployment MUST NOT be empty"):
            AzureOpenAINarratorModel(
                identity=_FakeIdentity(),
                http_client=_make_client(lambda r: httpx.Response(200)),
                config=AzureOpenAINarratorModelConfig(endpoint="https://x", deployment=""),
            )

    def test_zero_timeout_rejected(self) -> None:
        with pytest.raises(ValueError, match="timeout_seconds MUST be > 0"):
            AzureOpenAINarratorModel(
                identity=_FakeIdentity(),
                http_client=_make_client(lambda r: httpx.Response(200)),
                config=AzureOpenAINarratorModelConfig(
                    endpoint="https://x", deployment="d", timeout_seconds=0.0
                ),
            )

    def test_bad_temperature_rejected(self) -> None:
        with pytest.raises(ValueError, match="temperature MUST be in"):
            AzureOpenAINarratorModel(
                identity=_FakeIdentity(),
                http_client=_make_client(lambda r: httpx.Response(200)),
                config=AzureOpenAINarratorModelConfig(
                    endpoint="https://x", deployment="d", temperature=3.0
                ),
            )


class TestTranslate:
    def test_valid_response_returned_verbatim(self) -> None:
        captured: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["body"] = request.read()
            return httpx.Response(200, json=_envelope("query_inventory resource-group"))

        n = _make_narrator(handler_fn=handler)
        out = n.translate(
            utterance="\ub9ac\uc18c\uc2a4 \uadf8\ub8f9 \ubaa9\ub85d",
            tools=default_tool_schemas(),
            principal_role="reader",
        )
        assert out == "query_inventory resource-group"
        assert "openai/deployments/t2.reasoner.primary" in captured["url"]

    def test_abstain_marker_returns_none(self) -> None:
        n = _make_narrator(handler_fn=lambda r: httpx.Response(200, json=_envelope("ABSTAIN")))
        assert (
            n.translate(
                utterance="do random thing",
                tools=default_tool_schemas(),
                principal_role="reader",
            )
            is None
        )

    def test_abstain_lowercase_returns_none(self) -> None:
        n = _make_narrator(handler_fn=lambda r: httpx.Response(200, json=_envelope("abstain")))
        assert (
            n.translate(
                utterance="x",
                tools=default_tool_schemas(),
                principal_role="reader",
            )
            is None
        )

    def test_code_fence_stripped(self) -> None:
        n = _make_narrator(
            handler_fn=lambda r: httpx.Response(
                200,
                json=_envelope("```\nquery_audit\n```"),
            )
        )
        assert (
            n.translate(
                utterance="show audit",
                tools=default_tool_schemas(),
                principal_role="reader",
            )
            == "query_audit"
        )

    def test_multiline_response_takes_first_line(self) -> None:
        n = _make_narrator(
            handler_fn=lambda r: httpx.Response(
                200,
                json=_envelope("explore_catalog storage\n\nSome extra text."),
            )
        )
        assert (
            n.translate(
                utterance="find storage rules",
                tools=default_tool_schemas(),
                principal_role="reader",
            )
            == "explore_catalog storage"
        )

    def test_empty_utterance_short_circuits(self) -> None:
        # No HTTP call should be made.
        def handler(request: httpx.Request) -> httpx.Response:
            raise AssertionError("HTTP called on empty utterance")

        n = _make_narrator(handler_fn=handler)
        assert (
            n.translate(
                utterance="   ",
                tools=default_tool_schemas(),
                principal_role="reader",
            )
            is None
        )

    def test_empty_tool_list_short_circuits(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise AssertionError("HTTP called with empty tool list")

        n = _make_narrator(handler_fn=handler)
        # Empty tool sequence -> no legal verb possible -> short-circuit.
        assert (
            n.translate(
                utterance="please explore",
                tools=[],
                principal_role="reader",
            )
            is None
        )

    def test_http_error_returns_none(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("boom")

        n = _make_narrator(handler_fn=handler)
        assert (
            n.translate(
                utterance="x",
                tools=default_tool_schemas(),
                principal_role="reader",
            )
            is None
        )

    def test_4xx_returns_none(self) -> None:
        n = _make_narrator(handler_fn=lambda r: httpx.Response(429, text="rate limited"))
        assert (
            n.translate(
                utterance="x",
                tools=default_tool_schemas(),
                principal_role="reader",
            )
            is None
        )

    def test_non_json_body_returns_none(self) -> None:
        n = _make_narrator(handler_fn=lambda r: httpx.Response(200, text="not-json"))
        assert (
            n.translate(
                utterance="x",
                tools=default_tool_schemas(),
                principal_role="reader",
            )
            is None
        )

    def test_missing_content_returns_none(self) -> None:
        n = _make_narrator(
            handler_fn=lambda r: httpx.Response(
                200,
                json={"choices": [{"message": {"role": "assistant"}}]},
            )
        )
        assert (
            n.translate(
                utterance="x",
                tools=default_tool_schemas(),
                principal_role="reader",
            )
            is None
        )

    def test_empty_content_returns_none(self) -> None:
        n = _make_narrator(
            handler_fn=lambda r: httpx.Response(
                200,
                json=_envelope(""),
            )
        )
        assert (
            n.translate(
                utterance="x",
                tools=default_tool_schemas(),
                principal_role="reader",
            )
            is None
        )

    def test_authorization_header_carries_bearer_token(self) -> None:
        captured: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["auth"] = request.headers.get("Authorization")
            return httpx.Response(200, json=_envelope("query_audit"))

        identity = _FakeIdentity(token="tok-42")
        n = AzureOpenAINarratorModel(
            identity=identity,
            http_client=_make_client(handler),
            config=AzureOpenAINarratorModelConfig(
                endpoint="https://oai.example.com",
                deployment="t2.reasoner.primary",
            ),
        )
        n.translate(
            utterance="show audit",
            tools=default_tool_schemas(),
            principal_role="reader",
        )
        assert captured["auth"] == "Bearer tok-42"
        assert identity.audiences == ["https://cognitiveservices.azure.com/.default"]

    def test_reader_prompt_hides_write_verbs(self) -> None:
        captured: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["body"] = request.read().decode("utf-8")
            return httpx.Response(200, json=_envelope("ABSTAIN"))

        n = _make_narrator(handler_fn=handler)
        n.translate(
            utterance="approve",
            tools=default_tool_schemas(),
            principal_role="reader",
        )
        body = captured["body"]
        # System prompt for a Reader MUST NOT list Approver-floor tools.
        assert "approve_hil" not in body
        assert "list_hil" not in body
        # But Reader-visible verbs MUST appear.
        assert "explore_catalog" in body
