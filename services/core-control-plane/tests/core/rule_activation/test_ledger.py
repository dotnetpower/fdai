from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.rule_activation import (
    RuleActivationLedgerConflictError,
    StateStoreRuleActivationLedger,
)
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai_service_contracts.rule_activation import (
    RuleActivationApproval,
    RuleActivationCommand,
    RuleActivationDelta,
    RuleActivationGeneration,
    RuleActivationMember,
    RuleActivationProposal,
    RuleActivationSource,
    RuleActivationStatus,
    rule_activation_generation_digest,
    rule_activation_proposal_digest,
)

NOW = datetime(2026, 9, 22, tzinfo=UTC)
CATALOG_DIGEST = "a" * 64


def _generation(*rule_ids: str) -> RuleActivationGeneration:
    members = tuple(
        RuleActivationMember(
            rule_id=rule_id,
            rule_version="1.0.0",
            rule_digest=(chr(ord("b") + index) * 64),
        )
        for index, rule_id in enumerate(sorted(rule_ids))
    )
    digest = rule_activation_generation_digest(
        profile_id="baseline",
        profile_version="1.0.0",
        catalog_digest=CATALOG_DIGEST,
        members=members,
    )
    return RuleActivationGeneration(
        generation_id=f"rule-activation-{digest[:32]}",
        generation_digest=digest,
        profile_id="baseline",
        profile_version="1.0.0",
        catalog_digest=CATALOG_DIGEST,
        members=members,
        created_at=NOW,
    )


def _command(
    generation: RuleActivationGeneration,
    *,
    source: RuleActivationSource,
    expected: str | None,
    changes: tuple[RuleActivationDelta, ...],
    idempotency_key: str,
) -> RuleActivationCommand:
    values = {
        "idempotency_key": idempotency_key,
        "expected_generation_digest": expected,
        "source": source,
        "source_ref": f"{source.value}:activation",
        "source_digest": "f" * 64,
        "requested_by": "requester",
        "requested_at": NOW,
        "reason": "Apply the reviewed Rule membership generation safely.",
        "changes": changes,
    }
    digest = rule_activation_proposal_digest(**values)
    proposal = RuleActivationProposal(
        request_id=f"rule-activation-request-{digest[:32]}",
        **values,
    )
    approval = RuleActivationApproval(
        proposal_digest=proposal.proposal_digest,
        approver_ids=("approver",),
        approved_at=NOW + timedelta(seconds=1),
        approval_ref="approval:rule-activation",
    )
    return RuleActivationCommand(
        proposal=proposal,
        approval=approval,
        generation=generation,
        commanded_at=NOW + timedelta(seconds=2),
    )


async def _install(
    ledger: StateStoreRuleActivationLedger,
    generation: RuleActivationGeneration,
    *,
    idempotency_key: str = "install-baseline",
) -> RuleActivationCommand:
    command = _command(
        generation,
        source=RuleActivationSource.INSTALLATION,
        expected=None,
        changes=tuple(
            RuleActivationDelta(rule_id=member.rule_id, enabled=True)
            for member in generation.members
        ),
        idempotency_key=idempotency_key,
    )
    await ledger.apply(command)
    return command


async def test_installation_creates_generation_pointer_and_actor_audit() -> None:
    store = InMemoryStateStore()
    ledger = StateStoreRuleActivationLedger(store=store)
    generation = _generation("rule.alpha")
    command = await _install(ledger, generation)

    result = await ledger.result_for(command)

    assert result is not None and result.status is RuleActivationStatus.APPLIED
    assert await ledger.current_generation() == generation
    entries = [record["entry"] for record in store.audit_entries]
    changed = next(
        entry for entry in entries if entry["action_kind"] == "rule_activation.current_changed"
    )
    assert changed["actor"] == "approver"
    assert changed["requested_by"] == "requester"
    assert changed["approver_ids"] == ["approver"]
    assert changed["producer_principal"] == "Mimir"


async def test_replay_returns_one_terminal_without_second_pointer_audit() -> None:
    store = InMemoryStateStore()
    ledger = StateStoreRuleActivationLedger(store=store)
    command = await _install(ledger, _generation("rule.alpha"))

    first = await ledger.result_for(command)
    second = await ledger.apply(command)

    assert second == first
    entries = [record["entry"] for record in store.audit_entries]
    assert sum(entry["action_kind"] == "rule_activation.current_changed" for entry in entries) == 1


async def test_stale_expected_generation_is_audited_conflict() -> None:
    store = InMemoryStateStore()
    ledger = StateStoreRuleActivationLedger(store=store)
    initial = _generation("rule.alpha")
    await _install(ledger, initial)
    stale = _command(
        _generation("rule.alpha", "rule.beta"),
        source=RuleActivationSource.DIRECT,
        expected="0" * 64,
        changes=(RuleActivationDelta(rule_id="rule.beta", enabled=True),),
        idempotency_key="enable-beta-stale",
    )

    result = await ledger.apply(stale)

    assert result.status is RuleActivationStatus.CONFLICT
    assert result.failure_reason == "active_generation_identity_mismatch"
    assert await ledger.current_generation() == initial


async def test_candidate_cannot_replace_unchanged_rule_artifact() -> None:
    store = InMemoryStateStore()
    ledger = StateStoreRuleActivationLedger(store=store)
    initial = _generation("rule.alpha")
    await _install(ledger, initial)
    target = _generation("rule.alpha", "rule.beta")
    members = (
        target.members[0].model_copy(update={"rule_digest": "e" * 64}),
        target.members[1],
    )
    digest = rule_activation_generation_digest(
        profile_id=target.profile_id,
        profile_version=target.profile_version,
        catalog_digest=target.catalog_digest,
        members=members,
    )
    malicious = target.model_copy(
        update={
            "generation_id": f"rule-activation-{digest[:32]}",
            "generation_digest": digest,
            "members": members,
        }
    )
    command = _command(
        malicious,
        source=RuleActivationSource.DIRECT,
        expected=initial.generation_digest,
        changes=(RuleActivationDelta(rule_id="rule.beta", enabled=True),),
        idempotency_key="replace-alpha",
    )

    result = await ledger.apply(command)

    assert result.status is RuleActivationStatus.REJECTED
    assert await ledger.current_generation() == initial


async def test_idempotency_key_reuse_with_different_command_is_rejected() -> None:
    store = InMemoryStateStore()
    ledger = StateStoreRuleActivationLedger(store=store)
    await _install(ledger, _generation("rule.alpha"), idempotency_key="same-key")
    conflicting = _command(
        _generation("rule.beta"),
        source=RuleActivationSource.INSTALLATION,
        expected=None,
        changes=(RuleActivationDelta(rule_id="rule.beta", enabled=True),),
        idempotency_key="same-key",
    )

    with pytest.raises(RuleActivationLedgerConflictError, match="idempotency key"):
        await ledger.apply(conflicting)
