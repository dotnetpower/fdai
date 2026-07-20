"""Adversarial invariant tests for context-selection policy output."""

from __future__ import annotations

import json
from dataclasses import asdict, replace
from pathlib import Path

import pytest

from fdai.core.working_context import (
    DEFAULT_CONTEXT_SELECTION_POLICY,
    ContextBudget,
    ContextReplayFixture,
    ContextSelectionInput,
    ContextSelectionInvariantError,
    ContextSelectionOutput,
    ContextTrustClass,
    EntryKind,
    EntryRole,
    ModelCapabilityMetadata,
    TranscriptEntry,
    compose_working_context,
    execute_context_selection_policy,
    replay_approved_context_fixtures,
)
from fdai.core.working_context.composer import _compose_deterministic

_FIXTURES = Path(__file__).with_name("fixtures")


def _entry(
    entry_id: str,
    *,
    tokens: int = 10,
    sequence: int = 0,
    kind: EntryKind = EntryKind.VERBATIM,
    pinned: bool = False,
    level: int = 0,
) -> TranscriptEntry:
    return TranscriptEntry(
        entry_id=entry_id,
        role=EntryRole.OPERATOR,
        kind=kind,
        text=entry_id,
        tokens=tokens,
        sequence=sequence,
        pinned=pinned,
        level=level,
    )


def _input(entries: tuple[TranscriptEntry, ...], history: int = 100) -> ContextSelectionInput:
    return ContextSelectionInput(
        entries=entries,
        trust_classes={entry.entry_id: ContextTrustClass.UNTRUSTED_EXTERNAL for entry in entries},
        budget=ContextBudget(
            total_window=history + 1,
            base_reserve=0,
            output_reserve=1,
            tools_reserve=0,
            memory_reserve=0,
            verbatim_ratio=1.0,
            retrieval_ratio=0.0,
            summary_ratio=0.0,
            typed_fact_ratio=0.0,
        ),
        model=ModelCapabilityMetadata(model_id="fixture", context_window=history + 1),
    )


class _StaticPolicy:
    policy_id = "malicious-policy"
    policy_version = "1.0.0"

    def __init__(self, output: ContextSelectionOutput) -> None:
        self.output = output

    def select(self, selection_input: ContextSelectionInput) -> ContextSelectionOutput:
        del selection_input
        return self.output


def test_drop_pinned_is_rejected() -> None:
    selection_input = _input((_entry("pin", pinned=True), _entry("turn", sequence=1)))
    output = DEFAULT_CONTEXT_SELECTION_POLICY.select(
        replace(
            selection_input,
            entries=(selection_input.entries[1],),
            trust_classes={"turn": ContextTrustClass.UNTRUSTED_EXTERNAL},
        )
    )

    with pytest.raises(ContextSelectionInvariantError) as caught:
        execute_context_selection_policy(
            policy=_StaticPolicy(output),
            selection_input=selection_input,
        )

    assert caught.value.code == "pinned_constraint"


def test_invented_id_is_rejected() -> None:
    selection_input = _input((_entry("turn"),))
    baseline = DEFAULT_CONTEXT_SELECTION_POLICY.select(selection_input)
    malicious = replace(
        baseline,
        selected_entry_ids=(*baseline.selected_entry_ids, "invented"),
        manifest=replace(
            baseline.manifest,
            verbatim_ids=(*baseline.manifest.verbatim_ids, "invented"),
        ),
    )

    with pytest.raises(ContextSelectionInvariantError) as caught:
        execute_context_selection_policy(
            policy=_StaticPolicy(malicious),
            selection_input=selection_input,
        )

    assert caught.value.code == "invented_id"


def test_duplicate_id_is_rejected() -> None:
    selection_input = _input((_entry("turn"),))
    baseline = DEFAULT_CONTEXT_SELECTION_POLICY.select(selection_input)
    malicious = replace(
        baseline,
        selected_entry_ids=(*baseline.selected_entry_ids, "turn"),
    )

    with pytest.raises(ContextSelectionInvariantError) as caught:
        execute_context_selection_policy(
            policy=_StaticPolicy(malicious),
            selection_input=selection_input,
        )

    assert caught.value.code == "duplicate_id"


def test_budget_overflow_is_rejected() -> None:
    entry = _entry("large", tokens=60)
    selection_input = _input((entry,), history=50)
    baseline = DEFAULT_CONTEXT_SELECTION_POLICY.select(selection_input)
    malicious = ContextSelectionOutput(
        selected_entry_ids=(entry.entry_id,),
        manifest=replace(
            baseline.manifest,
            verbatim_ids=(entry.entry_id,),
            verbatim_tokens=entry.tokens,
            dropped_ids=(),
        ),
    )

    with pytest.raises(ContextSelectionInvariantError) as caught:
        execute_context_selection_policy(
            policy=_StaticPolicy(malicious),
            selection_input=selection_input,
        )

    assert caught.value.code == "budget_overflow"


def test_trust_order_reversal_is_rejected() -> None:
    selection_input = _input(
        (
            _entry("pin", pinned=True),
            _entry("turn", sequence=1),
        )
    )
    baseline = DEFAULT_CONTEXT_SELECTION_POLICY.select(selection_input)
    malicious = replace(baseline, selected_entry_ids=tuple(reversed(baseline.selected_entry_ids)))

    with pytest.raises(ContextSelectionInvariantError) as caught:
        execute_context_selection_policy(
            policy=_StaticPolicy(malicious),
            selection_input=selection_input,
        )

    assert caught.value.code == "invalid_trust_order"


def test_nondeterministic_policy_is_rejected() -> None:
    selection_input = _input((_entry("turn"),))
    baseline = DEFAULT_CONTEXT_SELECTION_POLICY.select(selection_input)

    class _NondeterministicPolicy(_StaticPolicy):
        def __init__(self) -> None:
            super().__init__(baseline)
            self.calls = 0

        def select(self, selection_input: ContextSelectionInput) -> ContextSelectionOutput:
            del selection_input
            self.calls += 1
            if self.calls == 1:
                return self.output
            return replace(self.output, selected_entry_ids=())

    with pytest.raises(ContextSelectionInvariantError) as caught:
        execute_context_selection_policy(
            policy=_NondeterministicPolicy(),
            selection_input=selection_input,
        )

    assert caught.value.code == "nondeterministic_output"


def test_policy_exception_fails_closed() -> None:
    class _ExceptionPolicy(_StaticPolicy):
        def select(self, selection_input: ContextSelectionInput) -> ContextSelectionOutput:
            raise RuntimeError("candidate exploded")

    selection_input = _input((_entry("turn"),))
    output = DEFAULT_CONTEXT_SELECTION_POLICY.select(selection_input)

    with pytest.raises(RuntimeError, match="candidate exploded"):
        execute_context_selection_policy(
            policy=_ExceptionPolicy(output),
            selection_input=selection_input,
        )


def test_approved_fixture_replay_is_byte_stable() -> None:
    payload = json.loads((_FIXTURES / "approved-conversation.json").read_text(encoding="utf-8"))
    entries = tuple(
        _entry(
            item["entry_id"],
            tokens=item["tokens"],
            sequence=item["sequence"],
            pinned=item["pinned"],
        )
        for item in payload["entries"]
    )
    selection_input = _input(entries, history=payload["history_budget"])
    expected = DEFAULT_CONTEXT_SELECTION_POLICY.select(selection_input)
    results = replay_approved_context_fixtures(
        policy=DEFAULT_CONTEXT_SELECTION_POLICY,
        fixtures=(
            ContextReplayFixture(
                payload["fixture_id"], payload["approved"], selection_input, expected
            ),
            ContextReplayFixture("draft", False, selection_input, expected),
        ),
    )

    assert len(results) == 1
    assert expected.selected_entry_ids == tuple(payload["expected_selected_ids"])
    assert results[0].fixture_id == "approved-conversation-1"
    assert results[0].passed is True
    assert results[0].failure_reason is None


def test_default_wrapper_preserves_canonical_output_bytes() -> None:
    entries = (_entry("pin", pinned=True), _entry("turn", sequence=1))
    budget = _input(entries).budget

    legacy = _compose_deterministic(budget=budget, entries=entries)
    wrapped = compose_working_context(budget=budget, entries=entries)

    legacy_bytes = json.dumps(asdict(legacy), sort_keys=True, separators=(",", ":"))
    wrapped_bytes = json.dumps(asdict(wrapped), sort_keys=True, separators=(",", ":"))
    assert wrapped_bytes == legacy_bytes
