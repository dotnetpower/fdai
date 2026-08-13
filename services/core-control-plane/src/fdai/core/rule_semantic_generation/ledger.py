"""Durable activation-result outbox for Rule semantic generations."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime
from typing import Any, Literal, Protocol

from fdai.rule_catalog.schema.rule_semantic_generation_events import (
    RuleGenerationActivationCommandEvent,
    RuleGenerationActivationResultEvent,
    RuleGenerationOutboxDeliveryState,
    RuleGenerationOutboxRecord,
)
from fdai.shared.providers.state_store import StateStore


class RuleGenerationLedgerConflictError(RuntimeError):
    """Raised when a transition is stale or owned by another claimant."""


class RuleGenerationLedgerCorruptionError(RuntimeError):
    """Raised when durable generation state fails exact contract validation."""


class RuleGenerationOutboxLedger(Protocol):
    """Persistence seam for atomic activation closure and publication."""

    async def result_for(
        self, command: RuleGenerationActivationCommandEvent
    ) -> RuleGenerationActivationResultEvent | None: ...

    async def commit_result(
        self, result: RuleGenerationActivationResultEvent
    ) -> RuleGenerationActivationResultEvent: ...

    async def claim_outbox(
        self,
        *,
        claimant_id: str,
        now: datetime,
        lease_until: datetime,
    ) -> RuleGenerationActivationResultEvent | None: ...

    async def complete_outbox(
        self,
        generation_request_id: str,
        idempotency_key: str,
        *,
        claimant_id: str,
        published_at: datetime,
    ) -> None: ...

    async def release_outbox(
        self,
        generation_request_id: str,
        idempotency_key: str,
        *,
        claimant_id: str,
        available_at: datetime,
        error: str,
    ) -> None: ...


class StateStoreRuleGenerationOutboxLedger:
    """StateStore aggregate with atomic terminal result and lease-fenced outbox."""

    _KEY_PREFIX = "rule-semantic-generation:activation:"
    _SCHEMA_VERSION = "1.0.0"
    _MAX_CAS_ATTEMPTS = 64
    _MAX_AGGREGATE_BYTES = 512 * 1024

    def __init__(self, *, store: StateStore) -> None:
        self._store = store

    async def result_for(
        self,
        command: RuleGenerationActivationCommandEvent,
    ) -> RuleGenerationActivationResultEvent | None:
        """Return an exact prior terminal result before replay can touch the index."""

        validated = RuleGenerationActivationCommandEvent.model_validate_json(
            command.model_dump_json()
        )
        request_id = _command_request_id(validated)
        existing = await self._store.read_state(f"{self._KEY_PREFIX}{request_id}")
        if existing is None:
            return None
        _revision, terminal, _delivery = self._parse_record(existing, request_id=request_id)
        if terminal.command.command_digest != validated.command_digest:
            raise RuleGenerationLedgerConflictError(
                "Rule generation request identity was reused with another activation command"
            )
        return terminal

    async def commit_result(
        self,
        result: RuleGenerationActivationResultEvent,
    ) -> RuleGenerationActivationResultEvent:
        """Atomically persist the first terminal result and pending outbox."""

        validated = RuleGenerationActivationResultEvent.model_validate_json(
            result.model_dump_json()
        )
        request_id = _generation_request_id(validated)
        key = f"{self._KEY_PREFIX}{request_id}"
        record = self._record(
            generation_request_id=request_id,
            revision=1,
            result=validated,
            delivery=RuleGenerationOutboxRecord(event=validated),
        )
        if await self._store.write_state_with_audit_if_absent(
            key,
            record,
            self._audit_entry(
                validated,
                action_kind="rule_generation.activation_closed",
                revision=1,
            ),
        ):
            return validated
        existing = await self._store.read_state(key)
        if existing is None:
            raise RuntimeError("Rule generation result write lost its durable state")
        _revision, terminal, _delivery = self._parse_record(existing, request_id=request_id)
        if terminal.command.command_digest != validated.command.command_digest:
            raise RuleGenerationLedgerConflictError(
                "Rule generation request identity was reused with another activation command"
            )
        return terminal

    async def claim_outbox(
        self,
        *,
        claimant_id: str,
        now: datetime,
        lease_until: datetime,
    ) -> RuleGenerationActivationResultEvent | None:
        """CAS-claim one due pending or lease-expired activation result."""

        _validate_lease(claimant_id=claimant_id, now=now, lease_until=lease_until)
        for _ in range(self._MAX_CAS_ATTEMPTS):
            candidates = await self._outbox_candidates()
            if not candidates:
                return None
            saw_claimable = False
            for aggregate in candidates:
                request_id = aggregate.get("generation_request_id")
                if not isinstance(request_id, str):
                    raise RuleGenerationLedgerCorruptionError(
                        "Durable Rule generation state failed validation"
                    )
                revision, result, delivery = self._parse_record(
                    aggregate,
                    request_id=request_id,
                )
                if not _is_claimable(delivery, now=now):
                    continue
                saw_claimable = True
                claimed = RuleGenerationOutboxRecord(
                    event=result,
                    state=RuleGenerationOutboxDeliveryState.CLAIMED,
                    attempts=delivery.attempts + 1,
                    available_at=delivery.available_at,
                    claimant_id=claimant_id,
                    claimed_at=now,
                    lease_until=lease_until,
                )
                next_revision = revision + 1
                if await self._store.compare_and_set_state_with_audit(
                    f"{self._KEY_PREFIX}{request_id}",
                    self._record(
                        generation_request_id=request_id,
                        revision=next_revision,
                        result=result,
                        delivery=claimed,
                    ),
                    expected_revision=revision,
                    audit_entry=self._audit_entry(
                        result,
                        action_kind="rule_generation.outbox_claimed",
                        revision=next_revision,
                    ),
                ):
                    return result
            if not saw_claimable:
                return None
        raise RuntimeError("Rule generation outbox claim conflicted repeatedly")

    async def complete_outbox(
        self,
        generation_request_id: str,
        idempotency_key: str,
        *,
        claimant_id: str,
        published_at: datetime,
    ) -> None:
        """Persist broker acknowledgement for the exact claimed result."""

        await self._update_delivery(
            generation_request_id=generation_request_id,
            idempotency_key=idempotency_key,
            claimant_id=claimant_id,
            action="complete",
            transition_at=published_at,
            error=None,
        )

    async def release_outbox(
        self,
        generation_request_id: str,
        idempotency_key: str,
        *,
        claimant_id: str,
        available_at: datetime,
        error: str,
    ) -> None:
        """Release one failed publication for deterministic retry."""

        await self._update_delivery(
            generation_request_id=generation_request_id,
            idempotency_key=idempotency_key,
            claimant_id=claimant_id,
            action="release",
            transition_at=available_at,
            error=error,
        )

    async def _outbox_candidates(self) -> tuple[Mapping[str, Any], ...]:
        candidates: list[Mapping[str, Any]] = []
        for state in (
            RuleGenerationOutboxDeliveryState.PENDING,
            RuleGenerationOutboxDeliveryState.CLAIMED,
        ):
            offset = 0
            while True:
                page, total = await self._store.read_state_page(
                    self._KEY_PREFIX,
                    limit=100,
                    offset=offset,
                    field="outbox_state",
                    value=state.value,
                )
                candidates.extend(page)
                offset += len(page)
                if not page or offset >= total:
                    break
        return tuple(candidates)

    async def _update_delivery(
        self,
        *,
        generation_request_id: str,
        idempotency_key: str,
        claimant_id: str,
        action: Literal["complete", "release"],
        transition_at: datetime,
        error: str | None,
    ) -> None:
        _require_aware("transition_at", transition_at)
        key = f"{self._KEY_PREFIX}{generation_request_id}"
        for _ in range(self._MAX_CAS_ATTEMPTS):
            aggregate = await self._store.read_state(key)
            if aggregate is None:
                raise RuleGenerationLedgerConflictError(
                    "Rule generation outbox aggregate does not exist"
                )
            revision, result, delivery = self._parse_record(
                aggregate,
                request_id=generation_request_id,
            )
            if delivery.event.idempotency_key != idempotency_key:
                raise RuleGenerationLedgerConflictError(
                    "Rule generation outbox event does not exist"
                )
            if delivery.state is RuleGenerationOutboxDeliveryState.PUBLISHED:
                return
            if (
                delivery.state is not RuleGenerationOutboxDeliveryState.CLAIMED
                or delivery.claimant_id != claimant_id
            ):
                raise RuleGenerationLedgerConflictError(
                    "Rule generation outbox publication is not owned by the claimant"
                )
            if (
                delivery.claimed_at is None
                or delivery.lease_until is None
                or transition_at < delivery.claimed_at
                or transition_at > delivery.lease_until
            ):
                raise RuleGenerationLedgerConflictError(
                    "Rule generation outbox claimant lease is not current"
                )
            updated = (
                RuleGenerationOutboxRecord(
                    event=result,
                    state=RuleGenerationOutboxDeliveryState.PUBLISHED,
                    attempts=delivery.attempts,
                    available_at=delivery.available_at,
                    published_at=transition_at,
                )
                if action == "complete"
                else RuleGenerationOutboxRecord(
                    event=result,
                    attempts=delivery.attempts,
                    available_at=transition_at,
                    last_error=error,
                )
            )
            next_revision = revision + 1
            action_kind = (
                "rule_generation.outbox_published"
                if action == "complete"
                else "rule_generation.outbox_released"
            )
            if await self._store.compare_and_set_state_with_audit(
                key,
                self._record(
                    generation_request_id=generation_request_id,
                    revision=next_revision,
                    result=result,
                    delivery=updated,
                ),
                expected_revision=revision,
                audit_entry=self._audit_entry(
                    result,
                    action_kind=action_kind,
                    revision=next_revision,
                ),
            ):
                return
        raise RuntimeError("Rule generation outbox update conflicted repeatedly")

    def _record(
        self,
        *,
        generation_request_id: str,
        revision: int,
        result: RuleGenerationActivationResultEvent,
        delivery: RuleGenerationOutboxRecord,
    ) -> dict[str, Any]:
        record = {
            "schema_version": self._SCHEMA_VERSION,
            "generation_request_id": generation_request_id,
            "revision": revision,
            "terminal_result": result.model_dump(mode="json"),
            "outbox": {delivery.event.idempotency_key: delivery.model_dump(mode="json")},
            "outbox_state": delivery.state.value,
        }
        encoded = json.dumps(
            record,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        if len(encoded) > self._MAX_AGGREGATE_BYTES:
            raise ValueError("Durable Rule generation aggregate exceeds its byte limit")
        return record

    def _parse_record(
        self,
        record: Mapping[str, Any],
        *,
        request_id: str,
    ) -> tuple[int, RuleGenerationActivationResultEvent, RuleGenerationOutboxRecord]:
        try:
            if (
                record.get("schema_version") != self._SCHEMA_VERSION
                or record.get("generation_request_id") != request_id
                or not isinstance(record.get("revision"), int)
                or isinstance(record.get("revision"), bool)
                or int(record["revision"]) < 1
                or not isinstance(record.get("outbox"), Mapping)
            ):
                raise ValueError("invalid Rule generation aggregate metadata")
            result = RuleGenerationActivationResultEvent.model_validate(
                record.get("terminal_result")
            )
            outbox = {
                str(key): RuleGenerationOutboxRecord.model_validate(payload)
                for key, payload in record["outbox"].items()
            }
            delivery = outbox.get(result.idempotency_key)
            if (
                _generation_request_id(result) != request_id
                or len(outbox) != 1
                or delivery is None
                or delivery.event != result
                or record.get("outbox_state") != delivery.state.value
            ):
                raise ValueError("Rule generation terminal result and outbox are not bound")
            return int(record["revision"]), result, delivery
        except (TypeError, ValueError) as exc:
            raise RuleGenerationLedgerCorruptionError(
                "Durable Rule generation state failed validation"
            ) from exc

    @staticmethod
    def _audit_entry(
        result: RuleGenerationActivationResultEvent,
        *,
        action_kind: str,
        revision: int,
    ) -> dict[str, Any]:
        return {
            "actor": "fdai.core.rule_semantic_generation",
            "action_kind": action_kind,
            "generation_request_id": _generation_request_id(result),
            "command_digest": result.command.command_digest,
            "result_digest": result.result_digest,
            "outbox_idempotency_key": result.idempotency_key,
            "revision": revision,
        }


def _generation_request_id(result: RuleGenerationActivationResultEvent) -> str:
    return _command_request_id(result.command)


def _command_request_id(command: RuleGenerationActivationCommandEvent) -> str:
    return command.validation_result.build_result.request.generation_request_id


def _validate_lease(*, claimant_id: str, now: datetime, lease_until: datetime) -> None:
    if not claimant_id:
        raise ValueError("Rule generation outbox claimant id MUST be non-empty")
    _require_aware("now", now)
    _require_aware("lease_until", lease_until)
    if lease_until <= now:
        raise ValueError("Rule generation outbox lease MUST end after claim time")


def _require_aware(name: str, value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"Rule generation outbox {name} MUST be timezone-aware")


def _is_claimable(record: RuleGenerationOutboxRecord, *, now: datetime) -> bool:
    if record.state is RuleGenerationOutboxDeliveryState.PUBLISHED:
        return False
    if record.state is RuleGenerationOutboxDeliveryState.CLAIMED:
        return record.lease_until is not None and record.lease_until <= now
    return record.available_at is None or record.available_at <= now


__all__ = [
    "RuleGenerationLedgerConflictError",
    "RuleGenerationLedgerCorruptionError",
    "RuleGenerationOutboxLedger",
    "StateStoreRuleGenerationOutboxLedger",
]
