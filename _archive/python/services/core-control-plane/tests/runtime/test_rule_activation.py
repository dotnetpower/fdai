from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

import pytest
from fdai.core.rule_activation import RuleActivationCoordinator, StateStoreRuleActivationLedger
from fdai.runtime.rule_activation import (
    RuleActivationRuntimeReconciler,
    build_rule_activation_generation,
    reconcile_rule_activation,
)
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
from fdai_service_contracts.rule_activation import RuleActivationSource

NOW = datetime(2026, 9, 22, tzinfo=UTC)


class RecordingRuntime:
    def __init__(self, generation_digest: str | None) -> None:
        self._generation_digest = generation_digest
        self.calls: list[tuple[tuple[str, ...], str]] = []

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


def _rule(rule_id: str, *, version: str = "1.0.0") -> Rule:
    return Rule(
        schema_version="1.0.0",
        id=rule_id,
        version=version,
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


async def test_empty_store_is_seeded_once_with_installer_and_approver_audit() -> None:
    store = InMemoryStateStore()
    ledger = StateStoreRuleActivationLedger(store=store)
    rules = (_rule("rule.alpha"), _rule("rule.beta"))

    first_rules, first_generation = await reconcile_rule_activation(
        ledger=ledger,
        available_rules=rules,
        profile_id="baseline",
        profile_version="1.0.0",
        source_ref="offline-kit:default-profile",
        source_digest="a" * 64,
        requested_by="release-signer",
        approved_by="deployment-approver",
        clock=lambda: NOW,
    )
    second_rules, second_generation = await reconcile_rule_activation(
        ledger=ledger,
        available_rules=rules,
        profile_id="ignored-after-seed",
        profile_version="9.9.9",
        source_ref="offline-kit:other",
        source_digest="b" * 64,
        requested_by="other",
        approved_by="different",
        clock=lambda: NOW,
    )

    assert first_rules == second_rules == rules
    assert first_generation == second_generation
    changed = [
        record["entry"]
        for record in store.audit_entries
        if record["entry"]["action_kind"] == "rule_activation.current_changed"
    ]
    assert len(changed) == 1
    assert changed[0]["actor"] == "deployment-approver"
    assert changed[0]["requested_by"] == "release-signer"
    assert changed[0]["approver_ids"] == ["deployment-approver"]


async def test_existing_generation_rejects_changed_rule_artifact() -> None:
    store = InMemoryStateStore()
    ledger = StateStoreRuleActivationLedger(store=store)
    await reconcile_rule_activation(
        ledger=ledger,
        available_rules=(_rule("rule.alpha"),),
        profile_id="baseline",
        profile_version="1.0.0",
        source_ref="offline-kit:default-profile",
        source_digest="a" * 64,
        requested_by="release-signer",
        approved_by="deployment-approver",
        clock=lambda: NOW,
    )

    with pytest.raises(RuntimeError, match="does not match installed artifact"):
        await reconcile_rule_activation(
            ledger=ledger,
            available_rules=(_rule("rule.alpha", version="2.0.0"),),
            profile_id="baseline",
            profile_version="1.0.0",
            source_ref="offline-kit:default-profile",
            source_digest="a" * 64,
            requested_by="release-signer",
            approved_by="deployment-approver",
            clock=lambda: NOW,
        )


async def test_signed_offline_genesis_records_its_distinct_source() -> None:
    store = InMemoryStateStore()
    ledger = StateStoreRuleActivationLedger(store=store)

    await reconcile_rule_activation(
        ledger=ledger,
        available_rules=(_rule("rule.alpha"),),
        profile_id="baseline",
        profile_version="1.0.0",
        source_ref="offline-kit:manifest",
        source_digest="a" * 64,
        requested_by="release-signer",
        approved_by="deployment-approver",
        source=RuleActivationSource.OFFLINE_PACKAGE,
        clock=lambda: NOW,
    )

    pointer = await store.read_state("rule-activation:current")
    assert pointer is not None
    assert pointer["source"] == "offline_package"
    assert pointer["source_ref"] == "offline-kit:manifest"


async def test_reviewed_pull_request_profile_advances_existing_generation() -> None:
    store = InMemoryStateStore()
    ledger = StateStoreRuleActivationLedger(store=store)
    rules = (_rule("rule.alpha"), _rule("rule.beta"))
    _, original = await reconcile_rule_activation(
        ledger=ledger,
        available_rules=rules,
        desired_rules=rules,
        profile_id="baseline",
        profile_version="1.0.0",
        source_ref="runtime-artifact:baseline",
        source_digest="a" * 64,
        requested_by="release-signer",
        approved_by="deployment-approver",
        clock=lambda: NOW,
    )

    activated, changed = await reconcile_rule_activation(
        ledger=ledger,
        available_rules=rules,
        desired_rules=(_rule("rule.alpha"),),
        profile_id="baseline",
        profile_version="1.0.0",
        source_ref="git:merge:reviewed-profile",
        source_digest="b" * 64,
        requested_by="pull-request-author",
        approved_by="pull-request-reviewer",
        source=RuleActivationSource.PULL_REQUEST,
        clock=lambda: NOW,
    )

    assert tuple(rule.id for rule in activated) == ("rule.alpha",)
    assert changed.generation_digest != original.generation_digest
    pointer = await store.read_state("rule-activation:current")
    assert pointer is not None
    assert pointer["source"] == "pull_request"
    assert pointer["previous_generation_digest"] == original.generation_digest


async def test_replica_reconciler_adopts_another_replica_generation() -> None:
    store = InMemoryStateStore()
    ledger = StateStoreRuleActivationLedger(store=store)
    rules = (_rule("rule.alpha"), _rule("rule.beta"))
    _, original = await reconcile_rule_activation(
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
    _, changed = await reconcile_rule_activation(
        ledger=ledger,
        available_rules=rules,
        desired_rules=(_rule("rule.alpha"),),
        profile_id="baseline",
        profile_version="1.0.0",
        source_ref="git:merge:reviewed-profile",
        source_digest="b" * 64,
        requested_by="pull-request-author",
        approved_by="pull-request-reviewer",
        source=RuleActivationSource.PULL_REQUEST,
        clock=lambda: NOW,
    )
    runtime = RecordingRuntime(original.generation_digest)
    reconciler = RuleActivationRuntimeReconciler(
        RuleActivationCoordinator(
            store=store,
            ledger=ledger,
            runtime=runtime,
            available_rules=rules,
        )
    )

    assert await reconciler.run_once() is True
    assert runtime.calls == [(("rule.alpha",), changed.generation_digest)]
    assert await reconciler.run_once() is False


def test_generation_digest_is_independent_of_rule_input_order() -> None:
    first = _rule("rule.alpha")
    second = _rule("rule.beta")

    left = build_rule_activation_generation(
        (first, second), profile_id="baseline", profile_version="1.0.0", created_at=NOW
    )
    right = build_rule_activation_generation(
        (second, first), profile_id="baseline", profile_version="1.0.0", created_at=NOW
    )

    assert left.generation_digest == right.generation_digest


def test_generation_can_reuse_full_catalog_digest_for_a_membership_subset() -> None:
    generation = build_rule_activation_generation(
        (_rule("rule.alpha"),),
        profile_id="baseline",
        profile_version="1.0.0",
        created_at=NOW,
        catalog_digest="f" * 64,
    )

    assert generation.catalog_digest == "f" * 64
