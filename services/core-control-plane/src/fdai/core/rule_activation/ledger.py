"""Durable immutable generations and one audited Rule activation pointer."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Any

from fdai_service_contracts.rule_activation import (
    RuleActivationCommand,
    RuleActivationGeneration,
    RuleActivationResult,
    RuleActivationSource,
    RuleActivationStatus,
)

from fdai.shared.providers.state_store import StateStore


class RuleActivationLedgerConflictError(RuntimeError):
    """Raised when one durable identity is reused with different content."""


class RuleActivationLedgerCorruptionError(RuntimeError):
    """Raised when durable activation state fails exact contract validation."""


class StateStoreRuleActivationLedger:
    """Apply complete generations through one CAS pointer.

    Immutable generation rows have no authority. Only the current pointer selects T0 membership.
    An orphaned generation is inert, and redelivery repairs a missing terminal after pointer CAS.
    """

    _GENERATION_PREFIX = "rule-activation:generation:"
    _RESULT_PREFIX = "rule-activation:result:"
    _IDEMPOTENCY_PREFIX = "rule-activation:idempotency:"
    _CURRENT_KEY = "rule-activation:current"
    _SCHEMA_VERSION = "1.0.0"

    def __init__(self, *, store: StateStore) -> None:
        self._store = store

    async def current_generation(self) -> RuleActivationGeneration | None:
        """Return the exact generation selected by the authoritative pointer."""

        pointer = await self._read_pointer()
        if pointer is None:
            return None
        generation = await self._read_generation(str(pointer["generation_id"]))
        if generation.generation_digest != pointer["generation_digest"]:
            raise RuleActivationLedgerCorruptionError(
                "Rule activation pointer and generation digest do not match"
            )
        return generation

    async def result_for(self, command: RuleActivationCommand) -> RuleActivationResult | None:
        """Return an exact terminal result without replaying the pointer effect."""

        validated = _validate_command(command)
        raw = await self._store.read_state(self._result_key(validated.proposal.request_id))
        if raw is None:
            return None
        result = _parse_result(raw)
        if result.command_digest != validated.command_digest:
            raise RuleActivationLedgerConflictError(
                "Rule activation request identity was reused with another command"
            )
        return result

    async def result_for_request(self, request_id: str) -> RuleActivationResult | None:
        """Return the retained terminal for one validated request identity."""

        raw = await self._store.read_state(self._result_key(request_id))
        return _parse_result(raw) if raw is not None else None

    async def apply(self, command: RuleActivationCommand) -> RuleActivationResult:
        """Apply or replay one approved command and verify the current pointer."""

        validated = _validate_command(command)
        existing = await self.result_for(validated)
        if existing is not None:
            return existing
        await self._reserve_idempotency(validated)

        pointer = await self._read_pointer()
        current = await self.current_generation()
        target = validated.generation
        if current is not None and current.generation_digest == target.generation_digest:
            return await self._commit_result(
                _result(
                    validated,
                    status=RuleActivationStatus.ALREADY_APPLIED,
                    previous_digest=_optional_digest(pointer, "previous_generation_digest"),
                    resulting_digest=target.generation_digest,
                    readback_verified=True,
                )
            )

        observed = current.generation_digest if current is not None else None
        if observed != validated.proposal.expected_generation_digest:
            return await self._commit_result(
                _result(
                    validated,
                    status=RuleActivationStatus.CONFLICT,
                    previous_digest=observed,
                    resulting_digest=None,
                    readback_verified=False,
                    failure_reason="active_generation_identity_mismatch",
                )
            )
        if not _transition_matches(current=current, target=target, command=validated):
            return await self._commit_result(
                _result(
                    validated,
                    status=RuleActivationStatus.REJECTED,
                    previous_digest=observed,
                    resulting_digest=None,
                    readback_verified=False,
                    failure_reason="candidate_generation_does_not_match_requested_changes",
                )
            )

        await self._store_generation(target)
        changed = await self._change_pointer(
            command=validated,
            target=target,
            pointer=pointer,
            previous_digest=observed,
        )
        readback = await self.current_generation()
        if readback is not None and readback.generation_digest == target.generation_digest:
            status = (
                RuleActivationStatus.APPLIED if changed else RuleActivationStatus.ALREADY_APPLIED
            )
            return await self._commit_result(
                _result(
                    validated,
                    status=status,
                    previous_digest=observed,
                    resulting_digest=target.generation_digest,
                    readback_verified=True,
                )
            )

        status = RuleActivationStatus.CONFLICT if not changed else RuleActivationStatus.FAILED
        reason = (
            "active_generation_identity_mismatch" if not changed else "activation_readback_failed"
        )
        return await self._commit_result(
            _result(
                validated,
                status=status,
                previous_digest=observed,
                resulting_digest=None,
                readback_verified=False,
                failure_reason=reason,
            )
        )

    async def _reserve_idempotency(self, command: RuleActivationCommand) -> None:
        key_digest = hashlib.sha256(command.proposal.idempotency_key.encode()).hexdigest()
        key = f"{self._IDEMPOTENCY_PREFIX}{key_digest}"
        value = {
            "schema_version": self._SCHEMA_VERSION,
            "kind": "rule_activation.idempotency",
            "idempotency_key_digest": key_digest,
            "request_id": command.proposal.request_id,
            "command_digest": command.command_digest,
        }
        if await self._store.write_state_if_absent(key, value):
            return
        if await self._store.read_state(key) != value:
            raise RuleActivationLedgerConflictError(
                "Rule activation idempotency key was reused with another command"
            )

    async def _store_generation(self, generation: RuleActivationGeneration) -> None:
        value = {
            "schema_version": self._SCHEMA_VERSION,
            "kind": "rule_activation.generation",
            "generation": generation.model_dump(mode="json"),
        }
        key = f"{self._GENERATION_PREFIX}{generation.generation_id}"
        if await self._store.write_state_if_absent(key, value):
            return
        if await self._store.read_state(key) != value:
            raise RuleActivationLedgerConflictError(
                "Rule activation generation identity was reused with different content"
            )

    async def _change_pointer(
        self,
        *,
        command: RuleActivationCommand,
        target: RuleActivationGeneration,
        pointer: Mapping[str, Any] | None,
        previous_digest: str | None,
    ) -> bool:
        revision = _pointer_revision(pointer)
        value = {
            "schema_version": self._SCHEMA_VERSION,
            "kind": "rule_activation.current",
            "revision": revision + 1,
            "generation_id": target.generation_id,
            "generation_digest": target.generation_digest,
            "previous_generation_digest": previous_digest,
            "profile_id": target.profile_id,
            "profile_version": target.profile_version,
            "request_id": command.proposal.request_id,
            "command_digest": command.command_digest,
            "source": command.proposal.source.value,
            "source_ref": command.proposal.source_ref,
            "requested_by": command.proposal.requested_by,
            "approver_ids": list(command.approval.approver_ids),
            "activated_at": command.commanded_at.isoformat(),
        }
        audit = _pointer_audit(command, previous_digest, target.generation_digest, revision + 1)
        if pointer is None:
            return await self._store.write_state_with_audit_if_absent(
                self._CURRENT_KEY, value, audit
            )
        return await self._store.compare_and_set_state_with_audit(
            self._CURRENT_KEY,
            value,
            expected_revision=revision,
            audit_entry=audit,
        )

    async def _commit_result(self, result: RuleActivationResult) -> RuleActivationResult:
        value = {
            "schema_version": self._SCHEMA_VERSION,
            "kind": "rule_activation.result",
            "result": result.model_dump(mode="json"),
        }
        key = self._result_key(result.request_id)
        audit = {
            "actor": result.applied_by,
            "producer_principal": "Saga",
            "action_kind": "rule_activation.closed",
            "mode": "shadow",
            "correlation_id": result.request_id,
            "idempotency_key": result.command_digest,
            "status": result.status.value,
            "previous_generation_digest": result.previous_generation_digest,
            "resulting_generation_digest": result.resulting_generation_digest,
            "readback_verified": result.readback_verified,
            "failure_reason": result.failure_reason,
            "recorded_at": result.completed_at.isoformat(),
        }
        if await self._store.write_state_with_audit_if_absent(key, value, audit):
            return result
        existing = await self._store.read_state(key)
        if existing is None:
            raise RuntimeError("Rule activation result write lost its durable state")
        terminal = _parse_result(existing)
        if terminal.command_digest != result.command_digest:
            raise RuleActivationLedgerConflictError(
                "Rule activation request identity was reused with another result"
            )
        return terminal

    async def _read_pointer(self) -> Mapping[str, Any] | None:
        pointer = await self._store.read_state(self._CURRENT_KEY)
        if pointer is None:
            return None
        try:
            if (
                pointer.get("schema_version") != self._SCHEMA_VERSION
                or pointer.get("kind") != "rule_activation.current"
                or not isinstance(pointer.get("generation_id"), str)
                or not isinstance(pointer.get("generation_digest"), str)
            ):
                raise ValueError
            _pointer_revision(pointer)
        except (TypeError, ValueError) as exc:
            raise RuleActivationLedgerCorruptionError(
                "Durable Rule activation pointer failed validation"
            ) from exc
        return pointer

    async def _read_generation(self, generation_id: str) -> RuleActivationGeneration:
        raw = await self._store.read_state(f"{self._GENERATION_PREFIX}{generation_id}")
        try:
            if (
                raw is None
                or raw.get("schema_version") != self._SCHEMA_VERSION
                or raw.get("kind") != "rule_activation.generation"
            ):
                raise ValueError
            return RuleActivationGeneration.model_validate(raw.get("generation"))
        except (TypeError, ValueError) as exc:
            raise RuleActivationLedgerCorruptionError(
                "Durable Rule activation generation failed validation"
            ) from exc

    @staticmethod
    def _result_key(request_id: str) -> str:
        return f"{StateStoreRuleActivationLedger._RESULT_PREFIX}{request_id}"


def _transition_matches(
    *,
    current: RuleActivationGeneration | None,
    target: RuleActivationGeneration,
    command: RuleActivationCommand,
) -> bool:
    if current is None:
        return command.proposal.source in {
            RuleActivationSource.INSTALLATION,
            RuleActivationSource.OFFLINE_PACKAGE,
        }
    if (
        target.profile_id != current.profile_id
        or target.profile_version != current.profile_version
        or target.catalog_digest != current.catalog_digest
    ):
        return False
    current_by_id = {member.rule_id: member for member in current.members}
    target_by_id = {member.rule_id: member for member in target.members}
    expected_ids = set(current_by_id)
    for change in command.proposal.changes:
        if change.enabled:
            if change.rule_id not in target_by_id:
                return False
            expected_ids.add(change.rule_id)
        else:
            expected_ids.discard(change.rule_id)
    if set(target_by_id) != expected_ids:
        return False
    return all(
        current_by_id[rule_id] == target_by_id[rule_id]
        for rule_id in set(current_by_id) & set(target_by_id)
    )


def _validate_command(command: RuleActivationCommand) -> RuleActivationCommand:
    return RuleActivationCommand.model_validate_json(command.model_dump_json())


def _parse_result(raw: Mapping[str, Any]) -> RuleActivationResult:
    try:
        if raw.get("schema_version") != "1.0.0" or raw.get("kind") != "rule_activation.result":
            raise ValueError
        return RuleActivationResult.model_validate(raw.get("result"))
    except (TypeError, ValueError) as exc:
        raise RuleActivationLedgerCorruptionError(
            "Durable Rule activation result failed validation"
        ) from exc


def _pointer_revision(pointer: Mapping[str, Any] | None) -> int:
    if pointer is None:
        return 0
    revision = pointer.get("revision")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        raise ValueError("Rule activation pointer revision is invalid")
    return revision


def _optional_digest(pointer: Mapping[str, Any] | None, field: str) -> str | None:
    if pointer is None:
        return None
    value = pointer.get(field)
    return value if isinstance(value, str) else None


def _result(
    command: RuleActivationCommand,
    *,
    status: RuleActivationStatus,
    previous_digest: str | None,
    resulting_digest: str | None,
    readback_verified: bool,
    failure_reason: str | None = None,
) -> RuleActivationResult:
    return RuleActivationResult(
        request_id=command.proposal.request_id,
        command_digest=command.command_digest,
        source=command.proposal.source,
        source_ref=command.proposal.source_ref,
        requested_by=command.proposal.requested_by,
        approver_ids=command.approval.approver_ids,
        reason=command.proposal.reason,
        changes=command.proposal.changes,
        status=status,
        previous_generation_digest=previous_digest,
        resulting_generation_digest=resulting_digest,
        completed_at=command.commanded_at,
        readback_verified=readback_verified,
        failure_reason=failure_reason,
    )


def _pointer_audit(
    command: RuleActivationCommand,
    previous_digest: str | None,
    resulting_digest: str,
    revision: int,
) -> dict[str, object]:
    return {
        "actor": command.approval.approver_ids[0],
        "producer_principal": "Mimir",
        "action_kind": "rule_activation.current_changed",
        "mode": "shadow",
        "correlation_id": command.proposal.request_id,
        "idempotency_key": command.proposal.idempotency_key,
        "source": command.proposal.source.value,
        "source_ref": command.proposal.source_ref,
        "source_digest": command.proposal.source_digest,
        "requested_by": command.proposal.requested_by,
        "approver_ids": list(command.approval.approver_ids),
        "approval_ref": command.approval.approval_ref,
        "previous_generation_digest": previous_digest,
        "resulting_generation_digest": resulting_digest,
        "revision": revision,
        "recorded_at": command.commanded_at.isoformat(),
        "execution_authority": False,
    }


__all__ = [
    "RuleActivationLedgerConflictError",
    "RuleActivationLedgerCorruptionError",
    "StateStoreRuleActivationLedger",
]
