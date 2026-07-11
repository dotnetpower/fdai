"""Self-consistency sampler - stability reduction + sampling.

Design reference: ``docs/roadmap/hallucination-rubric-gate.md`` §
Self-consistency.
"""

from __future__ import annotations

import pytest

from fdai.core.quality_gate.gate import QualityCandidate
from fdai.core.quality_gate.self_consistency import (
    STABILITY_SIGNAL_KEY,
    CascadeDecision,
    SelfConsistencySampler,
    compute_stability,
    run_consistency_cascade,
)
from fdai.core.quality_gate.testing import SequenceCrossCheckModel


def _candidate() -> QualityCandidate:
    return QualityCandidate(
        action_type="remediate.tag-add",
        target_resource_ref="rid-1",
        params={},
        cited_rule_ids=("r.known",),
    )


class TestComputeStability:
    def test_uniform_is_full_stability(self) -> None:
        modal, count, stability = compute_stability(["a", "a", "a"])
        assert modal == "a"
        assert count == 3
        assert stability == pytest.approx(1.0)

    def test_majority(self) -> None:
        modal, count, stability = compute_stability(["a", "a", "b"])
        assert modal == "a"
        assert count == 2
        assert stability == pytest.approx(2 / 3)

    def test_all_distinct_is_low(self) -> None:
        modal, count, stability = compute_stability(["a", "b", "c"])
        assert count == 1
        assert stability == pytest.approx(1 / 3)

    def test_tie_breaks_on_first_seen(self) -> None:
        # a and b both appear twice; first-seen (a) wins for determinism.
        modal, count, stability = compute_stability(["a", "b", "a", "b"])
        assert modal == "a"
        assert count == 2

    def test_empty_raises(self) -> None:
        with pytest.raises(ValueError, match="at least one"):
            compute_stability([])


class TestSelfConsistencySampler:
    def test_rejects_zero_samples(self) -> None:
        with pytest.raises(ValueError, match="samples MUST be"):
            SelfConsistencySampler(proposer=SequenceCrossCheckModel(sequence=("a",)), samples=0)

    @pytest.mark.asyncio
    async def test_stable_proposer(self) -> None:
        sampler = SelfConsistencySampler(
            proposer=SequenceCrossCheckModel(sequence=("remediate.tag-add",)), samples=4
        )
        result = await sampler.sample(_candidate())
        assert result.total == 4
        assert result.stability == pytest.approx(1.0)
        assert result.modal_action_type == "remediate.tag-add"
        assert result.signal == {STABILITY_SIGNAL_KEY: 1.0}

    @pytest.mark.asyncio
    async def test_unstable_proposer_lowers_stability(self) -> None:
        sampler = SelfConsistencySampler(
            proposer=SequenceCrossCheckModel(sequence=("a", "b", "a", "c")), samples=4
        )
        result = await sampler.sample(_candidate())
        assert result.total == 4
        assert result.modal_action_type == "a"
        assert result.agreement_count == 2
        assert result.stability == pytest.approx(0.5)
        assert result.signal[STABILITY_SIGNAL_KEY] == pytest.approx(0.5)

    @pytest.mark.asyncio
    async def test_proposer_failure_propagates(self) -> None:
        class _RaisingProposer:
            async def propose(self, candidate: QualityCandidate) -> tuple[str, dict[str, object]]:
                del candidate
                raise RuntimeError("proposer offline")

        sampler = SelfConsistencySampler(proposer=_RaisingProposer(), samples=3)
        with pytest.raises(RuntimeError, match="proposer offline"):
            await sampler.sample(_candidate())

    @pytest.mark.asyncio
    async def test_sibling_samples_cancelled_on_failure(self) -> None:
        # One sample raises immediately; the siblings would hang. The
        # sampler MUST cancel the in-flight siblings before propagating,
        # so this returns promptly (no 30s wait) and leaks no task.
        import asyncio

        started: list[asyncio.Task[object]] = []

        class _OneRaisesRestHang:
            def __init__(self) -> None:
                self.calls = 0

            async def propose(self, candidate: QualityCandidate) -> tuple[str, dict[str, object]]:
                del candidate
                self.calls += 1
                if self.calls == 1:
                    raise RuntimeError("boom")
                current = asyncio.current_task()
                if current is not None:
                    started.append(current)
                await asyncio.sleep(30)  # would hang unless cancelled
                return ("x", {})

        sampler = SelfConsistencySampler(proposer=_OneRaisesRestHang(), samples=3)
        with pytest.raises(RuntimeError, match="boom"):
            await sampler.sample(_candidate())
        # Give the event loop a tick to process the cancellations.
        await asyncio.sleep(0)
        assert all(t.cancelled() or t.done() for t in started)


class TestCascade:
    @pytest.mark.asyncio
    async def test_strong_signal_skips_sampling(self) -> None:
        sampler = SelfConsistencySampler(
            proposer=SequenceCrossCheckModel(sequence=("a",)), samples=3
        )
        decision = await run_consistency_cascade(
            sampler,
            _candidate(),
            aggregate_confidence=0.9,
            sample_threshold=0.7,
            stability_threshold=0.6,
        )
        assert decision == CascadeDecision(should_sample=False, stable=None, result=None)

    @pytest.mark.asyncio
    async def test_weak_signal_stable(self) -> None:
        sampler = SelfConsistencySampler(
            proposer=SequenceCrossCheckModel(sequence=("a",)), samples=4
        )
        decision = await run_consistency_cascade(
            sampler,
            _candidate(),
            aggregate_confidence=0.4,
            sample_threshold=0.7,
            stability_threshold=0.6,
        )
        assert decision.should_sample is True
        assert decision.stable is True
        assert decision.result is not None
        assert decision.result.stability == pytest.approx(1.0)

    @pytest.mark.asyncio
    async def test_weak_signal_unstable_is_gate_not_dilution(self) -> None:
        # Unstable proposer under a weak cheap signal -> stable is False.
        # The caller routes that to HIL; the low stability is NOT averaged
        # into confidence where a high signal could mask it.
        sampler = SelfConsistencySampler(
            proposer=SequenceCrossCheckModel(sequence=("a", "b", "c", "d")), samples=4
        )
        decision = await run_consistency_cascade(
            sampler,
            _candidate(),
            aggregate_confidence=0.4,
            sample_threshold=0.7,
            stability_threshold=0.6,
        )
        assert decision.should_sample is True
        assert decision.stable is False
        assert decision.result is not None
        assert decision.result.stability == pytest.approx(0.25)
