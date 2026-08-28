"""Bounded one-time Slack incoming-webhook notification diagnostics."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from urllib.parse import urlsplit

import httpx

from fdai_operator_service.families.iam.contracts import (
    SlackWebhookTestCommand,
    SlackWebhookTestResult,
)

_SLACK_HOSTS = frozenset({"hooks.slack.com", "hooks.slack-gov.com"})
_WEBHOOK_PATH = re.compile(r"^/services/[A-Za-z0-9]+/[A-Za-z0-9]+/[A-Za-z0-9_-]{20,256}$")
_REQUEST_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_MAX_URL_LENGTH = 2048
_TIMEOUT_SECONDS = 10.0
_MAX_RESPONSE_BYTES = 64


class SlackWebhookDiagnosticStore(Protocol):
    """Durable metadata store that never receives the webhook URL."""

    async def create_state(self, key: str, value: Mapping[str, object]) -> bool: ...

    async def read_state(self, key: str) -> dict[str, object] | None: ...

    async def write_state(self, key: str, value: Mapping[str, object]) -> None: ...


@dataclass(frozen=True, slots=True)
class SlackWebhookProviderResponse:
    status_code: int
    body: str


SlackWebhookPost = Callable[[str, Mapping[str, object]], Awaitable[SlackWebhookProviderResponse]]


class SlackWebhookTestConflictError(RuntimeError):
    """A request id already belongs to a different or ambiguous test."""


class SlackWebhookTestProviderError(RuntimeError):
    """The bounded Slack request was rejected or could not be observed."""


@dataclass(frozen=True, slots=True)
class SlackWebhookDiagnosticTester:
    """Validate, audit, and send one fixed synthetic Block Kit message."""

    store: SlackWebhookDiagnosticStore
    post: SlackWebhookPost = lambda url, payload: _post_webhook(url, payload)
    clock: Callable[[], datetime] = lambda: datetime.now(tz=UTC)

    async def test(self, command: SlackWebhookTestCommand) -> SlackWebhookTestResult:
        endpoint_digest = validate_slack_webhook_url(command.webhook_url)
        if not command.actor_id.strip():
            raise ValueError("Slack webhook test actor_id MUST be non-empty")
        if not _REQUEST_ID.fullmatch(command.request_id):
            raise ValueError("Slack webhook test request_id is invalid")
        now = self.clock()
        if now.tzinfo is None:
            raise RuntimeError("Slack webhook test clock MUST be timezone-aware")
        key = _test_key(command.request_id)
        prepared: dict[str, object] = {
            "kind": "operator.slack-webhook-test",
            "request_id": command.request_id,
            "actor_id": command.actor_id,
            "endpoint_digest": endpoint_digest,
            "phase": "prepared",
            "prepared_at": now.astimezone(UTC).isoformat(),
        }
        if not await self.store.create_state(key, prepared):
            return _existing_result(
                existing=await self.store.read_state(key),
                command=command,
                endpoint_digest=endpoint_digest,
            )

        try:
            response = await self.post(
                command.webhook_url,
                _synthetic_message(command.request_id),
            )
        except httpx.HTTPError as exc:
            await self.store.write_state(
                key,
                {
                    **prepared,
                    "phase": "completed",
                    "outcome": "ambiguous",
                    "completed_at": self.clock().astimezone(UTC).isoformat(),
                    "error_type": type(exc).__name__,
                },
            )
            raise SlackWebhookTestProviderError(
                "Slack webhook acknowledgement was not observed"
            ) from exc
        if response.status_code != 200 or response.body != "ok":
            await self.store.write_state(
                key,
                {
                    **prepared,
                    "phase": "completed",
                    "outcome": "rejected",
                    "provider_status": response.status_code,
                    "completed_at": self.clock().astimezone(UTC).isoformat(),
                },
            )
            raise SlackWebhookTestProviderError(
                f"Slack rejected the synthetic message with HTTP {response.status_code}"
            )

        completed_at = self.clock().astimezone(UTC)
        result = SlackWebhookTestResult(
            request_id=command.request_id,
            accepted=True,
            provider_status=response.status_code,
            tested_at=completed_at,
        )
        await self.store.write_state(
            key,
            {
                **prepared,
                "phase": "completed",
                "outcome": "accepted",
                "provider_status": result.provider_status,
                "completed_at": completed_at.isoformat(),
            },
        )
        return result


def validate_slack_webhook_url(webhook_url: str) -> str:
    """Validate one Slack or GovSlack incoming webhook and return its digest."""
    if not webhook_url or len(webhook_url) > _MAX_URL_LENGTH:
        raise ValueError("Slack webhook URL length is invalid")
    parsed = urlsplit(webhook_url)
    if (
        parsed.scheme != "https"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or parsed.query
        or parsed.port not in {None, 443}
        or parsed.hostname not in _SLACK_HOSTS
        or _WEBHOOK_PATH.fullmatch(parsed.path) is None
    ):
        raise ValueError("Slack webhook URL is not an allowed incoming-webhook endpoint")
    return hashlib.sha256(webhook_url.encode("utf-8")).hexdigest()


async def _post_webhook(
    webhook_url: str,
    payload: Mapping[str, object],
) -> SlackWebhookProviderResponse:
    async with httpx.AsyncClient(
        trust_env=False,
        follow_redirects=False,
        timeout=_TIMEOUT_SECONDS,
    ) as client:
        async with client.stream(
            "POST",
            webhook_url,
            content=json.dumps(
                payload,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        ) as response:
            body = (await response.aread())[:_MAX_RESPONSE_BYTES].decode(
                "utf-8",
                errors="replace",
            )
            return SlackWebhookProviderResponse(response.status_code, body)


def _synthetic_message(request_id: str) -> dict[str, object]:
    return {
        "text": "FDAI Slack notification test",
        "blocks": [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": "FDAI Slack notification test",
                    "emoji": True,
                },
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        "The one-time Slack incoming-webhook diagnostic reached this channel."
                    ),
                },
            },
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f"`request_id: {request_id}`",
                    }
                ],
            },
        ],
    }


def _test_key(request_id: str) -> str:
    digest = hashlib.sha256(request_id.encode("utf-8")).hexdigest()
    return f"operator-slack-webhook-test:{digest}"


def _existing_result(
    *,
    existing: Mapping[str, object] | None,
    command: SlackWebhookTestCommand,
    endpoint_digest: str,
) -> SlackWebhookTestResult:
    if (
        existing is None
        or existing.get("request_id") != command.request_id
        or existing.get("actor_id") != command.actor_id
        or existing.get("endpoint_digest") != endpoint_digest
    ):
        raise SlackWebhookTestConflictError(
            "Slack webhook test request_id conflicts with an existing request"
        )
    if existing.get("phase") != "completed" or existing.get("outcome") != "accepted":
        raise SlackWebhookTestConflictError(
            "Slack webhook test request has an ambiguous or non-successful prior attempt"
        )
    provider_status = existing.get("provider_status")
    tested_at = existing.get("completed_at")
    if not isinstance(provider_status, int) or not isinstance(tested_at, str):
        raise RuntimeError("stored Slack webhook test result is malformed")
    parsed_at = datetime.fromisoformat(tested_at)
    if parsed_at.tzinfo is None:
        raise RuntimeError("stored Slack webhook test timestamp is timezone-naive")
    return SlackWebhookTestResult(
        request_id=command.request_id,
        accepted=True,
        provider_status=provider_status,
        tested_at=parsed_at,
    )


__all__ = [
    "SlackWebhookDiagnosticTester",
    "SlackWebhookProviderResponse",
    "SlackWebhookTestConflictError",
    "SlackWebhookTestProviderError",
    "validate_slack_webhook_url",
]
