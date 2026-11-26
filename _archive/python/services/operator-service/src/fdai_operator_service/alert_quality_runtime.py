"""Signed request/result bridge; private identities resolve only from durable Operator state."""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import AsyncIterator, Callable, Mapping
from datetime import UTC, datetime
from typing import Protocol
from uuid import NAMESPACE_URL, uuid5

from fdai_service_contracts.alert_noise_wire import (
    ALERT_NOISE_RESULT_TOPIC,
    SignedAlertCommand,
    SignedAlertReadiness,
    SignedAlertResult,
    sign_alert_record,
    verify_alert_record,
)

from fdai_operator_service.alert_quality_codecs import (
    COMMAND_PRODUCER_V1,
    READINESS_CONSUMER_V1,
    RESULT_CONSUMER_V1,
)
from fdai_operator_service.alert_quality_command import command_from_record as command_from_record
from fdai_operator_service.alert_quality_history import StateKvAlertQualityRequestSource
from fdai_operator_service.alert_quality_store import (
    AlertQualityStaleError,
    StateKvAlertQualityStore,
)
from fdai_operator_service.postgres_family_store import PostgresFamilyStore


class AlertQualityTransport(Protocol):
    """Existing versioned transport; source authenticity is additionally signed."""

    async def publish(self, topic: str, key: str, payload: Mapping[str, object]) -> object: ...

    def subscribe(self, topic: str, group_id: str) -> AsyncIterator[Mapping[str, object]]: ...


class AlertQualityBridge:
    """Own bounded outbox work and result consumption for the production Operator lifecycle."""

    def __init__(
        self,
        *,
        store: PostgresFamilyStore,
        transport: AlertQualityTransport,
        event_topic: str,
        transport_key: bytes,
        scopes: frozenset[str],
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if not event_topic or len(transport_key) < 32:
            raise ValueError("alert quality bridge configuration is incomplete")
        self.store, self.transport, self.topic = store, transport, event_topic
        self.key, self.scopes, self.clock = transport_key, scopes, clock
        self.projections = StateKvAlertQualityStore(store, clock=clock)
        self.requests = StateKvAlertQualityRequestSource(
            store, transport_key=transport_key, clock=clock
        )
        self._tasks: tuple[asyncio.Task[None], ...] = ()
        self._ready: SignedAlertReadiness | None = None

    async def producer_ready(self) -> bool:
        """Require live workers and a fresh signed Core scope announcement."""
        if len(self._tasks) != 2 or any(task.done() for task in self._tasks) or self._ready is None:
            return False
        value = self._ready.readiness
        return value.generated_at <= self.clock() < value.valid_until and self.scopes.issubset(
            value.scope_refs
        )

    def workers_ready(self) -> bool:
        """Report worker liveness only, not source or execution readiness."""
        return len(self._tasks) == 2 and all(not task.done() for task in self._tasks)

    async def start(self) -> None:
        """Start exactly one owned drainer and one projection consumer."""
        if not self._tasks:
            self._tasks = (
                asyncio.create_task(self._drain(), name="alert-quality-outbox"),
                asyncio.create_task(self._consume(), name="alert-quality-projection"),
            )

    async def aclose(self) -> None:
        """Cancel and drain all owned tasks; availability expires with the process."""
        tasks, self._tasks = self._tasks, ()
        self._ready = None
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def drain_once(self) -> bool:
        """Publish one signed request, bounded by its persisted deadline and attempt count."""
        claim = await self.store.claim_alert_quality_proposal()
        if claim is None:
            return False
        key, claim_id, record = claim
        try:
            command = command_from_record(record)
            if (
                not command.requested_at <= self.clock() < command.expires_at
                or int(record.get("attempt", 1)) > 5
            ):
                raise ValueError("alert request expired")
            signed = SignedAlertCommand(
                command=command, signature=sign_alert_record(command, self.key)
            )
            raw = {
                "schema_version": "1.0.0",
                "event_id": str(uuid5(NAMESPACE_URL, command.request_ref)),
                "idempotency_key": command.request_ref,
                "correlation_id": command.request_ref,
                "source": "operator-alert-noise",
                "event_type": command.operation,
                "resource_ref": command.scope_ref,
                "payload": {
                    "alert_noise": COMMAND_PRODUCER_V1.encode_mapping(
                        signed.model_dump(mode="json")
                    )
                },
                "detected_at": command.requested_at.isoformat(),
                "ingested_at": command.requested_at.isoformat(),
                "incident_correlation": "none",
                "mode": "shadow",
            }
            async with asyncio.timeout(15):
                await self.transport.publish(self.topic, command.request_ref, raw)
        except ValueError:
            await self.store.mark_proposal_rejected(
                key=key, claim_id=claim_id, reason_code="invalid_alert_request"
            )
            return False
        except Exception:  # noqa: BLE001 - deadline-bound transport retry, no provider body logging
            await self.store.release_proposal_claim(key=key, claim_id=claim_id)
            return False
        return await self.store.mark_proposal_published(key=key, claim_id=claim_id)

    async def accept_result(self, raw: Mapping[str, object]) -> None:
        """Reserve the exact authenticated result before projecting any evidence.

        A conflicting terminal cannot win during projection I/O. Interrupted projection
        is completed by replaying only the retained result; reservation is not completion.
        """
        if "readiness" in raw:
            signed_ready = SignedAlertReadiness.model_validate(
                READINESS_CONSUMER_V1.decode_mapping(raw)
            )
            verify_alert_record(signed_ready.readiness, signed_ready.signature, self.key)
            value = signed_ready.readiness
            if not value.generated_at <= self.clock() < value.valid_until:
                return
            if self._ready is None or value.generated_at > self._ready.readiness.generated_at:
                self._ready = signed_ready
            return
        signed = SignedAlertResult.model_validate(RESULT_CONSUMER_V1.decode_mapping(raw))
        verify_alert_record(signed.result, signed.signature, self.key)
        result = signed.result
        if result.recorded_at > self.clock():
            raise ValueError("alert result is future recorded")
        record_key = (
            "operator-proposal:operations:"
            + hashlib.sha256(result.command.request_ref.encode()).hexdigest()
        )
        record = await self.store.read_state(record_key)
        if record is None or command_from_record(record) != result.command:
            raise ValueError("alert result has no matching Operator acceptance")
        result_key = "operator-alert-quality-result:" + result.command.request_ref
        result_value = signed.model_dump(mode="json")
        created = await self.store.create_state(result_key, result_value)
        if not created and await self.store.read_state(result_key) != result_value:
            raise ValueError("alert result conflicts with an already recorded terminal result")
        subject = str(record["principal_id"])
        if result.assessment is not None:
            try:
                await self.projections.persist_assessment(
                    principal_id=subject,
                    scope_ref=result.command.scope_ref,
                    assessment=result.assessment,
                )
                if result.plan is not None:
                    await self.projections.persist_plan(
                        principal_id=subject, scope_ref=result.command.scope_ref, plan=result.plan
                    )
            except AlertQualityStaleError:
                # Retained original request closure remains factual;
                # no newer projection is overwritten.
                pass

    async def _drain(self) -> None:
        while True:
            published = await self.drain_once()
            await asyncio.sleep(0 if published else 1)

    async def _consume(self) -> None:
        async for raw in self.transport.subscribe(
            ALERT_NOISE_RESULT_TOPIC, "operator-alert-quality"
        ):
            try:
                async with asyncio.timeout(15):
                    await self.accept_result(raw)
            except ValueError:
                await self.transport.publish(
                    ALERT_NOISE_RESULT_TOPIC + ".dlq",
                    "alert-quality-rejected",
                    {"reason": "invalid_alert_quality_result"},
                )
