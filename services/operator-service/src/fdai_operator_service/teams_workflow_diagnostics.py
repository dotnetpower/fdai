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
from fdai_operator_service.teams_workflow_binding import (
    TeamsWorkflowBindingError,
    TeamsWorkflowBindingStore,
)

_PUBLIC_CLOUD_HOST = re.compile(
    r"^[a-z0-9-]+(?:\.[a-z0-9-]+)*\.environment\.api\.powerplatform\.com$"
)
_WORKFLOW_PATH = re.compile(
    r"^/powerautomate/automations/direct(?:/[a-z0-9]{2}){0,2}/workflows/[a-f0-9]{32}"
    r"/triggers/manual/paths/invoke$"
)
_REQUEST_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_SIGNATURE = re.compile(r"^[A-Za-z0-9_-]{20,256}$")
_MAX_URL_LENGTH = 4096
_ACTIVE_BINDING_METADATA_KEY = "operator-teams-workflow-binding-metadata:active"
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


class TeamsWorkflowBindingUnavailableError(RuntimeError):
    """The deployment did not compose a writable secret binding."""


@dataclass(frozen=True, slots=True)
class TeamsWorkflowDiagnosticTester:
    """Save one endpoint, then validate, audit, and send one synthetic card."""

    store: TeamsWorkflowDiagnosticStore
    binding_store: TeamsWorkflowBindingStore | None = None
    post: TeamsWorkflowPost = lambda url, payload: _post_workflow(url, payload)
    clock: Callable[[], datetime] = lambda: datetime.now(tz=UTC)

    async def save_and_test(
        self,
        command: TeamsWorkflowTestCommand,
    ) -> TeamsWorkflowTestResult:
        endpoint_digest = validate_teams_workflow_url(command.webhook_url)
        if not command.actor_id.strip():
            raise ValueError("Teams Workflow test actor_id MUST be non-empty")
        if not _REQUEST_ID.fullmatch(command.request_id):
            raise ValueError("Teams Workflow test request_id is invalid")
        if self.binding_store is None:
            raise TeamsWorkflowBindingUnavailableError(
                "Teams Workflow binding storage is not configured"
            )
        now = self.clock()
        if now.tzinfo is None:
            raise RuntimeError("Teams Workflow test clock MUST be timezone-aware")
        key = _binding_key(command.request_id)
        prepared: dict[str, object] = {
            "kind": "operator.teams-workflow-binding-save",
            "request_id": command.request_id,
            "actor_id": command.actor_id,
            "endpoint_digest": endpoint_digest,
            "phase": "prepared",
            "prepared_at": now.astimezone(UTC).isoformat(),
        }
        if not await self.store.create_state(key, prepared):
            existing = await self.store.read_state(key)
            return await self._existing_saved_result(existing=existing, command=command)
        try:
            saved = await self.binding_store.save_and_verify(
                webhook_url=command.webhook_url,
                request_id=command.request_id,
            )
        except TeamsWorkflowBindingError as exc:
            await self.store.write_state(
                key,
                {
                    **prepared,
                    "phase": "completed",
                    "outcome": "failed",
                    "completed_at": self.clock().astimezone(UTC).isoformat(),
                    "error_type": type(exc).__name__,
                },
            )
            raise
        if saved.endpoint_digest != endpoint_digest:
            await self.store.write_state(
                key,
                {
                    **prepared,
                    "phase": "completed",
                    "outcome": "failed",
                    "completed_at": self.clock().astimezone(UTC).isoformat(),
                    "error_type": "TeamsWorkflowBindingError",
                },
            )
            raise TeamsWorkflowBindingError("Teams Workflow binding verification digest mismatch")
        saved_at = self.clock().astimezone(UTC)
        await self.store.write_state(
            key,
            {
                **prepared,
                "phase": "completed",
                "outcome": "saved",
                "binding_version": saved.version,
                "completed_at": saved_at.isoformat(),
            },
        )
        await self.store.write_state(
            _ACTIVE_BINDING_METADATA_KEY,
            {
                "kind": "operator.teams-workflow-binding-metadata",
                "binding_version": saved.version,
                "saved_at": saved_at.isoformat(),
                "actor_id": command.actor_id,
            },
        )
        tested = await self.test(
            TeamsWorkflowTestCommand(
                actor_id=command.actor_id,
                request_id=command.request_id,
                webhook_url=saved.webhook_url,
            )
        )
        return TeamsWorkflowTestResult(
            request_id=tested.request_id,
            saved=True,
            binding_version=saved.version,
            saved_at=saved_at,
            accepted=tested.accepted,
            provider_status=tested.provider_status,
            workflow_run_id=tested.workflow_run_id,
            tested_at=tested.tested_at,
        )

    async def describe_binding(
        self,
        *,
        actor_id: str,
    ) -> Mapping[str, object] | None:
        """Return secret-free saved-binding metadata for an authorized reader.

        The saved Teams Workflows URL is a password-equivalent secret. It is
        never returned, never prefilled, and never logged; an Owner replaces it
        by submitting a new URL. ``saved_at`` is present only when the durable
        Operator record proves this exact binding version was saved here.
        """
        if not actor_id.strip():
            raise ValueError("Teams Workflow binding actor_id MUST be non-empty")
        if self.binding_store is None:
            raise TeamsWorkflowBindingUnavailableError(
                "Teams Workflow binding storage is not configured"
            )
        saved = await self.binding_store.load()
        if saved is None:
            return None
        observed_at = self.clock().astimezone(UTC)
        metadata: dict[str, object] = {
            "binding_version": saved.version,
            "observed_at": observed_at.isoformat(),
        }
        record = await self.store.read_state(_ACTIVE_BINDING_METADATA_KEY)
        if record is not None and record.get("binding_version") == saved.version:
            saved_at = record.get("saved_at")
            if isinstance(saved_at, str):
                metadata["saved_at"] = saved_at
        return metadata

    async def _existing_saved_result(
        self,
        *,
        existing: Mapping[str, object] | None,
        command: TeamsWorkflowTestCommand,
    ) -> TeamsWorkflowTestResult:
        if (
            existing is None
            or existing.get("phase") != "completed"
            or existing.get("outcome") != "saved"
            or existing.get("actor_id") != command.actor_id
            or existing.get("endpoint_digest")
            != hashlib.sha256(command.webhook_url.encode("utf-8")).hexdigest()
        ):
            raise TeamsWorkflowTestConflictError(
                "Teams Workflow binding request is incomplete or belongs to another endpoint"
            )
        version = existing.get("binding_version")
        saved_at = existing.get("completed_at")
        if not isinstance(version, str) or not isinstance(saved_at, str):
            raise TeamsWorkflowTestConflictError(
                "Teams Workflow binding request has invalid saved metadata"
            )
        parsed_saved_at = datetime.fromisoformat(saved_at)
        if parsed_saved_at.tzinfo is None:
            raise RuntimeError("stored Teams Workflow binding timestamp is timezone-naive")
        tested = await self.test(command)
        return TeamsWorkflowTestResult(
            request_id=tested.request_id,
            saved=True,
            binding_version=version,
            saved_at=parsed_saved_at,
            accepted=tested.accepted,
            provider_status=tested.provider_status,
            workflow_run_id=tested.workflow_run_id,
            tested_at=tested.tested_at,
        )

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
            saved=False,
            binding_version="",
            saved_at=completed_at,
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


def _binding_key(request_id: str) -> str:
    digest = hashlib.sha256(request_id.encode("utf-8")).hexdigest()
    return f"operator-teams-workflow-binding:{digest}"


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
        saved=False,
        binding_version="",
        saved_at=parsed_at,
        accepted=True,
        provider_status=provider_status,
        workflow_run_id=workflow_run_id,
        tested_at=parsed_at,
    )


__all__ = [
    "TeamsWorkflowDiagnosticTester",
    "TeamsWorkflowBindingUnavailableError",
    "TeamsWorkflowProviderResponse",
    "TeamsWorkflowTestConflictError",
    "TeamsWorkflowTestProviderError",
    "validate_teams_workflow_url",
]
