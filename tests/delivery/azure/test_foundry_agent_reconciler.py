from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest

from fdai.delivery.azure.foundry_agent_reconciler import (
    FoundryWebSearchAgentSpec,
    reconcile_foundry_web_search_agent,
)


def _spec() -> FoundryWebSearchAgentSpec:
    return FoundryWebSearchAgentSpec(
        project_endpoint="https://foundry.example.com/api/projects/fdai",
        agent_name="fdai-web-search",
        model_deployment="t1.web_search",
        allowed_domains=("learn.microsoft.com", "azure.microsoft.com"),
    )


def test_reconcile_creates_changed_definition_and_probes_tool() -> None:
    calls: list[tuple[str, str, Mapping[str, Any] | None]] = []

    def request(
        method: str,
        url: str,
        _token: str,
        payload: Mapping[str, Any] | None,
    ) -> Mapping[str, Any]:
        calls.append((method, url, payload))
        if method == "GET":
            assert url.endswith("?api-version=v1&limit=1&order=desc")
            return {"data": []}
        if url.endswith("/openai/v1/responses"):
            return {"output": [{"type": "web_search_call"}]}
        return {"version": "1", "metadata": payload["metadata"] if payload else {}}

    result = reconcile_foundry_web_search_agent(
        _spec(), request_json=request, token_provider=lambda: "token"
    )

    assert result.changed is True
    assert result.agent_version == "1"
    create_payload = calls[1][2]
    assert create_payload is not None
    assert create_payload["definition"] == {
        "kind": "prompt",
        "model": "t1.web_search",
        "instructions": (
            "Search only the configured public domains. Return concise evidence with source "
            "citations and do not infer facts that the retrieved pages do not support."
        ),
        "tools": [
            {
                "type": "web_search",
                "filters": {"allowed_domains": ["learn.microsoft.com", "azure.microsoft.com"]},
            }
        ],
    }
    assert calls[2][2] is not None
    assert calls[2][2]["tool_choice"] == "required"


def test_reconcile_reuses_latest_matching_definition() -> None:
    spec = _spec()
    methods: list[str] = []

    def request(
        method: str,
        url: str,
        _token: str,
        _payload: Mapping[str, Any] | None,
    ) -> Mapping[str, Any]:
        methods.append(method)
        if method == "GET":
            return {
                "data": [
                    {"version": "2", "metadata": {"fdai_definition_sha256": "stale"}},
                    {
                        "version": "3",
                        "metadata": {"fdai_definition_sha256": spec.definition_digest()},
                    },
                ]
            }
        assert url.endswith("/openai/v1/responses")
        return {"output": [{"type": "web_search_call"}]}

    result = reconcile_foundry_web_search_agent(
        spec, request_json=request, token_provider=lambda: "token"
    )

    assert result.changed is False
    assert result.agent_version == "3"
    assert methods == ["GET", "POST"]


def test_reconcile_fails_when_probe_does_not_execute_tool() -> None:
    spec = _spec()

    def request(
        method: str,
        _url: str,
        _token: str,
        _payload: Mapping[str, Any] | None,
    ) -> Mapping[str, Any]:
        if method == "GET":
            return {
                "data": [
                    {
                        "version": "1",
                        "metadata": {"fdai_definition_sha256": spec.definition_digest()},
                    }
                ]
            }
        return {"output": [{"type": "message"}]}

    with pytest.raises(RuntimeError, match="did not execute web search"):
        reconcile_foundry_web_search_agent(
            spec, request_json=request, token_provider=lambda: "token"
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("project_endpoint", "http://foundry.example.com/api/projects/fdai"),
        ("agent_name", "invalid/name"),
        ("model_deployment", ""),
        ("allowed_domains", ()),
        ("allowed_domains", ("https://learn.microsoft.com",)),
        ("allowed_domains", ("learn.microsoft.com/path",)),
        ("allowed_domains", ("*.microsoft.com",)),
        ("allowed_domains", ("localhost",)),
    ],
)
def test_spec_rejects_invalid_boundary(field: str, value: object) -> None:
    values: dict[str, object] = {
        "project_endpoint": "https://foundry.example.com/api/projects/fdai",
        "agent_name": "fdai-web-search",
        "model_deployment": "t1.web_search",
        "allowed_domains": ("learn.microsoft.com",),
    }
    values[field] = value
    with pytest.raises(ValueError):
        FoundryWebSearchAgentSpec(**values)  # type: ignore[arg-type]
