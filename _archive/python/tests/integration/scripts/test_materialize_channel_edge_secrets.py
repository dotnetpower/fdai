from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "deployment" / "azure" / "materialize_channel_edge_secrets.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("materialize_channel_edge_secrets", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _environ() -> dict[str, str]:
    return {
        "CHANNEL_EDGE_SLACK_SIGNING_SECRET": "signing-secret-example",
        "CHANNEL_EDGE_SLACK_BOT_TOKEN": "xoxb-example-token-value",
        "CHANNEL_EDGE_SLACK_TEAM_ID": "TEXAMPLE",
        "CHANNEL_EDGE_SLACK_PRINCIPAL_MAP_JSON": json.dumps({"U123": "principal-example"}),
        "CHANNEL_EDGE_PRINCIPAL_SCOPES_JSON": json.dumps(
            {
                "principal-example": {
                    "scope_ref": "scope://operator/dev",
                    "roles": ["Reader"],
                    "locale": "en",
                }
            }
        ),
    }


def test_materialization_writes_and_reads_back_four_fixed_secrets() -> None:
    module = _load()
    inputs = module.ChannelEdgeSecretInputs.from_environ(_environ())
    methods: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        methods.append(request.method)
        assert request.url.host == "example.vault.azure.net"
        assert request.headers["Authorization"] == "Bearer header.payload.signature"
        if request.method == "PUT":
            return httpx.Response(200, json=json.loads(request.content))
        secret_name = request.url.path.rsplit("/", maxsplit=1)[-1]
        return httpx.Response(200, json={"value": inputs.vault_values()[secret_name]})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        module.materialize_channel_edge_secrets(
            vault_uri="https://example.vault.azure.net/",
            inputs=inputs,
            access_token="header.payload.signature",
            transport=client,
        )

    assert methods == ["PUT", "GET"] * 4


@pytest.mark.parametrize(
    ("name", "value", "message"),
    [
        ("CHANNEL_EDGE_SLACK_BOT_TOKEN", "not-a-bot-token", "bot token"),
        ("CHANNEL_EDGE_SLACK_TEAM_ID", "invalid team", "workspace id"),
        ("CHANNEL_EDGE_SLACK_PRINCIPAL_MAP_JSON", '{"U123":"missing"}', "configured principals"),
    ],
)
def test_materialization_rejects_invalid_provider_input(
    name: str,
    value: str,
    message: str,
) -> None:
    module = _load()
    environ = _environ()
    environ[name] = value

    with pytest.raises(module.ChannelEdgeSecretError, match=message):
        module.ChannelEdgeSecretInputs.from_environ(environ)


def test_materialization_rejects_mismatched_readback() -> None:
    module = _load()
    inputs = module.ChannelEdgeSecretInputs.from_environ(_environ())

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "PUT":
            return httpx.Response(200, json={})
        return httpx.Response(200, json={"value": "different"})

    with (
        httpx.Client(transport=httpx.MockTransport(handler)) as client,
        pytest.raises(module.ChannelEdgeSecretError, match="did not match"),
    ):
        module.materialize_channel_edge_secrets(
            vault_uri="https://example.vault.azure.net",
            inputs=inputs,
            access_token="header.payload.signature",
            transport=client,
        )


def test_materialization_rejects_non_vault_host() -> None:
    module = _load()
    inputs = module.ChannelEdgeSecretInputs.from_environ(_environ())

    with (
        httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(500))) as client,
        pytest.raises(module.ChannelEdgeSecretError, match="approved Azure boundary"),
    ):
        module.materialize_channel_edge_secrets(
            vault_uri="https://example.com",
            inputs=inputs,
            access_token="header.payload.signature",
            transport=client,
        )
