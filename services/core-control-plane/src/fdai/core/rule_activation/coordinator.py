"""Two-stage Operator request and approval coordination for Rule activation."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any, Protocol

from fdai_service_contracts.rule_activation import (
    RuleActivationApproval,
    RuleActivationCommand,
    RuleActivationDelta,
    RuleActivationProposal,
    RuleActivationSource,
    RuleActivationStatus,
    rule_activation_proposal_digest,
)

from fdai.core.rule_activation.generation import (
    build_rule_activation_generation,
    resolve_rule_activation_generation,
)
from fdai.core.rule_activation.ledger import StateStoreRuleActivationLedger
from fdai.shared.contracts.models import Rule
from fdai.shared.providers.state_store import StateStore


class RuleGenerationRuntime(Protocol):
    """Atomic runtime membership replacement owned by the ControlLoop."""

    @property
    def rule_generation_digest(self) -> str | None: ...

    async def replace_rule_generation(
        self,
        *,
        rules: Sequence[Rule],
        generation_digest: str,
    ) -> None: ...


class RuleActivationCoordinator:
    """Join authenticated direct requests with distinct approvals before application."""

    _REQUEST_PREFIX = "rule-activation:request:"

    def __init__(
        self,
        *,
        store: StateStore,
        ledger: StateStoreRuleActivationLedger,
        runtime: RuleGenerationRuntime,
        available_rules: Sequence[Rule],
    ) -> None:
        self._store = store
        self._ledger = ledger
        self._runtime = runtime
        self._available = {rule.id: rule for rule in available_rules}
        if not self._available or len(self._available) != len(available_rules):
            raise ValueError("Rule activation catalog MUST contain unique non-empty membership")

    async def accept_request(
        self,
        record: Mapping[str, Any],
        *,
        source_ref: str,
        at: datetime,
    ) -> RuleActivationProposal:
        """Persist an inert direct request after independently validating its source record."""

        proposal = _direct_proposal(record, source_ref=source_ref)
        key = f"{self._REQUEST_PREFIX}{proposal.request_id}"
        value = {
            "schema_version": "1.0.0",
            "kind": "rule_activation.request",
            "operator_proposal_id": record["proposal_id"],
            "proposal": proposal.model_dump(mode="json"),
            "revision": 1,
        }
        created = await self._store.write_state_with_audit_if_absent(
            key,
            value,
            {
                "actor": proposal.requested_by,
                "producer_principal": "Saga",
                "action_kind": "rule_activation.requested",
                "mode": "shadow",
                "correlation_id": proposal.request_id,
                "idempotency_key": proposal.idempotency_key,
                "source": proposal.source.value,
                "source_ref": proposal.source_ref,
                "proposal_digest": proposal.proposal_digest,
                "changes": [change.model_dump(mode="json") for change in proposal.changes],
                "reason": proposal.reason,
                "recorded_at": _aware(at).isoformat(),
                "approval_authority": False,
                "execution_authority": False,
            },
        )
        if created:
            return proposal
        existing = await self._store.read_state(key)
        if existing != value:
            raise ValueError("Rule activation request conflicts with durable state")
        return proposal

    async def approve(
        self,
        record: Mapping[str, Any],
        *,
        source_ref: str,
        at: datetime,
    ) -> RuleActivationStatus:
        """Verify a distinct approval, apply the exact generation, and update runtime."""

        approval_record = _workflow_record(record, "rule.activation-approve")
        payload = _mapping(approval_record["payload"], "approval workflow proposal")
        path = _mapping(payload.get("path_parameters"), "approval path parameters")
        operator_proposal_id = _text(path.get("request_id"), "activation request id")
        stored = await self._store.find_state(
            self._REQUEST_PREFIX,
            field="operator_proposal_id",
            value=operator_proposal_id,
        )
        if stored is None:
            raise ValueError("Rule activation request is unavailable")
        proposal = RuleActivationProposal.model_validate(stored.get("proposal"))
        if payload.get("expected_revision") != proposal.proposal_digest:
            raise ValueError("Rule activation approval revision does not match the request")
        body = _mapping(payload.get("payload"), "approval body")
        if body.get("mode") != "shadow" or body.get("decision") != "approve":
            raise ValueError("Rule activation approval decision is invalid")
        approver = _text(approval_record.get("principal_id"), "activation approver")
        roles = payload.get("principal_roles")
        if not isinstance(roles, list | tuple) or not {"Approver", "Owner"}.intersection(roles):
            raise ValueError("Rule activation approval lacks an approver role")
        if approver.casefold() == proposal.requested_by.casefold():
            raise ValueError("Rule activation requester MUST NOT approve the same change")
        approved_at = _timestamp(approval_record.get("accepted_at"), "approval accepted_at")
        approval = RuleActivationApproval(
            proposal_digest=proposal.proposal_digest,
            approver_ids=(approver,),
            approved_at=approved_at,
            approval_ref=source_ref,
        )
        terminal = await self._ledger.result_for_request(proposal.request_id)
        if terminal is not None:
            if terminal.status in {
                RuleActivationStatus.APPLIED,
                RuleActivationStatus.ALREADY_APPLIED,
            }:
                await self.synchronize_runtime()
            return terminal.status
        current = await self._ledger.current_generation()
        if current is None:
            raise ValueError("Rule activation generation is unavailable")
        selected = {member.rule_id for member in current.members}
        for change in proposal.changes:
            if change.enabled:
                selected.add(change.rule_id)
            else:
                selected.discard(change.rule_id)
        if not selected:
            raise ValueError("Rule activation change cannot remove every Rule")
        try:
            rules = tuple(self._available[rule_id] for rule_id in sorted(selected))
        except KeyError as exc:
            raise ValueError("Rule activation references an unavailable Rule artifact") from exc
        generation = build_rule_activation_generation(
            rules,
            profile_id=current.profile_id,
            profile_version=current.profile_version,
            created_at=approved_at,
            catalog_digest=current.catalog_digest,
        )
        command = RuleActivationCommand(
            proposal=proposal,
            approval=approval,
            generation=generation,
            commanded_at=approved_at,
        )
        result = await self._ledger.apply(command)
        if result.status in {
            RuleActivationStatus.APPLIED,
            RuleActivationStatus.ALREADY_APPLIED,
        }:
            await self.synchronize_runtime()
        return result.status

    async def synchronize_runtime(self) -> bool:
        """Converge this process on the exact authoritative current generation."""

        current = await self._ledger.current_generation()
        if current is None:
            raise ValueError("Rule activation generation is unavailable")
        if self._runtime.rule_generation_digest == current.generation_digest:
            return False
        rules = resolve_rule_activation_generation(current, self._available)
        await self._runtime.replace_rule_generation(
            rules=rules,
            generation_digest=current.generation_digest,
        )
        return True


def _direct_proposal(record: Mapping[str, Any], *, source_ref: str) -> RuleActivationProposal:
    verified = _workflow_record(record, "rule.activation-request")
    workflow = _mapping(verified["payload"], "activation workflow proposal")
    body = _mapping(workflow.get("payload"), "activation request body")
    if body.get("mode") != "shadow":
        raise ValueError("Rule activation request MUST remain shadow-first")
    raw_changes = body.get("changes")
    if not isinstance(raw_changes, list):
        raise ValueError("Rule activation request changes are invalid")
    changes = tuple(
        sorted(
            (RuleActivationDelta.model_validate(change) for change in raw_changes),
            key=lambda change: change.rule_id,
        )
    )
    requested_at = _timestamp(verified.get("accepted_at"), "request accepted_at")
    idempotency_key = _text(verified.get("idempotency_key"), "idempotency key")
    expected_generation_digest = _text(workflow.get("expected_revision"), "expected generation")
    source_digest = _text(verified.get("request_digest"), "source digest")
    requested_by = _text(verified.get("principal_id"), "requester")
    reason = _text(body.get("reason"), "activation reason")
    digest = rule_activation_proposal_digest(
        idempotency_key=idempotency_key,
        expected_generation_digest=expected_generation_digest,
        source=RuleActivationSource.DIRECT,
        source_ref=source_ref,
        source_digest=source_digest,
        requested_by=requested_by,
        requested_at=requested_at,
        reason=reason,
        changes=changes,
    )
    return RuleActivationProposal(
        request_id=f"rule-activation-request-{digest[:32]}",
        idempotency_key=idempotency_key,
        expected_generation_digest=expected_generation_digest,
        source=RuleActivationSource.DIRECT,
        source_ref=source_ref,
        source_digest=source_digest,
        requested_by=requested_by,
        requested_at=requested_at,
        reason=reason,
        changes=changes,
    )


def _workflow_record(record: Mapping[str, Any], operation: str) -> Mapping[str, Any]:
    payload = _mapping(record.get("payload"), "workflow proposal")
    request = {
        "family": record.get("family"),
        "operation": record.get("operation"),
        "principal_id": record.get("principal_id"),
        "idempotency_key": record.get("idempotency_key"),
        "payload": payload,
    }
    digest = hashlib.sha256(
        json.dumps(request, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()
    if (
        record.get("kind") != "operator.proposal"
        or record.get("family") != "workflow"
        or record.get("operation") != operation
        or record.get("mode") != "shadow"
        or record.get("request_digest") != digest
        or record.get("proposal_id") != f"operator-{digest[:32]}"
    ):
        raise ValueError("Rule activation Operator proposal identity is invalid")
    return record


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} is invalid")
    return value


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ValueError(f"{label} is invalid")
    return value


def _timestamp(value: object, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(_text(value, label))
    except ValueError as exc:
        raise ValueError(f"{label} is invalid") from exc
    return _aware(parsed)


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Rule activation time MUST be timezone-aware")
    return value.astimezone(UTC)


__all__ = ["RuleActivationCoordinator", "RuleGenerationRuntime"]
