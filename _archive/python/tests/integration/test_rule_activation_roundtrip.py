"""Synthetic Rule activation transport across independent Operator and Core stores."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import AsyncIterator, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, cast

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
from fdai.shared.providers.event_bus import EventEnvelope, PublishReceipt
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai_core_service.rule_activation_consumer import RuleActivationConsumer
from fdai_operator_service.rule_activation_outbox import (
    RuleActivationNoticeDrainer,
    RuleActivationProposalClaim,
)
from fdai_service_contracts.rule_activation import RuleActivationProposal

NOW = datetime(2026, 9, 22, tzinfo=UTC)


class Runtime:
    def __init__(self) -> None:
        self.calls: list[tuple[tuple[str, ...], str]] = []
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
        self.calls.append((tuple(rule.id for rule in rules), generation_digest))
        self._generation_digest = generation_digest


class Outbox:
    def __init__(self, claim: RuleActivationProposalClaim) -> None:
        self.claim_value = claim

    async def claim(self) -> RuleActivationProposalClaim | None:
        return self.claim_value

    async def finish(
        self,
        claim: RuleActivationProposalClaim,
        *,
        rejected: bool = False,
    ) -> bool:
        assert claim is self.claim_value
        assert rejected is False
        self.claim_value = cast(Any, None)
        return True

    async def release(self, claim: RuleActivationProposalClaim) -> None:
        assert claim is self.claim_value


class Bus:
    def __init__(self) -> None:
        self.records: list[EventEnvelope] = []
        self.dead_letters: list[tuple[object, ...]] = []

    async def publish(
        self,
        topic: str,
        key: str,
        payload: Mapping[str, object],
    ) -> PublishReceipt:
        self.records.append(EventEnvelope(topic, key, dict(payload), len(self.records)))
        return PublishReceipt(topic, 0, len(self.records))

    async def subscribe(self, topic: str, group_id: str) -> AsyncIterator[EventEnvelope]:
        del group_id
        for record in tuple(self.records):
            if record.topic == topic:
                yield record

    async def dead_letter(
        self,
        topic: str,
        key: str,
        payload: Mapping[str, object],
        reason: str,
    ) -> None:
        self.dead_letters.append((topic, key, payload, reason))


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


def _record(
    *,
    operation: str,
    principal_id: str,
    idempotency_key: str,
    expected_revision: str,
    path_parameters: Mapping[str, str],
    body: Mapping[str, object],
    roles: tuple[str, ...],
    accepted_at: datetime,
) -> tuple[str, dict[str, object]]:
    workflow = {
        "operation": operation,
        "principal_id": principal_id,
        "principal_roles": list(roles),
        "idempotency_key": idempotency_key,
        "expected_revision": expected_revision,
        "path_parameters": dict(path_parameters),
        "payload": dict(body),
        "mode": "shadow",
        "request_source": "operator-http:test",
    }
    request = {
        "family": "workflow",
        "operation": operation,
        "principal_id": principal_id,
        "idempotency_key": idempotency_key,
        "payload": workflow,
    }
    digest = hashlib.sha256(
        json.dumps(request, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()
    key = "operator-proposal:workflow:" + hashlib.sha256(idempotency_key.encode()).hexdigest()
    return key, {
        "kind": "operator.proposal",
        "proposal_id": f"operator-{digest[:32]}",
        "request_digest": digest,
        "dispatch_status": "pending",
        "mode": "shadow",
        "accepted_at": accepted_at.isoformat(),
        **request,
    }


async def test_direct_request_and_distinct_approval_apply_one_generation() -> None:
    operator_receipts = InMemoryStateStore()
    core_store = InMemoryStateStore()
    ledger = StateStoreRuleActivationLedger(store=core_store)
    runtime = Runtime()
    rules = (_rule("rule.alpha"), _rule("rule.beta"))
    await reconcile_rule_activation(
        ledger=ledger,
        available_rules=rules,
        profile_id="baseline",
        profile_version="1.0.0",
        source_ref="runtime-artifact:baseline",
        source_digest="a" * 64,
        requested_by="release-signer",
        approved_by="deployment-approver",
        clock=lambda: NOW,
    )
    current = await ledger.current_generation()
    assert current is not None
    coordinator = RuleActivationCoordinator(
        store=core_store,
        ledger=ledger,
        runtime=runtime,
        available_rules=rules,
    )
    consumer = RuleActivationConsumer(
        receipts=operator_receipts,
        coordinator=coordinator,
        clock=lambda: NOW + timedelta(minutes=3),
    )
    bus = Bus()
    request_key, request = _record(
        operation="rule.activation-request",
        principal_id="requester",
        idempotency_key="disable-beta",
        expected_revision=current.generation_digest,
        path_parameters={},
        body={
            "mode": "shadow",
            "reason": "Disable the reviewed Rule after a confirmed operational false positive.",
            "changes": [{"rule_id": "rule.beta", "enabled": False}],
        },
        roles=("Contributor",),
        accepted_at=NOW + timedelta(minutes=1),
    )
    await operator_receipts.write_state(request_key, request)
    assert await RuleActivationNoticeDrainer(
        Outbox(RuleActivationProposalClaim(request_key, "claim-request", request)),
        bus,
    ).run_once()
    assert "reason" not in bus.records[0].payload
    assert "principal_id" not in bus.records[0].payload
    await consumer.run(bus=cast(Any, bus), stop=asyncio.Event())
    core_request = await core_store.read_states("rule-activation:request:", limit=2)
    assert len(core_request) == 1
    proposal = RuleActivationProposal.model_validate(core_request[0].get("proposal"))

    approval_key, approval = _record(
        operation="rule.activation-approve",
        principal_id="approver",
        idempotency_key="approve-disable-beta",
        expected_revision=proposal.proposal_digest,
        path_parameters={"request_id": str(request["proposal_id"])},
        body={"mode": "shadow", "decision": "approve"},
        roles=("Approver",),
        accepted_at=NOW + timedelta(minutes=2),
    )
    await operator_receipts.write_state(approval_key, approval)
    assert await RuleActivationNoticeDrainer(
        Outbox(RuleActivationProposalClaim(approval_key, "claim-approval", approval)),
        bus,
    ).run_once()
    assert bus.records[0].key == bus.records[1].key == request["proposal_id"]
    await consumer.run(bus=cast(Any, bus), stop=asyncio.Event())

    active = await ledger.current_generation()
    assert active is not None
    assert tuple(member.rule_id for member in active.members) == ("rule.alpha",)
    assert runtime.calls == [(("rule.alpha",), active.generation_digest)]
    assert bus.dead_letters == []
