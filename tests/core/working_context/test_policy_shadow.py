"""Bounded shadow candidate execution and isolation tests."""

from __future__ import annotations

import time
from typing import cast

from fdai.core.capability_catalog import (
    Capability,
    CapabilityBinding,
    CapabilityBindingKind,
    CapabilityBundle,
    CapabilityCategory,
    CapabilityReferences,
    CapabilityRuntime,
    SideEffectClass,
)
from fdai.core.conversation.context_bridge import assemble_turn_context
from fdai.core.conversation.session import ConversationSession, Principal, Role, Turn
from fdai.core.working_context import (
    DEFAULT_CONTEXT_SELECTION_POLICY,
    ContextBudget,
    ContextPolicyIdentity,
    ContextSelectionInput,
    ContextSelectionOutput,
    ContextSelectionPolicy,
    ContextSelectionPolicyAuthority,
    ContextSelectionShadowRunner,
    ContextShadowConfig,
    ContextTrustClass,
    EntryKind,
    EntryRole,
    InMemoryContextSelectionEvaluationStore,
    ModelCapabilityMetadata,
    TranscriptEntry,
    execute_context_selection_policy,
)


class _ExceptionPolicy:
    policy_id = "exception-policy-v1"
    policy_version = "1.0.0"

    def select(self, selection_input: ContextSelectionInput) -> ContextSelectionOutput:
        raise RuntimeError("shadow exception")


class _TimeoutPolicy:
    policy_id = "timeout-policy-v1"
    policy_version = "1.0.0"

    def select(self, selection_input: ContextSelectionInput) -> ContextSelectionOutput:
        time.sleep(0.05)
        return DEFAULT_CONTEXT_SELECTION_POLICY.select(selection_input)


class _PassingPolicy:
    policy_id = "passing-policy-v1"
    policy_version = "1.0.0"

    def select(self, selection_input: ContextSelectionInput) -> ContextSelectionOutput:
        return DEFAULT_CONTEXT_SELECTION_POLICY.select(selection_input)


def _selection_input() -> ContextSelectionInput:
    entry = TranscriptEntry(
        entry_id="turn",
        role=EntryRole.OPERATOR,
        kind=EntryKind.VERBATIM,
        text="turn",
        tokens=1,
        sequence=0,
    )
    return ContextSelectionInput(
        entries=(entry,),
        trust_classes={"turn": ContextTrustClass.UNTRUSTED_EXTERNAL},
        budget=ContextBudget(
            total_window=2,
            base_reserve=0,
            output_reserve=1,
            tools_reserve=0,
            memory_reserve=0,
            verbatim_ratio=1.0,
            retrieval_ratio=0.0,
            summary_ratio=0.0,
            typed_fact_ratio=0.0,
        ),
        model=ModelCapabilityMetadata(model_id="fixture", context_window=2),
    )


def _authority(*policies: ContextSelectionPolicy) -> ContextSelectionPolicyAuthority:
    capabilities = []
    bindings = []
    refs = set()
    for policy in policies:
        identity = ContextPolicyIdentity(policy.policy_id, policy.policy_version)
        capability_id = f"context.selection.{policy.policy_id}"
        capabilities.append(
            Capability(
                capability_id=capability_id,
                name=policy.policy_id,
                category=CapabilityCategory.INVESTIGATION,
                summary="Shadow context selection candidate.",
                side_effect_class=SideEffectClass.READ,
            )
        )
        bindings.append(
            CapabilityBinding(
                capability_id=capability_id,
                kind=CapabilityBindingKind.CONTEXT_SELECTION_POLICY,
                target_ref=identity.ref,
            )
        )
        refs.add(identity.ref)
    runtime = CapabilityRuntime().install(
        CapabilityBundle(capabilities=tuple(capabilities), bindings=tuple(bindings)),
        references=CapabilityReferences(context_selection_policies=frozenset(refs)),
    )
    authority = ContextSelectionPolicyAuthority(capability_runtime=runtime)
    for policy in policies:
        identity = ContextPolicyIdentity(policy.policy_id, policy.policy_version)
        installed = authority.install(
            policy,
            capability_id=f"context.selection.{identity.policy_id}",
            expected_revision=authority.snapshot().revision,
        )
        authority.enable_shadow(identity, expected_revision=installed.revision)
    return authority


async def test_exception_and_timeout_never_replace_active_output() -> None:
    authority = _authority(
        cast(ContextSelectionPolicy, _ExceptionPolicy()),
        cast(ContextSelectionPolicy, _TimeoutPolicy()),
    )
    store = InMemoryContextSelectionEvaluationStore()
    runner = ContextSelectionShadowRunner(
        authority=authority,
        store=store,
        config=ContextShadowConfig(max_candidates=2, timeout_seconds=0.005),
    )
    selection_input = _selection_input()
    baseline = execute_context_selection_policy(
        policy=authority.active_policy(), selection_input=selection_input
    )
    active_before = authority.snapshot().active

    records = await runner.evaluate(selection_input=selection_input, baseline=baseline)

    assert authority.snapshot().active == active_before
    assert baseline.entries[0].entry_id == "turn"
    assert len(records) == 2
    reasons = {record.candidate_policy_ref: record.failure_reason for record in records}
    exception_reason = reasons["exception-policy-v1@1.0.0"]
    timeout_reason = reasons["timeout-policy-v1@1.0.0"]
    assert exception_reason is not None and exception_reason.startswith("RuntimeError")
    assert timeout_reason is not None and timeout_reason.startswith("timeout>")
    assert all(record.candidate_manifest is None for record in records)
    assert len(await store.list(limit=10)) == 2


async def test_success_persists_comparison_and_answer_linkage() -> None:
    authority = _authority(cast(ContextSelectionPolicy, _PassingPolicy()))
    store = InMemoryContextSelectionEvaluationStore()
    runner = ContextSelectionShadowRunner(authority=authority, store=store)
    selection_input = _selection_input()
    baseline = execute_context_selection_policy(
        policy=authority.active_policy(), selection_input=selection_input
    )

    records = await runner.evaluate(
        selection_input=selection_input,
        baseline=baseline,
        answer_quality_ref="answer-eval-1",
        answer_quality_score=0.9,
    )

    record = records[0]
    assert record.candidate_tokens == baseline.total_tokens
    assert record.evidence_overlap == 1.0
    assert record.omissions == ()
    assert record.pinned_preserved is True
    assert record.answer_quality_ref == "answer-eval-1"
    assert record.answer_quality_score == 0.9
    assert record.failure_reason is None


async def test_shadow_fanout_is_bounded() -> None:
    authority = _authority(
        cast(ContextSelectionPolicy, _PassingPolicy()),
        cast(ContextSelectionPolicy, _ExceptionPolicy()),
    )
    store = InMemoryContextSelectionEvaluationStore()
    runner = ContextSelectionShadowRunner(
        authority=authority,
        store=store,
        config=ContextShadowConfig(max_candidates=1),
    )
    selection_input = _selection_input()
    baseline = execute_context_selection_policy(
        policy=authority.active_policy(), selection_input=selection_input
    )

    records = await runner.evaluate(selection_input=selection_input, baseline=baseline)

    assert len(records) == 1


async def test_async_composition_schedules_shadow_without_candidate_output() -> None:
    authority = _authority(cast(ContextSelectionPolicy, _PassingPolicy()))
    store = InMemoryContextSelectionEvaluationStore()
    runner = ContextSelectionShadowRunner(authority=authority, store=store)
    session = ConversationSession(
        session_id="session-1",
        principal=Principal(id="operator-1", role=Role.READER),
        channel_id="cli",
    )
    session.append(Turn(turn_id="turn-1", direction="inbound", content="status"))

    context = await assemble_turn_context(
        session=session,
        utterance="status",
        budget=_selection_input().budget,
        policy_authority=authority,
        shadow_runner=runner,
        token_estimator=lambda _: 1,
    )

    assert context.manifest.verbatim_ids == ("turn-1",)
    await runner.drain()
    comparisons = await store.list(limit=10)
    assert len(comparisons) == 1
    assert comparisons[0].candidate_policy_ref == "passing-policy-v1@1.0.0"
