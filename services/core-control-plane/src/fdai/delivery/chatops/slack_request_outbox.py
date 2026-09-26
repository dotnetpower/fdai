"""Durable, at-most-once-attempt Slack approval-request delivery."""

from __future__ import annotations

import asyncio
import hashlib
import re
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from fdai.core.hil_resume.integrity import parked_action_integrity_matches
from fdai.core.hil_resume.load_control import approval_request_from_park
from fdai.delivery.chatops.slack_adapter import SlackHilAdapter
from fdai.shared.providers.hil_channel import (
    HilApprovalReceipt,
    HilApprovalRequest,
    HilChannel,
    HilChannelError,
    HilResponse,
)
from fdai.shared.providers.state_store import StateStore

_PREFIX = "hil-slack-request:"
_PARK_PREFIX = "hil_park:"
_CLAIM_SECONDS = 30
_PAGE_SIZE = 100
_DISPATCH_ID = re.compile(r"[A-Za-z0-9._:-]{1,200}\Z")
_MESSAGE_ID = re.compile(r"[0-9]{1,16}\.[0-9]{1,12}\Z")


class DurableSlackApprovalChannel(HilChannel):
    """Persist intent before I/O; never retry an attempted but unacknowledged post.

    An expired in-flight claim is unknown, even if the process stopped before
    issuing HTTP. Slack does not offer an authoritative idempotent-post receipt
    on which an automatic retry could safely depend.
    """

    def __init__(
        self,
        *,
        adapter: SlackHilAdapter,
        store: StateStore,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._adapter = adapter
        self._store = store
        self._clock = clock or (lambda: datetime.now(UTC))

    async def reserve(self, request: HilApprovalRequest) -> None:
        """Create exactly one immutable record before any provider operation."""
        dispatch_id = self._dispatch_id(request)
        payload_digest = hashlib.sha256(self._adapter.render_payload(request)).hexdigest()
        key = self._key(request.approval_id, dispatch_id)
        await self._check_park(request)
        record: dict[str, Any] = {
            "status": "queued",
            "revision": 0,
            "approval_id": request.approval_id,
            "dispatch_id": dispatch_id,
            "correlation_id": request.correlation_id,
            "action_id": request.action_id,
            "idempotency_key": request.metadata["idempotency_key"],
            "action_hash": request.action_hash,
            "channel_id": self._adapter.channel_id,
            "payload_digest": payload_digest,
        }
        created = await self._store.write_state_with_audit_if_absent(
            key, record, self._audit(record, "queued")
        )
        if not created:
            previous = await self._store.read_state(key)
            if previous is None or any(
                previous.get(name) != value
                for name, value in record.items()
                if name not in {"status", "revision"}
            ):
                raise HilChannelError(
                    "Slack approval dispatch identity conflicts with its durable record",
                    approval_id=request.approval_id,
                )

    async def send(self, request: HilApprovalRequest) -> HilApprovalReceipt:
        await self.reserve(request)
        key = self._key(request.approval_id, self._dispatch_id(request))
        record = await self._store.read_state(key)
        if record is None:
            raise HilChannelError("Slack approval outbox record is unavailable", approval_id="")
        if record.get("status") == "accepted":
            return self._receipt(record)
        if record.get("status") != "queued":
            raise HilChannelError(
                "Slack approval send is held pending authoritative reconciliation",
                approval_id=request.approval_id,
            )
        await self._check_park(request)
        claimed = await self._transition(
            key,
            record,
            "inflight",
            claim_until=(self._now() + timedelta(seconds=_CLAIM_SECONDS)).isoformat(),
        )
        try:
            await self._check_park(request)
        except HilChannelError:
            await self._transition(key, claimed, "held")
            raise
        if (
            hashlib.sha256(self._adapter.render_payload(request)).hexdigest()
            != claimed["payload_digest"]
        ):
            await self._transition(key, claimed, "held")
            raise HilChannelError(
                "Slack approval payload changed after durable admission",
                approval_id=request.approval_id,
            )
        try:
            receipt = await self._adapter.send(request)
        except asyncio.CancelledError:
            await self._transition(key, claimed, "unknown")
            raise
        except Exception as exc:  # noqa: BLE001 - every post failure is ambiguous after claim.
            await self._transition(key, claimed, "unknown")
            raise HilChannelError(
                "Slack approval acknowledgement is unknown; do not repost",
                approval_id=request.approval_id,
            ) from exc
        prefix = f"slack:{self._adapter.channel_id}/"
        if (
            receipt.approval_id != request.approval_id
            or not receipt.channel_ref.startswith(prefix)
            or _MESSAGE_ID.fullmatch(receipt.channel_ref[len(prefix) :]) is None
            or receipt.sent_at.tzinfo is None
            or receipt.sent_at.utcoffset() is None
        ):
            await self._transition(key, claimed, "unknown")
            raise HilChannelError(
                "Slack approval acknowledgement does not bind the accepted message",
                approval_id=request.approval_id,
            )
        await self._transition(
            key,
            claimed,
            "accepted",
            channel_ref=receipt.channel_ref,
            sent_at=receipt.sent_at.isoformat(),
        )
        return receipt

    async def poll(self, receipt: HilApprovalReceipt) -> HilResponse:
        return await self._adapter.poll(receipt)

    async def reconcile_once(self) -> bool:
        """Hold stale attempts; drain at most one never-attempted queued request."""
        inflight, _ = await self._store.read_state_page(
            _PREFIX, limit=_PAGE_SIZE, field="status", value="inflight"
        )
        for record in inflight:
            if self._claim_expired(record):
                await self._transition(self._record_key(record), record, "unknown")
                return True
        queued, _ = await self._store.read_state_page(
            _PREFIX, limit=_PAGE_SIZE, field="status", value="queued"
        )
        for record in queued:
            try:
                approval_id = str(record["approval_id"])
                parked = await self._store.read_state(f"{_PARK_PREFIX}{approval_id}")
                if parked is None:
                    await self._transition(self._record_key(record), record, "held")
                    return True
                dispatch_id = str(record["dispatch_id"])
                request = approval_request_from_park(
                    parked,
                    metadata=(
                        {"approval_dispatch_id": dispatch_id} if dispatch_id != "initial" else None
                    ),
                )
                await self.send(request)
            except HilChannelError:
                key = self._record_key(record)
                current = await self._store.read_state(key)
                if current is not None and current.get("status") == "queued":
                    try:
                        await self._transition(key, current, "held")
                    except HilChannelError:
                        pass  # Another worker won the claim; it owns the outcome.
            return True
        return False

    async def run(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            progressed = await self.reconcile_once()
            if not progressed:
                try:
                    await asyncio.wait_for(stop.wait(), timeout=5)
                except TimeoutError:
                    continue

    async def _check_park(self, request: HilApprovalRequest) -> None:
        parked = await self._store.read_state(f"{_PARK_PREFIX}{request.approval_id}")
        if parked is None or parked.get("status") != "pending":
            raise HilChannelError(
                "Slack approval park is not pending", approval_id=request.approval_id
            )
        action = parked.get("action")
        context = parked.get("approval_context")
        if not isinstance(action, Mapping) or not isinstance(context, Mapping):
            raise HilChannelError(
                "Slack approval park is incomplete", approval_id=request.approval_id
            )
        try:
            expires_at = datetime.fromisoformat(str(context["expires_at"]).replace("Z", "+00:00"))
        except (KeyError, ValueError) as exc:
            raise HilChannelError("Slack approval expiry is invalid", approval_id="") from exc
        if (
            expires_at.tzinfo is None
            or expires_at <= self._now()
            or not parked_action_integrity_matches(parked)
            or any(
                parked.get(name) != value
                for name, value in (
                    ("approval_id", request.approval_id),
                    ("correlation_id", request.correlation_id),
                    ("idempotency_key", request.metadata.get("idempotency_key")),
                    ("request_fingerprint", request.action_hash),
                )
            )
            or str(action.get("action_id")) != request.action_id
        ):
            raise HilChannelError(
                "Slack approval park is expired or its action binding changed",
                approval_id=request.approval_id,
            )

    async def _transition(
        self, key: str, record: Mapping[str, Any], status: str, **fields: object
    ) -> dict[str, Any]:
        revision = record.get("revision")
        if not isinstance(revision, int):
            raise HilChannelError("Slack approval outbox revision is invalid", approval_id="")
        updated = {**record, **fields, "status": status, "revision": revision + 1}
        if not await self._store.compare_and_set_state_with_audit(
            key, updated, expected_revision=revision, audit_entry=self._audit(updated, status)
        ):
            raise HilChannelError("Slack approval outbox claim changed", approval_id="")
        return updated

    def _audit(self, record: Mapping[str, Any], status: str) -> dict[str, Any]:
        digest = hashlib.sha256(
            f"{record['approval_id']}:{record['dispatch_id']}:{status}".encode()
        ).hexdigest()
        return {
            "actor": "fdai.delivery.chatops.slack_request_outbox",
            "action_kind": f"hil.slack.outbound.{status}",
            "mode": "shadow",
            "idempotency_key": f"hil-slack-outbound:{digest}",
            "approval_id": record["approval_id"],
            "correlation_id": record["correlation_id"],
            "payload_digest": record["payload_digest"],
            "recorded_at": self._now().isoformat(),
        }

    def _claim_expired(self, record: Mapping[str, Any]) -> bool:
        raw = record.get("claim_until")
        if not isinstance(raw, str):
            return True
        try:
            deadline = datetime.fromisoformat(raw)
        except ValueError:
            return True
        return deadline.tzinfo is None or deadline <= self._now()

    def _now(self) -> datetime:
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise HilChannelError("Slack approval outbox clock is invalid", approval_id="")
        return now.astimezone(UTC)

    @staticmethod
    def _dispatch_id(request: HilApprovalRequest) -> str:
        value = request.metadata.get("approval_dispatch_id", "initial")
        if not isinstance(value, str) or not _DISPATCH_ID.fullmatch(value):
            raise HilChannelError("Slack approval dispatch identity is invalid", approval_id="")
        return value

    @staticmethod
    def _key(approval_id: str, dispatch_id: str) -> str:
        digest = hashlib.sha256(f"{approval_id}\0{dispatch_id}".encode()).hexdigest()
        return f"{_PREFIX}{digest}"

    @classmethod
    def _record_key(cls, record: Mapping[str, Any]) -> str:
        return cls._key(str(record["approval_id"]), str(record["dispatch_id"]))

    @staticmethod
    def _receipt(record: Mapping[str, Any]) -> HilApprovalReceipt:
        try:
            sent_at = datetime.fromisoformat(str(record["sent_at"]))
            channel_ref = str(record["channel_ref"])
        except (KeyError, ValueError) as exc:
            raise HilChannelError("Slack approval receipt is incomplete", approval_id="") from exc
        prefix = f"slack:{record['channel_id']}/"
        if (
            sent_at.tzinfo is None
            or not channel_ref.startswith(prefix)
            or _MESSAGE_ID.fullmatch(channel_ref[len(prefix) :]) is None
        ):
            raise HilChannelError("Slack approval receipt is invalid", approval_id="")
        return HilApprovalReceipt(
            approval_id=str(record["approval_id"]), channel_ref=channel_ref, sent_at=sent_at
        )
