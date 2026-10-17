"""Real revision-source semantics, separate from learned prediction correctness."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import timedelta
from typing import Any

import pytest
from fdai.core.mscp_profile.response_outcome import response_outcome_audit_entry
from fdai.delivery.measurement.feedback_revision_source import PostgresFeedbackRevisionSource
from fdai.shared.contracts.models import ResponseOutcome
from tests.assurance_twin.test_feedback_rebuild import _AS_OF, _corrected
from tests.assurance_twin.test_feedback_reliability import _feedback


class _Source(PostgresFeedbackRevisionSource):
    def __init__(self, outcomes: tuple[ResponseOutcome, ...]) -> None:
        super().__init__(dsn="unused-local-fake", clock=lambda: _AS_OF)
        self.rows: list[Mapping[str, Any]] = [
            {"entry": response_outcome_audit_entry(item)} for item in outcomes
        ]

    async def _rows(self, revision_digests: tuple[str, ...]) -> Sequence[Mapping[str, Any]]:
        return self.rows


async def test_exact_replay_does_not_change_current_revision() -> None:
    outcome = _feedback(1)
    assert await _Source((outcome, outcome)).current((outcome.revision_digest,))


async def test_late_correction_withholds_old_model_and_accepts_complete_new_manifest() -> None:
    first = _feedback(1)
    corrected = _corrected(first)
    source = _Source((corrected, first))
    assert not await source.current((first.revision_digest,))
    assert await source.current((first.revision_digest, corrected.revision_digest))


@pytest.mark.parametrize("unknown", [False, True])
async def test_incomplete_predecessor_chain_is_not_current(unknown: bool) -> None:
    corrected = _corrected(_feedback(1), unknown=unknown)
    assert not await _Source((corrected,)).current((corrected.revision_digest,))


async def test_unknown_correction_is_current_evidence_not_a_success_label() -> None:
    first = _feedback(1)
    unknown = _corrected(first, unknown=True)
    assert await _Source((first, unknown)).current((first.revision_digest, unknown.revision_digest))
    assert not unknown.scorable


async def test_future_revision_withholds_past_head() -> None:
    first = _feedback(1)
    future = ResponseOutcome.model_validate(
        {
            **_corrected(first).model_dump(),
            "recorded_at": _AS_OF + timedelta(seconds=1),
        }
    )
    assert not await _Source((first, future)).current((first.revision_digest,))


async def test_missing_and_malformed_source_emit_explicit_diagnostics(
    caplog: pytest.LogCaptureFixture,
) -> None:
    first = _feedback(1)
    source = _Source(())
    assert not await source.current((first.revision_digest,))
    source.rows = [{"entry": {"schema_version": "9.0.0"}}]
    assert not await source.current((first.revision_digest,))
    assert {record.__dict__.get("reason") for record in caplog.records} == {
        "feedback_source_revision_missing",
        "feedback_source_invalid_outcome",
    }


async def test_bounded_history_cannot_be_misrepresented_as_complete() -> None:
    first = _feedback(1)
    source = _Source((first,))
    source.rows *= 1025
    assert not await source.current((first.revision_digest,))


@pytest.mark.parametrize("digests", [(), ("x",), ("a" * 64, "a" * 64), ("a" * 64,) * 1025])
async def test_invalid_manifest_is_an_explicit_error(digests: tuple[str, ...]) -> None:
    with pytest.raises(ValueError, match="bounded unique"):
        await _Source(()).current(digests)


async def test_source_io_failure_is_not_disguised_as_valid_or_empty_history() -> None:
    class Failed(_Source):
        async def _rows(self, revision_digests: tuple[str, ...]) -> Sequence[Mapping[str, Any]]:
            raise OSError("injected audit source failure")

    with pytest.raises(OSError, match="injected audit source failure"):
        await Failed(()).current((_feedback(1).revision_digest,))
