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
    describe_binding_metadata as _describe_binding_metadata,
)
from fdai_operator_service.teams_workflow_diagnostic_helpers import (
    endpoint_identifier as _endpoint_identifier,
)
from fdai_operator_service.teams_workflow_diagnostic_helpers import (
    merged_actor_email_recipients as _merged_actor_email_recipients,
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
    record_channel_test_outcomes as _record_channel_test_outcomes,
)
from fdai_operator_service.teams_workflow_diagnostic_helpers import (
    send_synthetic_test_email as _send_synthetic_test_email,
)
from fdai_operator_service.teams_workflow_diagnostic_helpers import (
    synthetic_card as _synthetic_card,
)
from fdai_operator_service.teams_workflow_diagnostic_helpers import (
    updated_preferences_metadata as _updated_preferences_metadata,
)
from fdai_operator_service.teams_workflow_diagnostic_helpers import (
    validate_channel_id as _validate_channel_id,
)
from fdai_operator_service.teams_workflow_diagnostic_helpers import (
    validate_teams_workflow_url,
)

_REQUEST_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
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
            if command.clear_binding:
                clear_fn = getattr(self.binding_store, "clear_all", None)
                if callable(clear_fn):
                    await clear_fn()
                now = self.clock().astimezone(UTC)
                prior_meta = await self.store.read_state(_ACTIVE_BINDING_METADATA_KEY)
                await self.store.write_state(
                    _ACTIVE_BINDING_METADATA_KEY,
                    {
                        **(dict(prior_meta) if isinstance(prior_meta, Mapping) else {}),
                        "kind": "operator.teams-workflow-binding-metadata",
                        "binding_version": "",
                        "saved_at": now.isoformat(),
                        "actor_id": command.actor_id,
                        "channels": [],
                    },
                )
                return TeamsWorkflowTestResult(
                    request_id=command.request_id,
                    saved=True,
                    binding_version="cleared",
                    saved_at=now,
                    accepted=True,
                    provider_status=200,
                    workflow_run_id=None,
                    tested_at=now,
                )
            saved = await self.binding_store.load()
            if saved is None:
                raise TeamsWorkflowBindingUnavailableError(
                    "Teams Workflow binding is not configured"
                )
            if (
                command.selected_channel_ids is not None
                or command.delivery_targets is not None
                or command.remove_channel_id is not None
                or command.rename_channel_id is not None
                or command.email_recipient_mode is not None
                or command.custom_email is not None
            ):
                await self._update_channel_preferences(
                    actor_id=command.actor_id,
                    saved=saved,
                    selected_channel_ids=command.selected_channel_ids,
                    delivery_targets=command.delivery_targets,
                    remove_channel_id=command.remove_channel_id,
                    rename_channel_id=command.rename_channel_id,
                    channel_label=command.channel_label,
                    email_recipient_mode=command.email_recipient_mode,
                    custom_email=command.custom_email,
                )
            if command.test_email:
                meta = await self.store.read_state(_ACTIVE_BINDING_METADATA_KEY)
                _, resolved_email = _normalized_email_recipient(
                    command.email_recipient_mode,
                    command.custom_email,
                    prior_meta=meta,
                    actor_id=command.actor_id,
                )
                target_email = resolved_email or (command.custom_email or "").strip()
                if not target_email:
                    raise ValueError("custom_email is required to send a synthetic test email")
                try:
                    status_code, op_id = await _send_synthetic_test_email(
                        target_email,
                        request_id=command.request_id,
                    )
                except (OSError, RuntimeError) as exc:
                    raise TeamsWorkflowTestProviderError(str(exc), status_code=502) from exc
                now = self.clock().astimezone(UTC)
                accepted = 200 <= status_code < 300
                return TeamsWorkflowTestResult(
                    request_id=command.request_id,
                    saved=True,
                    binding_version=saved.version,
                    saved_at=now,
                    accepted=accepted,
                    provider_status=status_code,
                    workflow_run_id=op_id,
                    tested_at=now,
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
                test_channel_id=command.test_channel_id,
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
            actor_id=command.actor_id,
        )
        actor_emails = _merged_actor_email_recipients(
            prior_meta,
            actor_id=command.actor_id,
            email_mode=email_mode,
            custom_email=custom_email,
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
                "actor_email_recipients": actor_emails,
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
        """Return secret-free saved-binding metadata for an authorized reader."""
        if not actor_id.strip():
            raise ValueError("Teams Workflow binding actor_id MUST be non-empty")
        if self.binding_store is None:
            raise TeamsWorkflowBindingUnavailableError(
                "Teams Workflow binding storage is not configured"
            )
        saved = await self.binding_store.load()
        if saved is None:
            return None
        record = await self.store.read_state(_ACTIVE_BINDING_METADATA_KEY)
        return _describe_binding_metadata(
            record,
            actor_id=actor_id,
            binding_version=saved.version,
            endpoint_digest=saved.endpoint_digest,
            webhook_url=saved.webhook_url,
            observed_at_iso=self.clock().astimezone(UTC).isoformat(),
        )

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
        rename_channel_id: str | None = None,
        channel_label: str | None = None,
        email_recipient_mode: str | None = None,
        custom_email: str | None = None,
    ) -> None:
        record = await self.store.read_state(_ACTIVE_BINDING_METADATA_KEY)
        raw_saved_at = record.get("saved_at") if record is not None else None
        saved_at_val = (
            raw_saved_at
            if isinstance(raw_saved_at, str)
            else self.clock().astimezone(UTC).isoformat()
        )
        updated = _updated_preferences_metadata(
            record,
            actor_id=actor_id,
            fallback_channel_id=_channel_id(saved.endpoint_digest),
            fallback_label=_default_channel_label(saved.webhook_url),
            fallback_version=saved.version,
            fallback_identifier=_endpoint_identifier(saved.webhook_url),
            saved_at_val=saved_at_val,
            selected_channel_ids=selected_channel_ids,
            delivery_targets=delivery_targets,
            remove_channel_id=remove_channel_id,
            rename_channel_id=rename_channel_id,
            channel_label=channel_label,
            email_recipient_mode=email_recipient_mode,
            custom_email=custom_email,
        )
        if remove_channel_id is not None:
            delete_ch = getattr(self.binding_store, "delete_channel", None)
            if callable(delete_ch):
                await delete_ch(remove_channel_id)
        await self.store.write_state(_ACTIVE_BINDING_METADATA_KEY, updated)

    async def _test_saved_binding(
        self,
        *,
        actor_id: str,
        request_id: str,
        saved: LoadedTeamsWorkflowBinding,
        test_channel_id: str | None = None,
    ) -> TeamsWorkflowTestResult:
        if test_channel_id is not None:
            _validate_channel_id(test_channel_id, field_name="test_channel_id")
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
        target_ids = (
            [test_channel_id]
            if test_channel_id is not None
            else (
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
        )
        channels_to_test: list[tuple[str, str]] = []
        if callable(load_channel) and (test_channel_id is not None or len(target_ids) > 1):
            for cid in target_ids:
                loaded_ch = await load_channel(cid)
                if loaded_ch is not None and all(
                    u != loaded_ch.webhook_url for _, u in channels_to_test
                ):
                    channels_to_test.append((cid, loaded_ch.webhook_url))
        if not channels_to_test:
            fallback_cid = target_ids[0] if target_ids else _channel_id(saved.endpoint_digest)
            channels_to_test = [(fallback_cid, saved.webhook_url)]
        outcomes: dict[str, dict[str, object]] = {}
        first_result: TeamsWorkflowTestResult | None = None
        first_error: TeamsWorkflowTestProviderError | None = None
        for idx, (cid, target_url) in enumerate(channels_to_test, start=1):
            sub_request_id = request_id if idx == 1 else f"{request_id}-ch{idx}"[:128]
            try:
                tested = await self.test(
                    TeamsWorkflowTestCommand(
                        actor_id=actor_id,
                        request_id=sub_request_id,
                        webhook_url=target_url,
                    )
                )
                outcomes[cid] = {
                    "last_tested_at": tested.tested_at.isoformat(),
                    "last_test_status": tested.provider_status,
                    "last_test_accepted": tested.accepted,
                }
                if first_result is None:
                    first_result = tested
            except TeamsWorkflowTestProviderError as exc:
                outcomes[cid] = {
                    "last_tested_at": self.clock().astimezone(UTC).isoformat(),
                    "last_test_status": exc.status_code,
                    "last_test_accepted": False,
                }
                if first_error is None:
                    first_error = exc
        if isinstance(metadata, Mapping) and isinstance(raw_channels, list) and outcomes:
            await self.store.write_state(
                _ACTIVE_BINDING_METADATA_KEY,
                {
                    **dict(metadata),
                    "channels": _record_channel_test_outcomes(
                        [dict(item) for item in raw_channels if isinstance(item, Mapping)],
                        outcomes,
                    ),
                },
            )
        if first_error is not None:
            return TeamsWorkflowTestResult(
                request_id=request_id,
                saved=True,
                binding_version=saved.version,
                saved_at=parsed_saved_at,
                accepted=False,
                provider_status=first_error.status_code,
                workflow_run_id=None,
                tested_at=self.clock().astimezone(UTC),
            )
        if first_result is None:
            raise TeamsWorkflowTestProviderError("Teams Workflow acknowledgement was not observed")
        return TeamsWorkflowTestResult(
            request_id=first_result.request_id,
            saved=True,
            binding_version=saved.version,
            saved_at=parsed_saved_at,
            accepted=first_result.accepted,
            provider_status=first_result.provider_status,
            workflow_run_id=first_result.workflow_run_id,
            tested_at=first_result.tested_at,
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
    return f"operator-teams-workflow-test:{hashlib.sha256(request_id.encode('utf-8')).hexdigest()}"


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
