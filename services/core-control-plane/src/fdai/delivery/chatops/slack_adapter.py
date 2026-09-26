"""Outbound-only Slack A1 delivery; callbacks and approval authority live elsewhere."""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Final

import httpx

from fdai.shared.providers.hil_channel import (
    HilApprovalReceipt,
    HilApprovalRequest,
    HilChannel,
    HilChannelError,
    HilDecision,
    HilResponse,
)

SLACK_POST_URL: Final = "https://slack.com/api/chat.postMessage"
HIL_BINDING_FIELD: Final = "idempotency_key"
_OPAQUE: Final = re.compile(r"[A-Za-z0-9._:-]{1,200}\Z")
_CHANNEL: Final = re.compile(r"[A-Z][A-Z0-9]{1,79}\Z")
_MESSAGE_ID: Final = re.compile(r"[0-9]{1,16}\.[0-9]{1,12}\Z")
_SECRET: Final = re.compile(
    r"AccountKey=|SharedAccessKey=|AKIA[0-9A-Z]{16}|xox[baprs]-|ghp_[A-Za-z0-9]{30,}"
)
_MAX_RESPONSE_BYTES: Final = 4096
_MAX_REQUEST_BYTES: Final = 4096
_MAX_ATTEMPTS: Final = 1024


@dataclass(frozen=True, slots=True)
class SlackHilAdapterConfig:
    api_url: str
    channel_id: str
    bot_token: str = field(repr=False)
    timeout_seconds: float = 10.0

    def __post_init__(self) -> None:
        if self.api_url != SLACK_POST_URL:
            raise ValueError("Slack approval API URL MUST be the fixed HTTPS chat.postMessage URL")
        if not _CHANNEL.fullmatch(self.channel_id):
            raise ValueError("Slack approval channel_id MUST be a bounded channel identifier")
        if not self.bot_token or self.bot_token != self.bot_token.strip():
            raise ValueError("Slack approval bot_token MUST be a protected non-empty credential")
        if not math.isfinite(self.timeout_seconds) or self.timeout_seconds <= 0:
            raise ValueError("Slack approval timeout_seconds MUST be finite and positive")


class SlackHilAdapter(HilChannel):
    """Post one bounded non-authorizing card with process-local replay suppression.

    An interrupted acknowledgement is unknown, not rejected: retries within this
    instance are held, and a restart needs durable reconciliation before reposting.
    """

    def __init__(self, *, config: SlackHilAdapterConfig, http_client: httpx.AsyncClient) -> None:
        self._config = config
        self._http = http_client
        self._lock = asyncio.Lock()
        self._attempts: dict[str, tuple[str, HilApprovalReceipt | None]] = {}

    @property
    def channel_id(self) -> str:
        return self._config.channel_id

    def render_payload(self, request: HilApprovalRequest) -> bytes:
        """Return exactly the sanitized bytes sent to the fixed Slack endpoint."""
        context = {
            "approval_id": request.approval_id,
            "correlation_id": request.correlation_id,
            "action_id": request.action_id,
            HIL_BINDING_FIELD: request.metadata.get(HIL_BINDING_FIELD),
            "action_hash": request.action_hash,
        }
        if any(
            not isinstance(value, str) or not _OPAQUE.fullmatch(value) or _SECRET.search(value)
            for value in context.values()
        ):
            raise HilChannelError("Slack approval binding is incomplete or unsafe", approval_id="")
        payload = json.dumps(
            {
                "channel": self._config.channel_id,
                "text": "FDAI human approval pending. Review through an authenticated channel.",
                "blocks": [
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": "*Human approval pending*\nA Slack message is not an approval.",
                        },
                    },
                    {
                        "type": "context",
                        "elements": [
                            {"type": "plain_text", "text": f"{key}: {value}"}
                            for key, value in context.items()
                        ],
                    },
                ],
            },
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        if len(payload) > _MAX_REQUEST_BYTES:
            raise HilChannelError("Slack approval message exceeds the size limit", approval_id="")
        return payload

    async def send(self, request: HilApprovalRequest) -> HilApprovalReceipt:
        payload = self.render_payload(request)
        fingerprint = hashlib.sha256(payload).hexdigest()
        dispatch_id = request.metadata.get("approval_dispatch_id", "initial")
        if not isinstance(dispatch_id, str) or not _OPAQUE.fullmatch(dispatch_id):
            raise HilChannelError("Slack approval dispatch identity is invalid", approval_id="")
        attempt_id = f"{request.approval_id}:{dispatch_id}"
        async with self._lock:
            prior = self._attempts.get(attempt_id)
            if prior is not None:
                if prior[0] != fingerprint:
                    raise HilChannelError(
                        "Slack approval replay has conflicting bindings",
                        approval_id=request.approval_id,
                    )
                if prior[1] is not None:
                    return prior[1]
                raise HilChannelError(
                    "Slack approval acknowledgement is unknown; reconcile before retry",
                    approval_id=request.approval_id,
                )
            if len(self._attempts) >= _MAX_ATTEMPTS:
                raise HilChannelError(
                    "Slack approval replay capacity reached; reconcile before retry",
                    approval_id=request.approval_id,
                )
            self._attempts[attempt_id] = (fingerprint, None)

        try:
            async with self._http.stream(
                "POST",
                self._config.api_url,
                content=payload,
                headers={
                    "Authorization": f"Bearer {self._config.bot_token}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                timeout=self._config.timeout_seconds,
                follow_redirects=False,
            ) as response:
                if response.status_code != 200:
                    raise HilChannelError(
                        "Slack approval was not accepted",
                        approval_id=request.approval_id,
                        status_code=response.status_code,
                    )
                body = bytearray()
                async for part in response.aiter_bytes():
                    if len(body) + len(part) > _MAX_RESPONSE_BYTES:
                        raise HilChannelError(
                            "Slack approval acknowledgement exceeds the size limit",
                            approval_id=request.approval_id,
                        )
                    body.extend(part)
        except httpx.HTTPError:
            raise HilChannelError(
                "Slack approval acknowledgement is unknown; reconcile before retry",
                approval_id=request.approval_id,
            ) from None
        try:
            acknowledgement = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise HilChannelError(
                "Slack approval acknowledgement is invalid",
                approval_id=request.approval_id,
            ) from exc
        if not isinstance(acknowledgement, dict) or acknowledgement.get("ok") is not True:
            raise HilChannelError(
                "Slack approval was not accepted",
                approval_id=request.approval_id,
            )
        message_id = acknowledgement.get("ts")
        if not isinstance(message_id, str) or not _MESSAGE_ID.fullmatch(message_id):
            raise HilChannelError(
                "Slack approval acknowledgement is missing the message id",
                approval_id=request.approval_id,
            )
        if acknowledgement.get("channel") != self._config.channel_id:
            raise HilChannelError(
                "Slack approval acknowledgement has the wrong destination",
                approval_id=request.approval_id,
            )
        receipt = HilApprovalReceipt(
            approval_id=request.approval_id,
            channel_ref=f"slack:{self._config.channel_id}/{message_id}",
            sent_at=datetime.now(tz=UTC),
        )
        async with self._lock:
            self._attempts[attempt_id] = (fingerprint, receipt)
        return receipt

    async def poll(self, receipt: HilApprovalReceipt) -> HilResponse:
        return HilResponse(approval_id=receipt.approval_id, decision=HilDecision.PENDING)
