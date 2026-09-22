from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.rule_activation import (
    RuleActivationCoordinator,
    StateStoreRuleActivationLedger,
)
from fdai.runtime.rule_activation import reconcile_rule_activation
from fdai.shared.contracts.models import (
    Category,
    CheckLogic,
    CheckLogicKind,
    Provenance,
    Redistribution,
    Remediation,
    Rule,
    RuleSource,
    Severity,
)
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai_service_contracts.rule_activation import RuleActivationStatus

NOW = datetime(2026, 9, 22, tzinfo=UTC)


class RecordingRuntime:
    def __init__(self) -> None:
        self.calls: list[tuple[tuple[str, ...], str]] = []
        self.fail_next = False
        self._generation_digest: str | None = None

    @property
    def rule_generation_digest(self) -> str | None:
        return self._generation_digest

    async def replace_rule_generation(
        self,
        *,
        rules: Sequence[Rule],
        generation_digest: str,
    ) -> None:
        if self.fail_next:
            self.fail_next = False
            raise RuntimeError("runtime replacement failed")
        self.calls.append((tuple(rule.id for rule in rules), generation_digest))
        self._generation_digest = generation_digest


def _rule(rule_id: str) -> Rule:
    return Rule(
        schema_version="1.0.0",
        id=rule_id,
        version="1.0.0",
        source=RuleSource.CUSTOM,
        severity=Severity.LOW,
        category=Category.SECURITY,
        resource_type="example.resource",
        check_logic=CheckLogic(kind=CheckLogicKind.REGO, reference="policies/example.rego"),
        remediation=Remediation(template_ref="remediation/example.tftpl"),
        remediates="remediate.example",
        provenance=Provenance(
            source_url="https://example.com/rule",
            resolved_ref="0" * 40,
            content_hash="sha256:example",
            license="MIT",
            redistribution=Redistribution.EMBEDDABLE,
            retrieved_at=NOW,
        ),
    )


def _operator_record(
    *,
    operation: str,
    principal_id: str,
    idempotency_key: str,
    expected_revision: str,
    path_parameters: Mapping[str, str],
    body: Mapping[str, object],
    accepted_at: datetime,
    roles: tuple[str, ...],
) -> dict[str, object]:
    workflow = {
        "operation": operation,
        "principal_id": principal_id,
        "idempotency_key": idempotency_key,
        "expected_revision": expected_revision,
        "request_source": "operator-http:test",
        "path_parameters": dict(path_parameters),
        "payload": dict(body),
        "mode": "shadow",
        "principal_roles": list(roles),
    }
    request: dict[str, object] = {
        "family": "workflow",
        "operation": operation,
        "principal_id": principal_id,
        "idempotency_key": idempotency_key,
        "payload": workflow,
    }
    digest = hashlib.sha256(
        json.dumps(request, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()
    return {
        "kind": "operator.proposal",
        "proposal_id": f"operator-{digest[:32]}",
        "request_digest": digest,
        "dispatch_status": "pending",
        "mode": "shadow",
        "accepted_at": accepted_at.isoformat(),
        **request,
    }


async def _coordinator() -> tuple[
    InMemoryStateStore,
    StateStoreRuleActivationLedger,
    RecordingRuntime,
    RuleActivationCoordinator,
]:
    store = InMemoryStateStore()
    ledger = StateStoreRuleActivationLedger(store=store)
    runtime = RecordingRuntime()
    rules = (_rule("rule.alpha"), _rule("rule.beta"))
    await reconcile_rule_activation(
        ledger=ledger,
        available_rules=rules,
        profile_id="baseline",
        profile_version="1.0.0",
        source_ref="offline-kit:baseline",
        source_digest="a" * 64,
        requested_by="release-signer",
        approved_by="deployment-approver",
        clock=lambda: NOW,
    )
    return (
        store,
        ledger,
        runtime,
        RuleActivationCoordinator(
            store=store,
            ledger=ledger,
            runtime=runtime,
            available_rules=rules,
        ),
    )


async def test_distinct_approval_changes_db_generation_and_runtime_membership() -> None:
    store, ledger, runtime, coordinator = await _coordinator()
    current = await ledger.current_generation()
    assert current is not None
    request = _operator_record(
        operation="rule.activation-request",
        principal_id="requester",
        idempotency_key="disable-beta",
        expected_revision=current.generation_digest,
        path_parameters={},
        body={
            "mode": "shadow",
            "reason": "Disable the reviewed Rule after an operational false positive.",
            "changes": [{"rule_id": "rule.beta", "enabled": False}],
        },
        accepted_at=NOW + timedelta(minutes=1),
        roles=("Contributor",),
    )
    proposal = await coordinator.accept_request(
        request,
        source_ref="operator-proposal:workflow:disable-beta",
        at=NOW + timedelta(minutes=1),
    )
    approval = _operator_record(
        operation="rule.activation-approve",
        principal_id="approver",
        idempotency_key="approve-disable-beta",
        expected_revision=proposal.proposal_digest,
        path_parameters={"request_id": str(request["proposal_id"])},
        body={"mode": "shadow", "decision": "approve"},
        accepted_at=NOW + timedelta(minutes=2),
        roles=("Approver",),
    )

    status = await coordinator.approve(
        approval,
        source_ref="operator-proposal:workflow:approve-disable-beta",
        at=NOW + timedelta(minutes=2),
    )

    assert status is RuleActivationStatus.APPLIED
    active = await ledger.current_generation()
    assert active is not None
    assert tuple(member.rule_id for member in active.members) == ("rule.alpha",)
    assert runtime.calls == [(("rule.alpha",), active.generation_digest)]
    request_audit = next(
        record["entry"]
        for record in store.audit_entries
        if record["entry"]["action_kind"] == "rule_activation.requested"
    )
    assert request_audit["actor"] == "requester"
    pointer_audit = next(
        record["entry"]
        for record in store.audit_entries
        if record["entry"]["action_kind"] == "rule_activation.current_changed"
        and record["entry"].get("source") == "direct"
    )
    assert pointer_audit["actor"] == "approver"
    assert pointer_audit["requested_by"] == "requester"

    replay_status = await coordinator.approve(
        approval,
        source_ref="operator-proposal:workflow:approve-disable-beta",
        at=NOW + timedelta(hours=1),
    )
    assert replay_status is RuleActivationStatus.APPLIED
    assert runtime.calls == [(("rule.alpha",), active.generation_digest)]


async def test_requester_cannot_approve_their_own_change() -> None:
    _, ledger, runtime, coordinator = await _coordinator()
    current = await ledger.current_generation()
    assert current is not None
    request = _operator_record(
        operation="rule.activation-request",
        principal_id="same-person",
        idempotency_key="disable-beta",
        expected_revision=current.generation_digest,
        path_parameters={},
        body={
            "mode": "shadow",
            "reason": "Disable the reviewed Rule after an operational false positive.",
            "changes": [{"rule_id": "rule.beta", "enabled": False}],
        },
        accepted_at=NOW + timedelta(minutes=1),
        roles=("Owner",),
    )
    proposal = await coordinator.accept_request(
        request,
        source_ref="operator-proposal:workflow:disable-beta",
        at=NOW + timedelta(minutes=1),
    )
    approval = _operator_record(
        operation="rule.activation-approve",
        principal_id="same-person",
        idempotency_key="approve-disable-beta",
        expected_revision=proposal.proposal_digest,
        path_parameters={"request_id": str(request["proposal_id"])},
        body={"mode": "shadow", "decision": "approve"},
        accepted_at=NOW + timedelta(minutes=2),
        roles=("Owner",),
    )

    with pytest.raises(ValueError, match="MUST NOT approve"):
        await coordinator.approve(
            approval,
            source_ref="operator-proposal:workflow:approve-disable-beta",
            at=NOW + timedelta(minutes=2),
        )

    assert runtime.calls == []


async def test_approval_replay_repairs_runtime_after_durable_apply() -> None:
    _, ledger, runtime, coordinator = await _coordinator()
    current = await ledger.current_generation()
    assert current is not None
    request = _operator_record(
        operation="rule.activation-request",
        principal_id="requester",
        idempotency_key="repair-disable-beta",
        expected_revision=current.generation_digest,
        path_parameters={},
        body={
            "mode": "shadow",
            "reason": "Disable the reviewed Rule after an operational false positive.",
            "changes": [{"rule_id": "rule.beta", "enabled": False}],
        },
        accepted_at=NOW + timedelta(minutes=1),
        roles=("Contributor",),
    )
    proposal = await coordinator.accept_request(
        request,
        source_ref="operator-proposal:workflow:repair-disable-beta",
        at=NOW + timedelta(minutes=1),
    )
    approval = _operator_record(
        operation="rule.activation-approve",
        principal_id="approver",
        idempotency_key="approve-repair-disable-beta",
        expected_revision=proposal.proposal_digest,
        path_parameters={"request_id": str(request["proposal_id"])},
        body={"mode": "shadow", "decision": "approve"},
        accepted_at=NOW + timedelta(minutes=2),
        roles=("Approver",),
    )
    runtime.fail_next = True

    with pytest.raises(RuntimeError, match="runtime replacement failed"):
        await coordinator.approve(
            approval,
            source_ref="operator-proposal:workflow:approve-repair-disable-beta",
            at=NOW + timedelta(minutes=2),
        )

    applied = await ledger.current_generation()
    assert applied is not None
    assert tuple(member.rule_id for member in applied.members) == ("rule.alpha",)
    assert runtime.rule_generation_digest is None

    assert (
        await coordinator.approve(
            approval,
            source_ref="operator-proposal:workflow:approve-repair-disable-beta",
            at=NOW + timedelta(minutes=3),
        )
        is RuleActivationStatus.APPLIED
    )
    assert runtime.calls == [(("rule.alpha",), applied.generation_digest)]


async def test_contributor_cannot_approve_activation() -> None:
    _, ledger, runtime, coordinator = await _coordinator()
    current = await ledger.current_generation()
    assert current is not None
    request = _operator_record(
        operation="rule.activation-request",
        principal_id="requester",
        idempotency_key="disable-beta",
        expected_revision=current.generation_digest,
        path_parameters={},
        body={
            "mode": "shadow",
            "reason": "Disable the reviewed Rule after an operational false positive.",
            "changes": [{"rule_id": "rule.beta", "enabled": False}],
        },
        accepted_at=NOW + timedelta(minutes=1),
        roles=("Contributor",),
    )
    proposal = await coordinator.accept_request(
        request,
        source_ref="operator-proposal:workflow:disable-beta",
        at=NOW + timedelta(minutes=1),
    )
    approval = _operator_record(
        operation="rule.activation-approve",
        principal_id="contributor",
        idempotency_key="approve-disable-beta",
        expected_revision=proposal.proposal_digest,
        path_parameters={"request_id": str(request["proposal_id"])},
        body={"mode": "shadow", "decision": "approve"},
        accepted_at=NOW + timedelta(minutes=2),
        roles=("Contributor",),
    )

    with pytest.raises(ValueError, match="lacks an approver role"):
        await coordinator.approve(
            approval,
            source_ref="operator-proposal:workflow:approve-disable-beta",
            at=NOW + timedelta(minutes=2),
        )

    assert runtime.calls == []
