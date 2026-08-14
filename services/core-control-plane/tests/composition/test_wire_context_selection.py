"""Composition tests for durable context-selection shadow evaluation."""

from __future__ import annotations

from dataclasses import replace
from typing import cast

import pytest
from fdai.composition import (
    Container,
    bind_context_selection_shadow,
    install_capability_bundle,
)
from fdai.core.capability_catalog import (
    Capability,
    CapabilityBinding,
    CapabilityBindingKind,
    CapabilityBundle,
    CapabilityCategory,
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
    ContextShadowConfig,
    ContextTrustClass,
    EntryKind,
    EntryRole,
    ModelCapabilityMetadata,
    TranscriptEntry,
    execute_context_selection_policy,
)
from fdai.shared.providers.testing.state_store import InMemoryStateStore

CAPABILITY_ID = "context.selection.composed-shadow-v1"
POLICY_REF = "composed-shadow-v1@1.0.0"


class _CandidatePolicy:
    """Deterministic candidate that mirrors the shipped tiered selection."""

    policy_id = "composed-shadow-v1"
    policy_version = "1.0.0"

    def select(self, selection_input: ContextSelectionInput) -> ContextSelectionOutput:
        return DEFAULT_CONTEXT_SELECTION_POLICY.select(selection_input)


def _budget() -> ContextBudget:
    return ContextBudget(
        total_window=8,
        base_reserve=0,
        output_reserve=1,
        tools_reserve=0,
        memory_reserve=0,
        verbatim_ratio=1.0,
        retrieval_ratio=0.0,
        summary_ratio=0.0,
        typed_fact_ratio=0.0,
    )


def _selection_input() -> ContextSelectionInput:
    entry = TranscriptEntry(
        entry_id="turn-1",
        role=EntryRole.OPERATOR,
        kind=EntryKind.VERBATIM,
        text="status",
        tokens=1,
        sequence=0,
    )
    return ContextSelectionInput(
        entries=(entry,),
        trust_classes={entry.entry_id: ContextTrustClass.UNTRUSTED_EXTERNAL},
        budget=_budget(),
        model=ModelCapabilityMetadata(model_id="fixture", context_window=8),
    )


def _bundle() -> CapabilityBundle:
    return CapabilityBundle(
        capabilities=(
            Capability(
                capability_id=CAPABILITY_ID,
                name="Composed shadow policy",
                category=CapabilityCategory.INVESTIGATION,
                summary="Composition shadow evaluation test policy.",
                side_effect_class=SideEffectClass.READ,
            ),
        ),
        bindings=(
            CapabilityBinding(
                capability_id=CAPABILITY_ID,
                kind=CapabilityBindingKind.CONTEXT_SELECTION_POLICY,
                target_ref=POLICY_REF,
            ),
        ),
    )


def _session() -> ConversationSession:
    session = ConversationSession(
        session_id="session-1",
        principal=Principal(id="operator-1", role=Role.READER),
        channel_id="cli",
    )
    session.append(Turn(turn_id="turn-1", direction="inbound", content="status"))
    return session


def _enable_shadow_candidate(container: Container) -> Container:
    installed = install_capability_bundle(
        container,
        _bundle(),
        context_selection_policies=(POLICY_REF,),
    )
    authority = installed.context_selection_policy_authority
    assert authority is not None
    record = authority.install(
        cast(ContextSelectionPolicy, _CandidatePolicy()),
        capability_id=CAPABILITY_ID,
        expected_revision=authority.snapshot().revision,
    )
    authority.enable_shadow(
        ContextPolicyIdentity(_CandidatePolicy.policy_id, _CandidatePolicy.policy_version),
        expected_revision=record.revision,
    )
    return installed


def test_default_container_leaves_shadow_evaluation_unbound(container: Container) -> None:
    assert container.context_selection_shadow_runner is None


def test_shadow_binding_requires_policy_authority(container: Container) -> None:
    unbound = replace(container)
    object.__setattr__(unbound, "context_selection_policy_authority", None)

    with pytest.raises(ValueError, match="requires a policy authority"):
        bind_context_selection_shadow(unbound, state_store=InMemoryStateStore())


async def test_assembled_turn_persists_bounded_shadow_comparison(container: Container) -> None:
    state_store = InMemoryStateStore()
    bound = bind_context_selection_shadow(
        _enable_shadow_candidate(container),
        state_store=state_store,
        config=ContextShadowConfig(max_candidates=1),
    )
    runner = bound.context_selection_shadow_runner
    assert runner is not None

    context = await assemble_turn_context(
        session=_session(),
        utterance="status",
        budget=_budget(),
        policy_authority=bound.context_selection_policy_authority,
        shadow_runner=runner,
        token_estimator=lambda _: 1,
    )

    assert context.manifest.verbatim_ids == ("turn-1",)
    await runner.drain()
    comparisons = await runner.store.list(limit=10)
    assert len(comparisons) == 1
    assert comparisons[0].candidate_policy_ref == POLICY_REF
    assert comparisons[0].failure_reason is None
    durable = await state_store.read_states("context-selection:evaluation:", limit=10)
    assert len(durable) == 1


async def test_bundle_install_rebinds_runner_to_refreshed_authority(container: Container) -> None:
    bound = bind_context_selection_shadow(container, state_store=InMemoryStateStore())
    reinstalled = _enable_shadow_candidate(bound)

    runner = reinstalled.context_selection_shadow_runner
    assert runner is not None
    assert runner is not bound.context_selection_shadow_runner
    assert bound.context_selection_shadow_runner is not None
    assert runner.store is bound.context_selection_shadow_runner.store

    selection_input = _selection_input()
    records = await runner.evaluate(
        selection_input=selection_input,
        baseline=execute_context_selection_policy(
            policy=DEFAULT_CONTEXT_SELECTION_POLICY,
            selection_input=selection_input,
        ),
    )

    assert [record.candidate_policy_ref for record in records] == [POLICY_REF]
