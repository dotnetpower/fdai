"""Mandatory fail-closed validation for context-selection policy output."""

from __future__ import annotations

from collections.abc import Sequence
from typing import NoReturn

from fdai.core.working_context.selection import (
    ContextSelectionInput,
    ContextSelectionOutput,
    ContextSelectionPolicy,
    ContextTrustClass,
)
from fdai.core.working_context.types import EntryKind, TranscriptEntry, WorkingContext

_GROUP_ORDER: dict[EntryKind, int] = {
    EntryKind.SUMMARY: 1,
    EntryKind.RETRIEVED: 2,
    EntryKind.TYPED_FACT: 3,
    EntryKind.VERBATIM: 4,
}


class ContextSelectionInvariantError(RuntimeError):
    """A policy output cannot be reconstructed or trusted."""

    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        super().__init__(f"context selection invariant {code}: {detail}")


def validate_context_selection(
    *,
    selection_input: ContextSelectionInput,
    output: ContextSelectionOutput,
    replay_output: ContextSelectionOutput,
) -> WorkingContext:
    """Validate a policy result and reconstruct the selected immutable entries."""

    if output != replay_output:
        _fail("nondeterministic_output", "identical immutable input produced different output")

    selected_ids = output.selected_entry_ids
    if len(selected_ids) != len(set(selected_ids)):
        _fail("duplicate_id", "selected_entry_ids contains duplicates")

    known_ids = {entry.entry_id for entry in selection_input.entries}
    invented = tuple(entry_id for entry_id in selected_ids if entry_id not in known_ids)
    if invented:
        _fail("invented_id", f"unknown selected ids={invented}")

    manifest = output.manifest
    grouped_ids = (
        manifest.pinned_ids
        + manifest.summary_ids
        + manifest.retrieved_ids
        + manifest.typed_fact_ids
        + manifest.verbatim_ids
    )
    if len(grouped_ids) != len(set(grouped_ids)):
        _fail("duplicate_id", "manifest assigns an id more than once")
    if set(grouped_ids) != set(selected_ids):
        _fail("incomplete_manifest", "manifest ids do not equal selected_entry_ids")

    pinned_ids = tuple(entry.entry_id for entry in selection_input.entries if entry.pinned)
    if manifest.pinned_ids != pinned_ids:
        _fail("pinned_constraint", "all pinned ids must be preserved in input order")

    selected = tuple(
        _resolve_entry(entry_id, selection_input.entries, output) for entry_id in selected_ids
    )
    _validate_trust_classes(selection_input, selected)
    expected_order = tuple(sorted(selected, key=_prompt_order))
    if selected != expected_order:
        _fail("invalid_trust_order", "selected ids do not follow authoritative prompt ordering")

    expected_dropped = tuple(
        entry.entry_id
        for entry in selection_input.entries
        if entry.entry_id not in set(selected_ids)
    )
    if manifest.dropped_ids != expected_dropped:
        _fail("incomplete_manifest", "dropped_ids does not describe every omitted input")

    _validate_token_totals(selected, output)
    if manifest.total_tokens > selection_input.budget.history_budget:
        _fail(
            "budget_overflow",
            f"selected={manifest.total_tokens}, budget={selection_input.budget.history_budget}",
        )
    return WorkingContext(entries=selected, manifest=manifest)


def execute_context_selection_policy(
    *,
    policy: ContextSelectionPolicy,
    selection_input: ContextSelectionInput,
) -> WorkingContext:
    """Run one policy with mandatory deterministic replay validation."""

    first = policy.select(selection_input)
    replay = policy.select(selection_input)
    return validate_context_selection(
        selection_input=selection_input,
        output=first,
        replay_output=replay,
    )


def _resolve_entry(
    entry_id: str,
    entries: Sequence[TranscriptEntry],
    output: ContextSelectionOutput,
) -> TranscriptEntry:
    manifest = output.manifest
    if entry_id in manifest.pinned_ids:
        matches = [entry for entry in entries if entry.entry_id == entry_id and entry.pinned]
    else:
        expected_kind = _manifest_kind(entry_id, output)
        matches = [
            entry
            for entry in entries
            if entry.entry_id == entry_id and not entry.pinned and entry.kind is expected_kind
        ]
    if len(matches) != 1:
        _fail("unreplayable_output", f"selected id {entry_id!r} resolves to {len(matches)} entries")
    return matches[0]


def _manifest_kind(entry_id: str, output: ContextSelectionOutput) -> EntryKind:
    manifest = output.manifest
    by_kind = (
        (manifest.summary_ids, EntryKind.SUMMARY),
        (manifest.retrieved_ids, EntryKind.RETRIEVED),
        (manifest.typed_fact_ids, EntryKind.TYPED_FACT),
        (manifest.verbatim_ids, EntryKind.VERBATIM),
    )
    for ids, kind in by_kind:
        if entry_id in ids:
            return kind
    _fail("incomplete_manifest", f"selected id {entry_id!r} has no manifest tier")


def _validate_trust_classes(
    selection_input: ContextSelectionInput,
    selected: Sequence[TranscriptEntry],
) -> None:
    for entry in selected:
        expected = (
            ContextTrustClass.TRUSTED_INTERNAL
            if entry.trusted
            else ContextTrustClass.UNTRUSTED_EXTERNAL
        )
        if selection_input.trust_classes[entry.entry_id] is not expected:
            _fail("invalid_trust_order", f"trust class changed for {entry.entry_id!r}")


def _validate_token_totals(
    selected: Sequence[TranscriptEntry],
    output: ContextSelectionOutput,
) -> None:
    manifest = output.manifest
    expected = {
        "pinned_tokens": sum(entry.tokens for entry in selected if entry.pinned),
        "summary_tokens": sum(
            entry.tokens
            for entry in selected
            if not entry.pinned and entry.kind is EntryKind.SUMMARY
        ),
        "retrieved_tokens": sum(
            entry.tokens
            for entry in selected
            if not entry.pinned and entry.kind is EntryKind.RETRIEVED
        ),
        "typed_fact_tokens": sum(
            entry.tokens
            for entry in selected
            if not entry.pinned and entry.kind is EntryKind.TYPED_FACT
        ),
        "verbatim_tokens": sum(
            entry.tokens
            for entry in selected
            if not entry.pinned and entry.kind is EntryKind.VERBATIM
        ),
    }
    for field_name, token_count in expected.items():
        if getattr(manifest, field_name) != token_count:
            _fail("incomplete_manifest", f"{field_name} does not match selected entries")


def _prompt_order(entry: TranscriptEntry) -> tuple[int, int]:
    return (0 if entry.pinned else _GROUP_ORDER[entry.kind], entry.sequence)


def _fail(code: str, detail: str) -> NoReturn:
    raise ContextSelectionInvariantError(code, detail)


__all__ = [
    "ContextSelectionInvariantError",
    "execute_context_selection_policy",
    "validate_context_selection",
]
