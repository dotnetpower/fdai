"""Bounded one-time Microsoft Teams Workflows notification diagnostics."""

from __future__ import annotations

import hashlib
import json
import re
import secrets
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
    LoadedTeamsWorkflowBinding,
    TeamsWorkflowBindingError,
    TeamsWorkflowBindingStore,
)
from fdai_operator_service.teams_workflow_diagnostic_helpers import (
    channel_id_for_digest as _channel_id,
)
from fdai_operator_service.teams_workflow_diagnostic_helpers import (
    default_channel_label as _default_channel_label,
)
from fdai_operator_service.teams_workflow_diagnostic_helpers import (
    endpoint_identifier as _endpoint_identifier,
)
from fdai_operator_service.teams_workflow_diagnostic_helpers import (
    merged_channels as _merged_channels,
)
from fdai_operator_service.teams_workflow_diagnostic_helpers import (
    normalized_delivery_targets as _normalized_delivery_targets,
)
from fdai_operator_service.teams_workflow_diagnostic_helpers import (
    normalized_email_recipient as _normalized_email_recipient,
)
from fdai_operator_service.teams_workflow_diagnostic_helpers import (
    projected_channels as _projected_channels,
)
from fdai_operator_service.teams_workflow_diagnostic_helpers import (
    synthetic_card as _synthetic_card,
)
from fdai_operator_service.teams_workflow_diagnostic_helpers import (
    validate_channel_id as _validate_channel_id,
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

    def __init__(self, message: str, *, status_code: int = 0) -> None:
        super().__init__(message)
        self.status_code = status_code


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
        if not command.actor_id.strip():
            raise ValueError("Teams Workflow test actor_id MUST be non-empty")
        if not _REQUEST_ID.fullmatch(command.request_id):
            raise ValueError("Teams Workflow test request_id is invalid")
        if command.channel_label is not None and any(
            ord(ch) < 32 or ord(ch) == 127 for ch in command.channel_label
        ):
            raise ValueError("Teams Workflow channel_label MUST NOT contain control characters")
        if self.binding_store is None:
            raise TeamsWorkflowBindingUnavailableError(
                "Teams Workflow binding storage is not configured"
            )
        if not command.webhook_url.strip():
            saved = await self.binding_store.load()
            if saved is None:
                raise TeamsWorkflowBindingUnavailableError(
                    "Teams Workflow binding is not configured"
                )
            if (
                command.selected_channel_ids is not None
                or command.delivery_targets is not None
                or command.remove_channel_id is not None
                or command.email_recipient_mode is not None
                or command.custom_email is not None
            ):
                await self._update_channel_preferences(
                    actor_id=command.actor_id,
                    saved=saved,
                    selected_channel_ids=command.selected_channel_ids,
                    delivery_targets=command.delivery_targets,
                    remove_channel_id=command.remove_channel_id,
                    email_recipient_mode=command.email_recipient_mode,
                    custom_email=command.custom_email,
                )
            if command.selection_only:
                now = self.clock().astimezone(UTC)
                return TeamsWorkflowTestResult(
                    request_id=command.request_id,
                    saved=True,
                    binding_version=saved.version,
                    saved_at=now,
                    accepted=True,
                    provider_status=200,
                    workflow_run_id=None,
                    tested_at=now,
                )
            return await self._test_saved_binding(
                actor_id=command.actor_id,
                request_id=command.request_id,
                saved=saved,
            )
        endpoint_digest = validate_teams_workflow_url(command.webhook_url)
        channel_id = _channel_id(endpoint_digest)
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
            save_channel = getattr(self.binding_store, "save_channel_and_verify", None)
            if callable(save_channel):
                saved = await save_channel(
                    channel_id=channel_id,
                    webhook_url=command.webhook_url,
                    request_id=command.request_id,
                )
            else:
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
        prior_meta = await self.store.read_state(_ACTIVE_BINDING_METADATA_KEY)
        channels = _merged_channels(
            prior_meta,
            channel_id=channel_id,
            label=command.channel_label or _default_channel_label(command.webhook_url),
            binding_version=saved.version,
            endpoint_identifier_val=_endpoint_identifier(command.webhook_url),
            saved_at=saved_at.isoformat(),
            selected_channel_ids=command.selected_channel_ids,
        )
        delivery_targets = _normalized_delivery_targets(
            command.delivery_targets,
            prior_meta=prior_meta,
        )
        email_mode, custom_email = _normalized_email_recipient(
            command.email_recipient_mode,
            command.custom_email,
            prior_meta=prior_meta,
        )
        await self.store.write_state(
            _ACTIVE_BINDING_METADATA_KEY,
            {
                "kind": "operator.teams-workflow-binding-metadata",
                "binding_version": saved.version,
                "saved_at": saved_at.isoformat(),
                "actor_id": command.actor_id,
                "channels": channels,
                "delivery_targets": list(delivery_targets),
                "email_recipient_mode": email_mode,
                "custom_email": custom_email,
            },
        )
        return await self._test_saved_binding(
            actor_id=command.actor_id,
            request_id=command.request_id,
            saved=saved,
        )

    async def describe_binding(
        self,
        *,
        actor_id: str,
    ) -> Mapping[str, object] | None:
        """Return secret-free saved-binding metadata for an authorized reader.

        The default read returns only metadata so the Console can render a
        masked endpoint representation; explicit reveals go through
        :meth:`reveal_binding`. ``saved_at`` is present only when the durable
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
        endpoint_id = _endpoint_identifier(saved.webhook_url)
        record = await self.store.read_state(_ACTIVE_BINDING_METADATA_KEY)
        saved_at_val: str | None = None
        if record is not None and record.get("binding_version") == saved.version:
            raw_saved_at = record.get("saved_at")
            if isinstance(raw_saved_at, str):
                saved_at_val = raw_saved_at
        channels = _projected_channels(
            record,
            fallback_channel_id=_channel_id(saved.endpoint_digest),
            fallback_label=_default_channel_label(saved.webhook_url),
            fallback_version=saved.version,
            fallback_identifier=endpoint_id,
            fallback_saved_at=saved_at_val,
        )
        delivery_targets = list(_normalized_delivery_targets(None, prior_meta=record))
        email_mode, custom_email = _normalized_email_recipient(
            None,
            None,
            prior_meta=record,
        )
        metadata: dict[str, object] = {
            "binding_version": saved.version,
            "endpoint_identifier": endpoint_id,
            "observed_at": observed_at.isoformat(),
            "channels": channels,
            "delivery_targets": delivery_targets,
            "email_recipient_mode": email_mode,
            "custom_email": custom_email,
        }
        if saved_at_val is not None:
            metadata["saved_at"] = saved_at_val
        return metadata

    async def reveal_binding(
        self,
        *,
        actor_id: str,
        channel_id: str | None = None,
    ) -> Mapping[str, object] | None:
        """Audit and return the saved endpoint for an authorized secret reader."""
        if not actor_id.strip():
            raise ValueError("Teams Workflow reveal actor_id MUST be non-empty")
        if channel_id is not None:
            _validate_channel_id(channel_id)
        if self.binding_store is None:
            raise TeamsWorkflowBindingUnavailableError(
                "Teams Workflow binding storage is not configured"
            )
        load_channel = getattr(self.binding_store, "load_channel", None)
        if channel_id and callable(load_channel):
            saved = await load_channel(channel_id)
        else:
            saved = await self.binding_store.load()
        if saved is None:
            return None
        revealed_at = self.clock().astimezone(UTC)
        request_id = f"teams-workflow-reveal-{secrets.token_hex(16)}"
        await self.store.write_state(
            _reveal_key(request_id),
            {
                "kind": "operator.teams-workflow-binding-reveal",
                "request_id": request_id,
                "actor_id": actor_id,
                "endpoint_digest": saved.endpoint_digest,
                "binding_version": saved.version,
                "phase": "completed",
                "outcome": "revealed",
                "completed_at": revealed_at.isoformat(),
            },
        )
        result: dict[str, object] = {
            "binding_version": saved.version,
            "endpoint_identifier": _endpoint_identifier(saved.webhook_url),
            "webhook_url": saved.webhook_url,
            "revealed_at": revealed_at.isoformat(),
        }
        if channel_id:
            result["channel_id"] = channel_id
        return result

    async def _update_channel_preferences(
        self,
        *,
        actor_id: str,
        saved: LoadedTeamsWorkflowBinding,
        selected_channel_ids: tuple[str, ...] | None,
        delivery_targets: tuple[str, ...] | None,
        remove_channel_id: str | None,
        email_recipient_mode: str | None = None,
        custom_email: str | None = None,
    ) -> None:
        record = await self.store.read_state(_ACTIVE_BINDING_METADATA_KEY)
        endpoint_id = _endpoint_identifier(saved.webhook_url)
        raw_saved_at = record.get("saved_at") if record is not None else None
        saved_at_val = (
            raw_saved_at
            if isinstance(raw_saved_at, str)
            else self.clock().astimezone(UTC).isoformat()
        )
        channels = _projected_channels(
            record,
            fallback_channel_id=_channel_id(saved.endpoint_digest),
            fallback_label=_default_channel_label(saved.webhook_url),
            fallback_version=saved.version,
            fallback_identifier=endpoint_id,
            fallback_saved_at=saved_at_val,
        )
        if remove_channel_id is not None:
            _validate_channel_id(remove_channel_id, field_name="remove_channel_id")
            if len(channels) <= 1 or not any(
                item.get("channel_id") == remove_channel_id for item in channels
            ):
                raise ValueError(
                    "cannot remove the last remaining or unknown Teams Workflow channel"
                )
            channels = [item for item in channels if item.get("channel_id") != remove_channel_id]
        if selected_channel_ids is not None:
            for cid in selected_channel_ids:
                _validate_channel_id(cid)
            selected_set = set(selected_channel_ids)
            updated_channels: list[dict[str, object]] = []
            for item in channels:
                cid = str(item.get("channel_id", ""))
                updated_channels.append({**item, "enabled": cid in selected_set})
            if not any(bool(item.get("enabled")) for item in updated_channels) and updated_channels:
                updated_channels[0] = {**updated_channels[0], "enabled": True}
            channels = updated_channels
        targets = _normalized_delivery_targets(delivery_targets, prior_meta=record)
        email_mode, normalized_custom_email = _normalized_email_recipient(
            email_recipient_mode,
            custom_email,
            prior_meta=record,
        )
        active_version = str(channels[0].get("binding_version") or saved.version)
        await self.store.write_state(
            _ACTIVE_BINDING_METADATA_KEY,
            {
                "kind": "operator.teams-workflow-binding-metadata",
                "binding_version": active_version,
                "saved_at": saved_at_val,
                "actor_id": actor_id,
                "channels": channels,
                "delivery_targets": list(targets),
                "email_recipient_mode": email_mode,
                "custom_email": normalized_custom_email,
            },
        )

    async def _test_saved_binding(
        self,
        *,
        actor_id: str,
        request_id: str,
        saved: LoadedTeamsWorkflowBinding,
    ) -> TeamsWorkflowTestResult:
        metadata = await self.store.read_state(_ACTIVE_BINDING_METADATA_KEY)
        if metadata is None or metadata.get("binding_version") != saved.version:
            parsed_saved_at = self.clock().astimezone(UTC)
            await self.store.write_state(
                _ACTIVE_BINDING_METADATA_KEY,
                {
                    "kind": "operator.teams-workflow-binding-metadata",
                    "binding_version": saved.version,
                    "saved_at": parsed_saved_at.isoformat(),
                    "actor_id": actor_id,
                },
            )
        else:
            saved_at = metadata.get("saved_at")
            if not isinstance(saved_at, str):
                raise TeamsWorkflowBindingError(
                    "Teams Workflow binding saved timestamp is unavailable"
                )
            parsed_saved_at = datetime.fromisoformat(saved_at)
            if parsed_saved_at.tzinfo is None:
                raise TeamsWorkflowBindingError(
                    "Teams Workflow binding saved timestamp is timezone-naive"
                )
        load_channel = getattr(self.binding_store, "load_channel", None)
        raw_channels = metadata.get("channels") if isinstance(metadata, Mapping) else None
        enabled_channel_ids = (
            [
                str(item.get("channel_id"))
                for item in raw_channels
                if isinstance(item, Mapping)
                and bool(item.get("enabled", True))
                and isinstance(item.get("channel_id"), str)
            ]
            if isinstance(raw_channels, list)
            else []
        )
        urls_to_test: list[str] = []
        if len(enabled_channel_ids) > 1 and callable(load_channel):
            for cid in enabled_channel_ids:
                loaded_ch = await load_channel(cid)
                if loaded_ch is not None and loaded_ch.webhook_url not in urls_to_test:
                    urls_to_test.append(loaded_ch.webhook_url)
        if not urls_to_test:
            urls_to_test = [saved.webhook_url]
        try:
            tested = await self.test(
                TeamsWorkflowTestCommand(
                    actor_id=actor_id,
                    request_id=request_id,
                    webhook_url=urls_to_test[0],
                )
            )
            for idx, extra_url in enumerate(urls_to_test[1:], start=2):
                await self.test(
                    TeamsWorkflowTestCommand(
                        actor_id=actor_id,
                        request_id=f"{request_id}-ch{idx}"[:128],
                        webhook_url=extra_url,
                    )
                )
        except TeamsWorkflowTestProviderError as exc:
            return TeamsWorkflowTestResult(
                request_id=request_id,
                saved=True,
                binding_version=saved.version,
                saved_at=parsed_saved_at,
                accepted=False,
                provider_status=exc.status_code,
                workflow_run_id=None,
                tested_at=self.clock().astimezone(UTC),
            )
        return TeamsWorkflowTestResult(
            request_id=tested.request_id,
            saved=True,
            binding_version=saved.version,
            saved_at=parsed_saved_at,
            accepted=tested.accepted,
            provider_status=tested.provider_status,
            workflow_run_id=tested.workflow_run_id,
            tested_at=tested.tested_at,
        )

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

        payload = _synthetic_card(
            command.request_id,
            endpoint_identifier_val=_endpoint_identifier(command.webhook_url),
            tested_at=now,
        )
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
                f"Teams Workflow rejected the synthetic card with HTTP {response.status_code}",
                status_code=response.status_code,
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


def _test_key(request_id: str) -> str:
    digest = hashlib.sha256(request_id.encode("utf-8")).hexdigest()
    return f"operator-teams-workflow-test:{digest}"


def _binding_key(request_id: str) -> str:
    digest = hashlib.sha256(request_id.encode("utf-8")).hexdigest()
    return f"operator-teams-workflow-binding:{digest}"


def _reveal_key(request_id: str) -> str:
    digest = hashlib.sha256(request_id.encode("utf-8")).hexdigest()
    return f"operator-teams-workflow-binding-reveal:{digest}"


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
