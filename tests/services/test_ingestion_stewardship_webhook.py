"""Focused optional composition and signed merge tests for stewardship webhooks."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json

import httpx
import pytest
from fdai_ingestion_api_service.adapters.stewardship import (
    GitHubRepositoryHandoverIntake,
    GitHubRepositoryHandoverIntakeConfig,
    GitHubStewardshipWebhook,
    GitHubStewardshipWebhookConfig,
)
from fdai_ingestion_api_service.production import (
    ProductionConfigurationError,
    _build_repository_handover_intake,
    _build_stewardship_webhook,
)
from fdai_service_contracts import RepositoryHandoverDraft, StewardshipMergeRecord

_SECRET = "s" * 32


class Recorder:
    def __init__(self) -> None:
        self.records: list[StewardshipMergeRecord] = []

    async def record(self, merge: StewardshipMergeRecord) -> bool:
        if any(item.delivery_id == merge.delivery_id for item in self.records):
            return False
        self.records.append(merge)
        return True


class DraftRecorder:
    def __init__(self) -> None:
        self.records: list[RepositoryHandoverDraft] = []

    async def record(self, draft: RepositoryHandoverDraft) -> bool:
        if any(item.delivery_id == draft.delivery_id for item in self.records):
            return False
        self.records.append(draft)
        return True


async def test_signed_merge_records_verified_stewardship_content_once() -> None:
    merged_yaml = "stewardship:\n  version: 1\n"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/pulls/42/files"):
            return httpx.Response(200, json=[{"filename": "config/agent-stewardship.yaml"}])
        if "/contents/config/agent-stewardship.yaml" in request.url.path:
            return httpx.Response(
                200,
                json={
                    "encoding": "base64",
                    "content": base64.b64encode(merged_yaml.encode()).decode(),
                },
            )
        raise AssertionError(request.url)

    body = json.dumps(
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
    signature = hmac.new(_SECRET.encode(), body, hashlib.sha256).hexdigest()
    headers = {
        "x-hub-signature-256": f"sha256={signature}",
        "x-github-event": "pull_request",
        "x-github-delivery": "delivery-1",
    }
    recorder = Recorder()
    webhook = GitHubStewardshipWebhook(
        config=GitHubStewardshipWebhookConfig(
            repository="acme/fdai",
            webhook_secret=_SECRET,
            token="token",
            api_base="https://example.com",
        ),
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        recorder=recorder,
    )

    first = await webhook.handle(headers=headers, body=body)
    replay = await webhook.handle(headers=headers, body=body)

    assert first.accepted is True and first.changed is True
    assert replay.accepted is True and replay.changed is False
    assert recorder.records[0].actor_identity == "github:operator"
    assert recorder.records[0].merged_yaml == merged_yaml


async def test_invalid_signature_is_rejected_without_github_call() -> None:
    webhook = GitHubStewardshipWebhook(
        config=GitHubStewardshipWebhookConfig(
            repository="acme/fdai",
            webhook_secret=_SECRET,
            token="token",
            api_base="https://example.com",
        ),
        http_client=httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: (_ for _ in ()).throw(AssertionError(request.url))
            )
        ),
        recorder=Recorder(),
    )

    result = await webhook.handle(headers={"x-hub-signature-256": "sha256=bad"}, body=b"{}")

    assert result.accepted is False
    assert result.reason == "invalid signature"


def test_optional_webhook_composition_is_disabled_or_fails_closed_when_partial() -> None:
    client = httpx.AsyncClient()
    assert (
        _build_stewardship_webhook(env={}, dsn="postgresql://example", http_client=client) is None
    )
    with pytest.raises(ProductionConfigurationError, match="environment is missing"):
        _build_stewardship_webhook(
            env={"FDAI_STEWARDSHIP_GITHUB_WEBHOOK_ENABLED": "1"},
            dsn="postgresql://example",
            http_client=client,
        )


async def test_authenticated_repository_dispatch_creates_only_an_inert_draft() -> None:
    body = json.dumps(
        {
            "action": "handover_draft",
            "repository": {"full_name": "acme/fdai"},
            "sender": {"login": "operator"},
            "client_payload": {
                "source_ref": "issues/17",
                "content": (
                    "agent: Njord; responsibility: accountable; subject: user; identity: Jane Kim"
                ),
            },
        }
    ).encode()
    signature = hmac.new(_SECRET.encode(), body, hashlib.sha256).hexdigest()
    headers = {
        "x-hub-signature-256": f"sha256={signature}",
        "x-github-event": "repository_dispatch",
        "x-github-delivery": "draft-delivery-1",
    }
    recorder = DraftRecorder()
    intake = GitHubRepositoryHandoverIntake(
        config=GitHubRepositoryHandoverIntakeConfig(repository="acme/fdai", webhook_secret=_SECRET),
        recorder=recorder,
    )

    first = await intake.handle(headers=headers, body=body)
    replay = await intake.handle(headers=headers, body=body)

    assert first.accepted is True and first.changed is True
    assert replay.accepted is True and replay.changed is False
    assert recorder.records[0].mode == "shadow"
    assert recorder.records[0].may_merge is False
    assert recorder.records[0].may_execute is False
    assert recorder.records[0].actor_identity == "github:operator"


def test_optional_repository_intake_requires_only_authentication_inputs() -> None:
    assert _build_repository_handover_intake(env={}, dsn="postgresql://example") is None
    with pytest.raises(ProductionConfigurationError, match="environment is missing"):
        _build_repository_handover_intake(
            env={"FDAI_STEWARDSHIP_REPOSITORY_INTAKE_ENABLED": "1"},
            dsn="postgresql://example",
        )
