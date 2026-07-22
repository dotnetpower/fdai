from __future__ import annotations

import base64
import hashlib
import hmac
import json
from pathlib import Path

import httpx

from fdai.delivery.stewardship.github_webhook import (
    GitHubStewardshipWebhook,
    GitHubStewardshipWebhookConfig,
)

_CONFIG = Path(__file__).resolve().parents[3] / "config" / "agent-stewardship.yaml"
_SECRET = "s" * 32


class Governance:
    def __init__(self) -> None:
        self.merges = []

    async def record_merge(self, merge):
        self.merges.append(merge)
        return True


def _body() -> bytes:
    return json.dumps(
        {
            "action": "closed",
            "number": 42,
            "repository": {"full_name": "acme/fdai"},
            "pull_request": {
                "merged": True,
                "merge_commit_sha": "abc123",
                "merged_by": {"login": "operator"},
            },
        }
    ).encode()


def _headers(body: bytes) -> dict[str, str]:
    signature = hmac.new(_SECRET.encode(), body, hashlib.sha256).hexdigest()
    return {
        "x-hub-signature-256": f"sha256={signature}",
        "x-github-event": "pull_request",
        "x-github-delivery": "delivery-1",
    }


async def test_webhook_verifies_changed_file_and_merged_content() -> None:
    yaml_content = _CONFIG.read_text(encoding="utf-8")
    encoded = base64.b64encode(yaml_content.encode()).decode()
    wrapped = "\n".join(encoded[index : index + 60] for index in range(0, len(encoded), 60))

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/pulls/42/files"):
            return httpx.Response(200, json=[{"filename": "config/agent-stewardship.yaml"}])
        if "/contents/config/agent-stewardship.yaml" in request.url.path:
            return httpx.Response(
                200,
                json={
                    "encoding": "base64",
                    "content": wrapped,
                },
            )
        raise AssertionError(request.url)

    governance = Governance()
    webhook = GitHubStewardshipWebhook(
        config=GitHubStewardshipWebhookConfig(
            repository="acme/fdai",
            webhook_secret=_SECRET,
            token="token",
            api_base="https://mock.github.local",
        ),
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        governance=governance,
    )
    body = _body()

    result = await webhook.handle(headers=_headers(body), body=body)

    assert result.accepted is True
    assert result.changed is True
    assert governance.merges[0].actor_identity == "github:operator"
    assert governance.merges[0].merged_yaml == yaml_content


async def test_webhook_rejects_invalid_signature_without_http() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("invalid webhook must not call GitHub")

    webhook = GitHubStewardshipWebhook(
        config=GitHubStewardshipWebhookConfig(
            repository="acme/fdai",
            webhook_secret=_SECRET,
            token="token",
            api_base="https://mock.github.local",
        ),
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        governance=Governance(),
    )

    result = await webhook.handle(
        headers={"x-hub-signature-256": "sha256=bad"},
        body=_body(),
    )

    assert result.accepted is False
    assert result.reason == "invalid signature"
