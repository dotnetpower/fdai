"""Offline deterministic replay over approved conversation fixtures."""

from __future__ import annotations

from dataclasses import dataclass

from fdai.core.working_context.selection import (
    ContextSelectionInput,
    ContextSelectionOutput,
    ContextSelectionPolicy,
)
from fdai.core.working_context.validation import execute_context_selection_policy


@dataclass(frozen=True, slots=True)
class ContextReplayFixture:
    fixture_id: str
    approved: bool
    selection_input: ContextSelectionInput
    expected_output: ContextSelectionOutput


@dataclass(frozen=True, slots=True)
class ContextReplayResult:
    fixture_id: str
    passed: bool
    failure_reason: str | None = None


def replay_approved_context_fixtures(
    *,
    policy: ContextSelectionPolicy,
    fixtures: tuple[ContextReplayFixture, ...],
) -> tuple[ContextReplayResult, ...]:
    """Replay approved fixtures only and report exact deterministic failures."""

    approved = tuple(fixture for fixture in fixtures if fixture.approved)
    if not approved:
        raise ValueError("at least one approved context replay fixture is required")
    results: list[ContextReplayResult] = []
    for fixture in approved:
        try:
            context = execute_context_selection_policy(
                policy=policy,
                selection_input=fixture.selection_input,
            )
            actual = ContextSelectionOutput(
                selected_entry_ids=tuple(entry.entry_id for entry in context.entries),
                manifest=context.manifest,
            )
            if actual != fixture.expected_output:
                results.append(
                    ContextReplayResult(
                        fixture_id=fixture.fixture_id,
                        passed=False,
                        failure_reason="output_mismatch",
                    )
                )
            else:
                results.append(ContextReplayResult(fixture_id=fixture.fixture_id, passed=True))
        except Exception as exc:
            results.append(
                ContextReplayResult(
                    fixture_id=fixture.fixture_id,
                    passed=False,
                    failure_reason=f"{type(exc).__name__}: {exc}",
                )
            )
    return tuple(results)


__all__ = [
    "ContextReplayFixture",
    "ContextReplayResult",
    "replay_approved_context_fixtures",
]
