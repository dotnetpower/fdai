"""One-time Slack webhook diagnostic transport and durable metadata tests."""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest
from fdai_operator_service.families.iam.contracts import SlackWebhookTestCommand
from fdai_operator_service.slack_webhook_diagnostics import (
    SlackWebhookDiagnosticTester,
    SlackWebhookProviderResponse,
    SlackWebhookTestConflictError,
    SlackWebhookTestProviderError,
    validate_slack_webhook_url,
)

NOW = datetime(2026, 8, 27, 13, 0, tzinfo=UTC)
URL = "https://hooks.slack.com/services/T00000000/B00000000/abcdefghijklmnopqrstuvwxyz"


class MemoryStore:
    def __init__(self) -> None:
        self.values: dict[str, dict[str, object]] = {}

    async def create_state(self, key: str, value: dict[str, object]) -> bool:
        if key in self.values:
            return False
        self.values[key] = dict(value)
        return True

    async def read_state(self, key: str) -> dict[str, object] | None:
        value = self.values.get(key)
        return None if value is None else dict(value)

    async def write_state(self, key: str, value: dict[str, object]) -> None:
        self.values[key] = dict(value)


def _command(request_id: str = "slack-test-1") -> SlackWebhookTestCommand:
    return SlackWebhookTestCommand(
        actor_id="owner-1",
        request_id=request_id,
        webhook_url=URL,
    )


async def test_accepts_fixed_message_and_never_persists_url() -> None:
    store = MemoryStore()
    calls: list[tuple[str, object]] = []

    async def post(url: str, payload: object) -> SlackWebhookProviderResponse:
        calls.append((url, payload))
        return SlackWebhookProviderResponse(200, "ok")

    tester = SlackWebhookDiagnosticTester(store=store, post=post, clock=lambda: NOW)
    result = await tester.test(_command())

    assert result.accepted is True
    assert result.provider_status == 200
    assert len(calls) == 1
    stored = next(iter(store.values.values()))
    assert stored["phase"] == "completed"
    assert stored["outcome"] == "accepted"
    assert URL not in repr(stored)
    assert calls[0][1]["text"] == "FDAI Slack notification test"  # type: ignore[index]


async def test_duplicate_completed_request_returns_receipt_without_resend() -> None:
    store = MemoryStore()
    calls = 0

    async def post(_: str, __: object) -> SlackWebhookProviderResponse:
        nonlocal calls
        calls += 1
        return SlackWebhookProviderResponse(200, "ok")

    tester = SlackWebhookDiagnosticTester(store=store, post=post, clock=lambda: NOW)

    first = await tester.test(_command())
    second = await tester.test(_command())

    assert first == second
    assert calls == 1


async def test_ambiguous_request_id_is_not_replayed() -> None:
    store = MemoryStore()

    async def post(_: str, __: object) -> SlackWebhookProviderResponse:
        raise httpx.ReadTimeout("acknowledgement missing")

    tester = SlackWebhookDiagnosticTester(store=store, post=post, clock=lambda: NOW)
    with pytest.raises(SlackWebhookTestProviderError, match="not observed"):
        await tester.test(_command())
    with pytest.raises(SlackWebhookTestConflictError, match="ambiguous"):
        await tester.test(_command())


@pytest.mark.parametrize(
    "url",
    [
        "http://hooks.slack.com/services/T000/B000/abcdefghijklmnopqrstuvwxyz",
        "https://hooks.slack.example/services/T000/B000/abcdefghijklmnopqrstuvwxyz",
        "https://hooks.slack.com/services/T000/B000/abcdefghijklmnopqrstuvwxyz?redirect=1",
        "https://hooks.slack.com.evil.invalid/services/T000/B000/abcdefghijklmnopqrstuvwxyz",
    ],
)
def test_rejects_non_slack_and_widened_urls(url: str) -> None:
    with pytest.raises(ValueError):
        validate_slack_webhook_url(url)


def test_accepts_govslack_webhook_host() -> None:
    digest = validate_slack_webhook_url(
        "https://hooks.slack-gov.com/services/T000/B000/abcdefghijklmnopqrstuvwxyz"
    )
    assert len(digest) == 64
