"""Promotion, rollback, auto-demotion, and concurrency tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

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
from fdai.core.working_context import (
    DEFAULT_CONTEXT_SELECTION_POLICY,
    ContextBudget,
    ContextPolicyEvidence,
    ContextPolicyGovernanceError,
    ContextPolicyIdentity,
    ContextPolicyState,
    ContextSelectionInput,
    ContextSelectionOutput,
    ContextSelectionPolicyAuthority,
    ContextTrustClass,
    EntryKind,
    EntryRole,
    ModelCapabilityMetadata,
    TranscriptEntry,
)


class _CandidatePolicy:
    policy_id = "candidate-tiered-v1"
    policy_version = "1.0.0"

    def select(self, selection_input: ContextSelectionInput) -> ContextSelectionOutput:
        return DEFAULT_CONTEXT_SELECTION_POLICY.select(selection_input)


def _runtime(identity: ContextPolicyIdentity) -> CapabilityRuntime:
    capability_id = "context.selection.candidate-tiered-v1"
    capability = Capability(
        capability_id=capability_id,
        name="Candidate context selection",
        category=CapabilityCategory.INVESTIGATION,
        summary="Select bounded context in shadow before promotion.",
        side_effect_class=SideEffectClass.READ,
    )
    return CapabilityRuntime().install(
        CapabilityBundle(
            capabilities=(capability,),
            bindings=(
                CapabilityBinding(
                    capability_id=capability_id,
                    kind=CapabilityBindingKind.CONTEXT_SELECTION_POLICY,
                    target_ref=identity.ref,
                ),
            ),
        ),
        references=CapabilityReferences(context_selection_policies=frozenset({identity.ref})),
    )


def _authority() -> tuple[ContextSelectionPolicyAuthority, ContextPolicyIdentity, str]:
    identity = ContextPolicyIdentity("candidate-tiered-v1", "1.0.0")
    capability_id = "context.selection.candidate-tiered-v1"
    authority = ContextSelectionPolicyAuthority(capability_runtime=_runtime(identity))
    return authority, identity, capability_id


def _evidence(identity: ContextPolicyIdentity) -> ContextPolicyEvidence:
    now = datetime.now(tz=UTC)
    return ContextPolicyEvidence(
        evidence_id="window-1",
        policy=identity,
        window_start=now - timedelta(days=7),
        window_end=now,
        sample_count=100,
        invariant_failures=0,
    )


def test_install_disabled_then_promote_and_rollback() -> None:
    authority, identity, capability_id = _authority()
    baseline = authority.snapshot().active
    assert baseline is not None

    installed = authority.install(
        _CandidatePolicy(), capability_id=capability_id, expected_revision=0
    )
    assert installed.records[identity].state is ContextPolicyState.DISABLED
    shadow = authority.enable_shadow(identity, expected_revision=installed.revision)
    promoted = authority.promote(
        identity,
        evidence=_evidence(identity),
        rollback_to=baseline,
        expected_revision=shadow.revision,
    )
    assert promoted.active == identity

    rolled_back = authority.demote(
        identity,
        reason="answer-quality regression",
        expected_revision=promoted.revision,
    )
    assert rolled_back.active == baseline
    assert rolled_back.records[identity].state is ContextPolicyState.SHADOW


def test_concurrent_registry_update_is_rejected() -> None:
    authority, identity, capability_id = _authority()
    installed = authority.install(
        _CandidatePolicy(), capability_id=capability_id, expected_revision=0
    )

    with pytest.raises(ContextPolicyGovernanceError, match="changed concurrently"):
        authority.enable_shadow(identity, expected_revision=installed.revision - 1)


def test_invariant_violation_kills_candidate_and_rolls_back() -> None:
    authority, identity, capability_id = _authority()
    baseline = authority.snapshot().active
    assert baseline is not None

    class _InventingPolicy(_CandidatePolicy):
        def select(self, selection_input: ContextSelectionInput) -> ContextSelectionOutput:
            output = super().select(selection_input)
            return replace(
                output,
                selected_entry_ids=(*output.selected_entry_ids, "invented"),
                manifest=replace(
                    output.manifest,
                    verbatim_ids=(*output.manifest.verbatim_ids, "invented"),
                ),
            )

    installed = authority.install(
        _InventingPolicy(), capability_id=capability_id, expected_revision=0
    )
    shadow = authority.enable_shadow(identity, expected_revision=installed.revision)
    authority.promote(
        identity,
        evidence=_evidence(identity),
        rollback_to=baseline,
        expected_revision=shadow.revision,
    )
    entry = TranscriptEntry(
        entry_id="turn",
        role=EntryRole.OPERATOR,
        kind=EntryKind.VERBATIM,
        text="turn",
        tokens=1,
        sequence=0,
    )
    selection_input = ContextSelectionInput(
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

    with pytest.raises(Exception, match="invented_id"):
        authority.select(selection_input)

    snapshot = authority.snapshot()
    assert snapshot.active == baseline
    assert snapshot.records[identity].state is ContextPolicyState.KILLED
    assert snapshot.records[identity].kill_switch is True
