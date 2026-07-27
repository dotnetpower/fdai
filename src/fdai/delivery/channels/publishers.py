"""Credential-backed reply publishers for bidirectional ChatOps channels."""

from __future__ import annotations

import re
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from typing import Any, Final
from urllib.parse import urlparse

import httpx

from fdai.delivery.channels.publisher_rendering import (
    operation_fallback_text as _operation_fallback_text,
)
from fdai.delivery.channels.publisher_rendering import (
    render_slack_text as _render_slack_text,
)
from fdai.delivery.channels.publisher_rendering import (
    slack_activity_blocks as _slack_activity_blocks,
)
from fdai.delivery.channels.publisher_rendering import (
    slack_update_body as _slack_update_body,
)
from fdai.delivery.channels.publisher_rendering import (
    teams_activity_omission_count as _teams_activity_omission_count,
)
from fdai.delivery.channels.publisher_rendering import (
    teams_message_body as _teams_message_body,
)
from fdai.shared.providers.conversation_channel import (
    ChannelDeliveryError,
    ChannelDeliveryOperation,
    ChannelDeliveryReceipt,
    ChannelProgressStatus,
    ChannelProgressUpdate,
    ChannelThreadMode,
    ConversationChannelKind,
    ObservedExecutionActivity,
    OutboundResponse,
)
from fdai.shared.providers.workload_identity import WorkloadIdentity
from fdai.shared.telemetry import ConversationProgressMetrics

_SAFE_ACTIVITY_ID: Final = re.compile(r"^[A-Za-z0-9._:-]+$")


@dataclass(frozen=True, slots=True)
class SlackReplyPublisherConfig:
    api_url: str = "https://slack.com/api/chat.postMessage"
    update_api_url: str = "https://slack.com/api/chat.update"
    reaction_api_url: str = "https://slack.com/api/reactions.add"
    timeout_seconds: float = 10.0
    supports_mentions: bool = True
    supports_streaming: bool = True
    supports_edits: bool = True
    supports_reactions: bool = True

    def __post_init__(self) -> None:
        for endpoint in (self.api_url, self.update_api_url, self.reaction_api_url):
            _require_https(endpoint)
        if self.timeout_seconds <= 0:
            raise ValueError("Slack reply timeout MUST be positive")


class SlackWebApiReplyPublisher:
    """Post thread replies through a configured Slack app token."""

    def __init__(
        self,
        *,
        config: SlackReplyPublisherConfig,
        token: str,
        http_client: httpx.AsyncClient,
        progress_metrics: ConversationProgressMetrics | None = None,
    ) -> None:
        if not token:
            raise ValueError("Slack reply token MUST be non-empty")
        self._config = config
        self._token: Final = token
        self._http = http_client
        self._progress_metrics = progress_metrics

    async def publish(self, response: OutboundResponse) -> ChannelDeliveryReceipt:
        if response.channel_kind is not ConversationChannelKind.SLACK:
            raise ValueError("Slack publisher received a non-Slack response")
        operation = response.operation
        if operation is ChannelDeliveryOperation.STREAM and self._config.supports_streaming:
            return await self._publish_stream(response)
        if operation is ChannelDeliveryOperation.EDIT and self._config.supports_edits:
            return await self._publish_edit(response)
        if operation is ChannelDeliveryOperation.REACTION and self._config.supports_reactions:
            return await self._publish_reaction(response)
        degraded = operation is not ChannelDeliveryOperation.POST or (
            bool(response.mentions) and not self._config.supports_mentions
        )
        message_id = await self._post_message(
            response,
            text=_render_slack_text(
                response,
                response.text,
                native_mentions=self._config.supports_mentions,
                include_operation_fallback=degraded,
            ),
        )
        return _receipt(response, message_id, degraded_to_text=degraded)

    async def _publish_stream(self, response: OutboundResponse) -> ChannelDeliveryReceipt:
        if response.progress_updates:
            return await self._publish_progress_updates(response)
        visible = response.stream_chunks[0]
        message_id = await self._post_message(
            response,
            text=_render_slack_text(
                response,
                visible,
                native_mentions=self._config.supports_mentions,
            ),
        )
        for chunk in response.stream_chunks[1:]:
            visible += chunk
            await self._acknowledged_update(
                self._config.update_api_url,
                _slack_update_body(
                    response,
                    message_id=message_id,
                    text=visible,
                    native_mentions=self._config.supports_mentions,
                ),
            )
        if visible != response.text:
            await self._acknowledged_update(
                self._config.update_api_url,
                _slack_update_body(
                    response,
                    message_id=message_id,
                    text=response.text,
                    native_mentions=self._config.supports_mentions,
                ),
            )
        return _receipt(
            response,
            message_id,
            degraded_to_text=bool(response.mentions and not self._config.supports_mentions),
        )

    async def _publish_progress_updates(
        self,
        response: OutboundResponse,
    ) -> ChannelDeliveryReceipt:
        started = time.monotonic()
        snapshots = tuple(
            _progress_response(response, update) for update in response.progress_updates
        )
        message_id = await self._post_message(
            snapshots[0],
            text=_render_slack_text(
                snapshots[0],
                snapshots[0].text,
                native_mentions=self._config.supports_mentions,
            ),
        )
        self._record_progress_latency("time_to_first_progress", started)
        for snapshot in snapshots[1:]:
            await self._acknowledged_update(
                self._config.update_api_url,
                _slack_update_body(
                    snapshot,
                    message_id=message_id,
                    text=snapshot.text,
                    native_mentions=self._config.supports_mentions,
                ),
            )
        self._record_progress_latency("time_to_first_confirmed", started)
        if self._progress_metrics is not None:
            self._progress_metrics.increment("terminal_completed")
            if _response_truncated(response, 2_800):
                self._progress_metrics.increment("truncations")
        return _receipt(
            response,
            message_id,
            degraded_to_text=bool(response.mentions and not self._config.supports_mentions),
        )

    async def _acknowledged_update(
        self,
        endpoint: str,
        body: Mapping[str, object],
    ) -> Mapping[str, Any]:
        try:
            return await self._call(endpoint, body)
        except ChannelDeliveryError as exc:
            if self._progress_metrics is not None:
                self._progress_metrics.increment("channel_update_ambiguous")
            raise ChannelDeliveryError(
                "Slack update failed after the initial message was acknowledged",
                code=exc.code,
                acknowledgement_ambiguous=True,
            ) from exc

    def _record_progress_latency(self, name: str, started: float) -> None:
        if self._progress_metrics is not None:
            self._progress_metrics.observe_latency(
                name,
                max(0, int((time.monotonic() - started) * 1000)),
            )

    async def _publish_edit(self, response: OutboundResponse) -> ChannelDeliveryReceipt:
        message_id = response.edit_message_id
        if message_id is None:
            raise ValueError("Slack edit requires edit_message_id")
        await self._call(
            self._config.update_api_url,
            _slack_update_body(
                response,
                message_id=message_id,
                text=response.text,
                native_mentions=self._config.supports_mentions,
            ),
        )
        return _receipt(
            response,
            message_id,
            degraded_to_text=bool(response.mentions and not self._config.supports_mentions),
        )

    async def _publish_reaction(self, response: OutboundResponse) -> ChannelDeliveryReceipt:
        reaction = response.reaction
        if reaction is None:
            raise ValueError("Slack reaction requires a reaction name")
        await self._call(
            self._config.reaction_api_url,
            {
                "channel": response.channel_id,
                "timestamp": response.in_reply_to,
                "name": reaction,
            },
        )
        return _receipt(response, response.in_reply_to)

    async def _post_message(self, response: OutboundResponse, *, text: str) -> str:
        body: dict[str, object] = {
            "channel": response.channel_id,
            "text": text,
        }
        if response.activities:
            body["blocks"] = _slack_activity_blocks(response, text)
        if response.thread_id is not None:
            body["thread_ts"] = response.thread_id
        payload = await self._call(self._config.api_url, body)
        message_id = payload.get("ts")
        if not isinstance(message_id, str) or not message_id:
            raise ChannelDeliveryError(
                "Slack reply did not include a delivery acknowledgement",
                code="ack_missing",
                acknowledgement_ambiguous=True,
            )
        return message_id

    async def _call(self, endpoint: str, body: Mapping[str, object]) -> Mapping[str, Any]:
        try:
            result = await self._http.post(
                endpoint,
                headers={"Authorization": f"Bearer {self._token}"},
                json=body,
                timeout=self._config.timeout_seconds,
            )
        except httpx.HTTPError as exc:
            raise ChannelDeliveryError(
                "Slack reply transport failed",
                code="transport_interrupted",
                acknowledgement_ambiguous=True,
            ) from exc
        if not result.is_success:
            raise ChannelDeliveryError(
                f"Slack reply returned HTTP {result.status_code}",
                code=f"http_{result.status_code}",
                acknowledgement_ambiguous=False,
            )
        try:
            payload = result.json()
        except ValueError as exc:
            raise ChannelDeliveryError(
                "Slack reply returned invalid JSON",
                code="ack_invalid",
                acknowledgement_ambiguous=True,
            ) from exc
        if not isinstance(payload, Mapping) or payload.get("ok") is not True:
            raise ChannelDeliveryError(
                "Slack reply was not accepted",
                code="provider_rejected",
                acknowledgement_ambiguous=False,
            )
        return payload


@dataclass(frozen=True, slots=True)
class TeamsReplyPublisherConfig:
    audience: str = "https://api.botframework.com"
    timeout_seconds: float = 10.0
    supports_mentions: bool = True
    supports_streaming: bool = True
    supports_edits: bool = True
    supports_reactions: bool = True

    def __post_init__(self) -> None:
        if not self.audience or self.timeout_seconds <= 0:
            raise ValueError("Teams reply audience and timeout MUST be valid")


class TeamsBotFrameworkReplyPublisher:
    """Post through server-owned conversation endpoints with workload identity."""

    def __init__(
        self,
        *,
        config: TeamsReplyPublisherConfig,
        identity: WorkloadIdentity,
        endpoint_resolver: Callable[[str], str],
        http_client: httpx.AsyncClient,
        progress_metrics: ConversationProgressMetrics | None = None,
    ) -> None:
        self._config = config
        self._identity = identity
        self._endpoint_resolver = endpoint_resolver
        self._http = http_client
        self._progress_metrics = progress_metrics

    async def publish(self, response: OutboundResponse) -> ChannelDeliveryReceipt:
        if response.channel_kind is not ConversationChannelKind.TEAMS:
            raise ValueError("Teams publisher received a non-Teams response")
        endpoint = self._endpoint_resolver(response.channel_id)
        _require_https(endpoint)
        token = await self._identity.get_token(self._config.audience)
        operation = response.operation
        if operation is ChannelDeliveryOperation.STREAM and self._config.supports_streaming:
            return await self._publish_stream(response, endpoint=endpoint, token=token.token)
        if operation is ChannelDeliveryOperation.EDIT and self._config.supports_edits:
            return await self._publish_edit(response, endpoint=endpoint, token=token.token)
        if operation is ChannelDeliveryOperation.REACTION and self._config.supports_reactions:
            return await self._publish_reaction(response, endpoint=endpoint, token=token.token)
        degraded = operation is not ChannelDeliveryOperation.POST or (
            bool(response.mentions) and not self._config.supports_mentions
        )
        body = _teams_message_body(
            response,
            _operation_fallback_text(response) if degraded else response.text,
            native_mentions=self._config.supports_mentions,
        )
        if response.thread_mode is ChannelThreadMode.ORIGIN and response.in_reply_to:
            body["replyToId"] = response.in_reply_to
        payload = await self._request("POST", endpoint, body, token=token.token)
        message_id = _teams_acknowledgement(payload)
        return _receipt(response, message_id, degraded_to_text=degraded)

    async def _publish_stream(
        self,
        response: OutboundResponse,
        *,
        endpoint: str,
        token: str,
    ) -> ChannelDeliveryReceipt:
        if response.progress_updates:
            return await self._publish_progress_updates(
                response,
                endpoint=endpoint,
                token=token,
            )
        visible = response.stream_chunks[0]
        initial = _teams_message_body(
            response,
            visible,
            native_mentions=self._config.supports_mentions,
        )
        initial["replyToId"] = response.in_reply_to
        message_id = _teams_acknowledgement(
            await self._request("POST", endpoint, initial, token=token)
        )
        update_endpoint = _activity_endpoint(endpoint, message_id)
        for chunk in response.stream_chunks[1:]:
            visible += chunk
            await self._acknowledged_update(
                "PUT",
                update_endpoint,
                _teams_message_body(
                    response,
                    visible,
                    native_mentions=self._config.supports_mentions,
                ),
                token=token,
            )
        if visible != response.text:
            await self._acknowledged_update(
                "PUT",
                update_endpoint,
                _teams_message_body(
                    response,
                    response.text,
                    native_mentions=self._config.supports_mentions,
                ),
                token=token,
            )
        return _receipt(
            response,
            message_id,
            degraded_to_text=bool(response.mentions and not self._config.supports_mentions),
        )

    async def _publish_progress_updates(
        self,
        response: OutboundResponse,
        *,
        endpoint: str,
        token: str,
    ) -> ChannelDeliveryReceipt:
        started = time.monotonic()
        snapshots = tuple(
            _progress_response(response, update) for update in response.progress_updates
        )
        initial = _teams_message_body(
            snapshots[0],
            snapshots[0].text,
            native_mentions=self._config.supports_mentions,
        )
        initial["replyToId"] = response.in_reply_to
        message_id = _teams_acknowledgement(
            await self._request("POST", endpoint, initial, token=token)
        )
        self._record_progress_latency("time_to_first_progress", started)
        update_endpoint = _activity_endpoint(endpoint, message_id)
        for snapshot in snapshots[1:]:
            await self._acknowledged_update(
                "PUT",
                update_endpoint,
                _teams_message_body(
                    snapshot,
                    snapshot.text,
                    native_mentions=self._config.supports_mentions,
                ),
                token=token,
            )
        self._record_progress_latency("time_to_first_confirmed", started)
        if self._progress_metrics is not None:
            self._progress_metrics.increment("terminal_completed")
            if (
                _response_truncated(response, 4_000)
                or _teams_activity_omission_count(response, response.text) > 0
            ):
                self._progress_metrics.increment("truncations")
        return _receipt(
            response,
            message_id,
            degraded_to_text=bool(response.mentions and not self._config.supports_mentions),
        )

    async def _acknowledged_update(
        self,
        method: str,
        endpoint: str,
        body: Mapping[str, Any],
        *,
        token: str,
    ) -> Mapping[str, Any] | None:
        try:
            return await self._request(method, endpoint, body, token=token)
        except ChannelDeliveryError as exc:
            if self._progress_metrics is not None:
                self._progress_metrics.increment("channel_update_ambiguous")
            raise ChannelDeliveryError(
                "Teams update failed after the initial message was acknowledged",
                code=exc.code,
                acknowledgement_ambiguous=True,
            ) from exc

    def _record_progress_latency(self, name: str, started: float) -> None:
        if self._progress_metrics is not None:
            self._progress_metrics.observe_latency(
                name,
                max(0, int((time.monotonic() - started) * 1000)),
            )

    async def _publish_edit(
        self,
        response: OutboundResponse,
        *,
        endpoint: str,
        token: str,
    ) -> ChannelDeliveryReceipt:
        message_id = response.edit_message_id
        if message_id is None:
            raise ValueError("Teams edit requires edit_message_id")
        await self._request(
            "PUT",
            _activity_endpoint(endpoint, message_id),
            _teams_message_body(
                response,
                response.text,
                native_mentions=self._config.supports_mentions,
            ),
            token=token,
        )
        return _receipt(response, message_id)

    async def _publish_reaction(
        self,
        response: OutboundResponse,
        *,
        endpoint: str,
        token: str,
    ) -> ChannelDeliveryReceipt:
        reaction = response.reaction
        if reaction is None:
            raise ValueError("Teams reaction requires a reaction name")
        payload = await self._request(
            "POST",
            endpoint,
            {
                "type": "messageReaction",
                "replyToId": response.in_reply_to,
                "reactionsAdded": [{"type": reaction}],
            },
            token=token,
        )
        message_id = _optional_teams_acknowledgement(payload) or response.in_reply_to
        return _receipt(response, message_id)

    async def _request(
        self,
        method: str,
        endpoint: str,
        body: Mapping[str, Any],
        *,
        token: str,
    ) -> Mapping[str, Any] | None:
        try:
            result = await self._http.request(
                method,
                endpoint,
                headers={"Authorization": f"Bearer {token}"},
                json=body,
                timeout=self._config.timeout_seconds,
            )
        except httpx.HTTPError as exc:
            raise ChannelDeliveryError(
                "Teams reply transport failed",
                code="transport_interrupted",
                acknowledgement_ambiguous=True,
            ) from exc
        if not result.is_success:
            raise ChannelDeliveryError(
                f"Teams reply returned HTTP {result.status_code}",
                code=f"http_{result.status_code}",
                acknowledgement_ambiguous=False,
            )
        if not result.content:
            return None
        try:
            payload = result.json()
        except ValueError as exc:
            raise ChannelDeliveryError(
                "Teams reply returned invalid JSON",
                code="ack_invalid",
                acknowledgement_ambiguous=True,
            ) from exc
        if not isinstance(payload, Mapping):
            raise ChannelDeliveryError(
                "Teams reply acknowledgement is invalid",
                code="ack_invalid",
                acknowledgement_ambiguous=True,
            )
        return payload


def _activity_endpoint(base: str, message_id: str) -> str:
    if _SAFE_ACTIVITY_ID.fullmatch(message_id) is None:
        raise ValueError("Teams activity id contains unsupported characters")
    endpoint = f"{base.rstrip('/')}/{message_id}"
    _require_https(endpoint)
    return endpoint


def _teams_acknowledgement(payload: Mapping[str, Any] | None) -> str:
    message_id = _optional_teams_acknowledgement(payload)
    if message_id is None:
        raise ChannelDeliveryError(
            "Teams reply did not include a delivery acknowledgement",
            code="ack_missing",
            acknowledgement_ambiguous=True,
        )
    return message_id


def _optional_teams_acknowledgement(payload: Mapping[str, Any] | None) -> str | None:
    message_id = payload.get("id") if payload is not None else None
    return message_id if isinstance(message_id, str) and message_id else None


def _receipt(
    response: OutboundResponse,
    message_id: str,
    *,
    degraded_to_text: bool = False,
) -> ChannelDeliveryReceipt:
    return ChannelDeliveryReceipt(
        channel_kind=response.channel_kind,
        channel_id=response.channel_id,
        operation=response.operation,
        message_id=message_id,
        degraded_to_text=degraded_to_text,
    )


def _progress_response(
    response: OutboundResponse,
    update: ChannelProgressUpdate,
) -> OutboundResponse:
    return replace(
        response,
        text=update.text,
        activities=(
            response.activities[: update.activity_count]
            if update.status is ChannelProgressStatus.CONFIRMED
            else ()
        ),
        stream_chunks=(),
        progress_updates=(),
    )


def _response_truncated(response: OutboundResponse, output_limit: int) -> bool:
    return any(
        isinstance(activity, ObservedExecutionActivity)
        and (activity.output_truncated or len(activity.output) > output_limit)
        for activity in response.activities
    )


def _require_https(value: str) -> None:
    parsed = urlparse(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("reply endpoint MUST be an HTTPS URL without credentials or query")


__all__ = [
    "SlackReplyPublisherConfig",
    "SlackWebApiReplyPublisher",
    "TeamsBotFrameworkReplyPublisher",
    "TeamsReplyPublisherConfig",
]
