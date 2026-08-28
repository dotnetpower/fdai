"""Bounded one-time Microsoft Teams Workflows notification diagnostics."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from urllib.parse import parse_qs, urlsplit

import httpx

from fdai_operator_service.families.iam.contracts import (
    TeamsWorkflowTestCommand,
    TeamsWorkflowTestResult,
)

_PUBLIC_CLOUD_HOST = re.compile(
    r"^[a-z0-9-]+(?:\.[a-z0-9-]+)*\.environment\.api\.powerplatform\.com$"
)
_WORKFLOW_PATH = re.compile(
    r"^/powerautomate/automations/direct/workflows/[a-f0-9]{32}"
    r"/triggers/manual/paths/invoke$"
)
_REQUEST_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_SIGNATURE = re.compile(r"^[A-Za-z0-9_-]{20,256}$")
_MAX_URL_LENGTH = 4096
_TIMEOUT_SECONDS = 10.0


class TeamsWorkflowDiagnosticStore(Protocol):
    """Durable metadata store that never receives the webhook URL."""

    async def create_state(self, key: str, value: Mapping[str, object]) -> bool: ...

    async def read_state(self, key: str) -> dict[str, object] | None: ...

    async def write_state(self, key: str, value: Mapping[str, object]) -> None: ...


@dataclass(frozen=True, slots=True)
class TeamsWorkflowProviderResponse:
    status_code: int
    workflow_run_id: str | None = None


TeamsWorkflowPost = Callable[[str, Mapping[str, object]], Awaitable[TeamsWorkflowProviderResponse]]


class TeamsWorkflowTestConflictError(RuntimeError):
    """A request id already belongs to a different or ambiguous test."""


class TeamsWorkflowTestProviderError(RuntimeError):
    """The bounded provider request was rejected or could not be observed."""


@dataclass(frozen=True, slots=True)
class TeamsWorkflowDiagnosticTester:
    """Validate, audit, and send one fixed synthetic Adaptive Card."""

    store: TeamsWorkflowDiagnosticStore
    post: TeamsWorkflowPost = lambda url, payload: _post_workflow(url, payload)
    clock: Callable[[], datetime] = lambda: datetime.now(tz=UTC)

    async def test(self, command: TeamsWorkflowTestCommand) -> TeamsWorkflowTestResult:
        endpoint_digest = validate_teams_workflow_url(command.webhook_url)
        if not command.actor_id.strip():
            raise ValueError("Teams Workflow test actor_id MUST be non-empty")
        if not _REQUEST_ID.fullmatch(command.request_id):
            raise ValueError("Teams Workflow test request_id is invalid")
        now = self.clock()
        if now.tzinfo is None:
            raise RuntimeError("Teams Workflow test clock MUST be timezone-aware")
        key = _test_key(command.request_id)
        prepared: dict[str, object] = {
            "kind": "operator.teams-workflow-test",
            "request_id": command.request_id,
            "actor_id": command.actor_id,
            "endpoint_digest": endpoint_digest,
            "phase": "prepared",
            "prepared_at": now.astimezone(UTC).isoformat(),
        }
        if not await self.store.create_state(key, prepared):
            existing = await self.store.read_state(key)
            return _existing_result(
                existing=existing,
                command=command,
                endpoint_digest=endpoint_digest,
            )

        payload = _synthetic_card(command.request_id)
        try:
            response = await self.post(command.webhook_url, payload)
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
            raise TeamsWorkflowTestProviderError(
                "Teams Workflow acknowledgement was not observed"
            ) from exc
        if response.status_code not in {200, 201, 202, 204}:
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
            raise TeamsWorkflowTestProviderError(
                f"Teams Workflow rejected the synthetic card with HTTP {response.status_code}"
            )

        completed_at = self.clock().astimezone(UTC)
        result = TeamsWorkflowTestResult(
            request_id=command.request_id,
            accepted=True,
            provider_status=response.status_code,
            workflow_run_id=response.workflow_run_id,
            tested_at=completed_at,
        )
        await self.store.write_state(
            key,
            {
                **prepared,
                "phase": "completed",
                "outcome": "accepted",
                "provider_status": result.provider_status,
                "workflow_run_id": result.workflow_run_id,
                "completed_at": completed_at.isoformat(),
            },
        )
        return result


def validate_teams_workflow_url(webhook_url: str) -> str:
    """Validate one public-cloud Teams Workflows URL and return its digest."""
    if not webhook_url or len(webhook_url) > _MAX_URL_LENGTH:
        raise ValueError("Teams Workflow webhook URL length is invalid")
    parsed = urlsplit(webhook_url)
    if (
        parsed.scheme != "https"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or parsed.port not in {None, 443}
        or parsed.hostname is None
        or _PUBLIC_CLOUD_HOST.fullmatch(parsed.hostname) is None
        or _WORKFLOW_PATH.fullmatch(parsed.path) is None
    ):
        raise ValueError("Teams Workflow webhook URL is not an allowed public-cloud endpoint")
    query = parse_qs(parsed.query, keep_blank_values=True, strict_parsing=True)
    if set(query) != {"api-version", "sp", "sv", "sig"} or any(
        len(values) != 1 for values in query.values()
    ):
        raise ValueError("Teams Workflow webhook URL query contract is invalid")
    if (
        query["api-version"][0] != "1"
        or query["sp"][0] != "/triggers/manual/run"
        or query["sv"][0] != "1.0"
        or _SIGNATURE.fullmatch(query["sig"][0]) is None
    ):
        raise ValueError("Teams Workflow webhook URL query values are invalid")
    return hashlib.sha256(webhook_url.encode("utf-8")).hexdigest()


async def _post_workflow(
    webhook_url: str,
    payload: Mapping[str, object],
) -> TeamsWorkflowProviderResponse:
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
            return TeamsWorkflowProviderResponse(
                status_code=response.status_code,
                workflow_run_id=response.headers.get("x-ms-workflow-run-id"),
            )


def _synthetic_card(request_id: str) -> dict[str, object]:
    return {
        "type": "message",
        "attachments": [
            {
                "contentType": "application/vnd.microsoft.card.adaptive",
                "contentUrl": None,
                "content": {
                    "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                    "type": "AdaptiveCard",
                    "version": "1.4",
                    "body": [
                        {
                            "type": "TextBlock",
                            "size": "Medium",
                            "weight": "Bolder",
                            "text": "FDAI Teams notification test",
                        },
                        {
                            "type": "TextBlock",
                            "wrap": True,
                            "text": (
                                "The one-time Teams Workflows notification diagnostic "
                                "reached this channel."
                            ),
                        },
                        {
                            "type": "FactSet",
                            "facts": [{"title": "request_id", "value": request_id}],
                        },
                    ],
                },
            }
        ],
    }


def _test_key(request_id: str) -> str:
    digest = hashlib.sha256(request_id.encode("utf-8")).hexdigest()
    return f"operator-teams-workflow-test:{digest}"


def _existing_result(
    *,
    existing: Mapping[str, object] | None,
    command: TeamsWorkflowTestCommand,
    endpoint_digest: str,
) -> TeamsWorkflowTestResult:
    if (
        existing is None
        or existing.get("request_id") != command.request_id
        or existing.get("actor_id") != command.actor_id
        or existing.get("endpoint_digest") != endpoint_digest
    ):
        raise TeamsWorkflowTestConflictError(
            "Teams Workflow test request_id conflicts with an existing request"
        )
    if existing.get("phase") != "completed" or existing.get("outcome") != "accepted":
        raise TeamsWorkflowTestConflictError(
            "Teams Workflow test request has an ambiguous or non-successful prior attempt"
        )
    provider_status = existing.get("provider_status")
    tested_at = existing.get("completed_at")
    workflow_run_id = existing.get("workflow_run_id")
    if (
        not isinstance(provider_status, int)
        or not isinstance(tested_at, str)
        or (workflow_run_id is not None and not isinstance(workflow_run_id, str))
    ):
        raise RuntimeError("stored Teams Workflow test result is malformed")
    parsed_at = datetime.fromisoformat(tested_at)
    if parsed_at.tzinfo is None:
        raise RuntimeError("stored Teams Workflow test timestamp is timezone-naive")
    return TeamsWorkflowTestResult(
        request_id=command.request_id,
        accepted=True,
        provider_status=provider_status,
        workflow_run_id=workflow_run_id,
        tested_at=parsed_at,
    )


__all__ = [
    "TeamsWorkflowDiagnosticTester",
    "TeamsWorkflowProviderResponse",
    "TeamsWorkflowTestConflictError",
    "TeamsWorkflowTestProviderError",
    "validate_teams_workflow_url",
]
