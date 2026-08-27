from __future__ import annotations

from dataclasses import replace

import pytest
from fdai.core.conversation_assurance.quality_latency import (
    CHATOPS_LATENCY_CONTRACT_V1,
    LatencyBenchmarkBatch,
    LatencyEnvironment,
    LatencySample,
    LatencySampleOutcome,
    LatencyStage,
    LatencyStageReceipt,
    latency_sample_from_stage_receipt,
    reduce_latency_benchmark,
)
from fdai.core.conversation_assurance.quality_qualification import (
    QualificationEvidence,
)
from fdai.core.conversation_assurance.quality_scorecard import QualityHardCap


def _sample(
    stage: LatencyStage,
    index: int,
    *,
    duration_ms: float | None = None,
    outcome: LatencySampleOutcome = LatencySampleOutcome.COMPLETED,
) -> LatencySample:
    slo = CHATOPS_LATENCY_CONTRACT_V1.stages[tuple(LatencyStage).index(stage)]
    return LatencySample(
        stage=stage,
        environment=slo.environment,
        observed_at="2026-08-28T00:00:00Z",
        duration_ms=float(slo.p50_ceiling_ms if duration_ms is None else duration_ms),
        timestamp_authority="stage-owner-clock",
        trace_digest=f"{index:064x}",
        provenance_digest=f"{index + 10_000:064x}",
        outcome=outcome,
    )


def _batch() -> LatencyBenchmarkBatch:
    samples = tuple(
        _sample(slo.stage, index)
        for slo in CHATOPS_LATENCY_CONTRACT_V1.stages
        for index in range(slo.minimum_samples)
    )
    return LatencyBenchmarkBatch(
        run_id="latency-run-001",
        source_revision="a" * 40,
        started_at="2026-08-28T00:00:00Z",
        completed_at="2026-08-28T00:10:00Z",
        samples=samples,
    )


def test_contract_declares_five_stages_environments_floors_and_percentiles() -> None:
    contract = CHATOPS_LATENCY_CONTRACT_V1

    assert tuple(item.stage for item in contract.stages) == tuple(LatencyStage)
    assert {item.environment for item in contract.stages} == set(LatencyEnvironment)
    assert all(item.minimum_samples >= 30 for item in contract.stages)
    assert all(
        item.p50_ceiling_ms <= item.p95_ceiling_ms <= item.p99_ceiling_ms
        for item in contract.stages
    )
    assert len(contract.content_digest) == 64


def test_complete_batch_emits_content_free_p50_p95_p99_evidence() -> None:
    batch = _batch()
    evidence = reduce_latency_benchmark(batch)
    payload = evidence.to_dict()

    assert evidence.latency_slo_met is True
    assert [item.stage for item in evidence.stages] == list(LatencyStage)
    assert all(item.passed for item in evidence.stages)
    assert all(item.p50_ms is not None for item in evidence.stages)
    assert all(item.p95_ms is not None for item in evidence.stages)
    assert all(item.p99_ms is not None for item in evidence.stages)
    assert payload["qualification_authority"] is False
    assert payload["complete_trace_claimed"] is False
    assert len(payload["run_digest"]) == 64
    assert len(payload["sample_manifest_digest"]) == 64
    assert "latency-run-001" not in str(payload)
    assert "trace_digest" not in str(payload)
    assert "provenance_digest" not in str(payload)
    assert all(item.timestamp_authorities == ("stage-owner-clock",) for item in evidence.stages)
    assert (
        reduce_latency_benchmark(
            replace(batch, samples=tuple(reversed(batch.samples)))
        ).sample_manifest_digest
        == evidence.sample_manifest_digest
    )


def test_missing_stage_samples_and_timeout_fail_latency_slo() -> None:
    batch = _batch()
    retained = tuple(
        sample
        for sample in batch.samples
        if sample.stage is not LatencyStage.CHANNEL_ACKNOWLEDGEMENT
    )
    timed_out = replace(
        retained[0],
        outcome=LatencySampleOutcome.TIMED_OUT,
    )

    evidence = reduce_latency_benchmark(
        replace(batch, samples=(timed_out, *retained[1:])),
    )

    assert evidence.latency_slo_met is False
    assert "timed_out_samples=1" in evidence.stages[0].gaps
    acknowledgement = evidence.stages[3]
    assert acknowledgement.sample_count == 0
    assert acknowledgement.gaps == ("sample_count=0<minimum_samples=30",)


def test_percentile_regression_fails_its_stage() -> None:
    batch = _batch()
    delivery_slo = CHATOPS_LATENCY_CONTRACT_V1.stages[-1]
    samples = tuple(
        replace(
            sample,
            duration_ms=float(delivery_slo.p99_ceiling_ms + 1),
        )
        if sample.stage is LatencyStage.COMPLETE_DELIVERY
        else sample
        for sample in batch.samples
    )

    evidence = reduce_latency_benchmark(replace(batch, samples=samples))

    delivery = evidence.stages[-1]
    assert delivery.p99_ms == delivery_slo.p99_ceiling_ms + 1
    assert delivery.passed is False
    assert any(gap.startswith("p99_ms=") for gap in delivery.gaps)


def test_wrong_environment_and_duplicate_trace_fail_closed() -> None:
    batch = _batch()
    first = batch.samples[0]
    with pytest.raises(ValueError, match="wrong environment"):
        reduce_latency_benchmark(
            replace(
                batch,
                samples=(
                    replace(first, environment=LatencyEnvironment.RELEASE),
                    *batch.samples[1:],
                ),
            )
        )
    with pytest.raises(ValueError, match="unique by stage"):
        replace(batch, samples=(first, first))


def test_samples_require_typed_enums_and_benchmark_window() -> None:
    sample = _sample(LatencyStage.TIME_TO_FIRST_TOKEN, 1)
    with pytest.raises(ValueError, match="contract enums"):
        replace(sample, outcome="completed")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="benchmark window"):
        replace(
            _batch(),
            samples=(replace(sample, observed_at="2026-08-28T00:11:00Z"),),
        )


def test_stage_owner_receipt_derives_duration_and_enforces_environment() -> None:
    receipt = LatencyStageReceipt(
        stage=LatencyStage.DETERMINISTIC_VERIFICATION,
        environment=LatencyEnvironment.PR_REGRESSION,
        observed_at="2026-08-28T00:00:00Z",
        started_monotonic_ns=1_000_000_000,
        completed_monotonic_ns=1_125_500_000,
        timestamp_authority="verification-owner-clock",
        trace_digest="a" * 64,
        provenance_digest="b" * 64,
        outcome=LatencySampleOutcome.COMPLETED,
    )

    sample = latency_sample_from_stage_receipt(receipt)

    assert sample.duration_ms == 125.5
    with pytest.raises(ValueError, match="environment"):
        latency_sample_from_stage_receipt(
            replace(receipt, environment=LatencyEnvironment.LIVE_CANARY)
        )
    with pytest.raises(ValueError, match="MUST NOT precede"):
        replace(receipt, completed_monotonic_ns=receipt.started_monotonic_ns - 1)


def test_missing_slo_or_complete_trace_applies_existing_hard_cap() -> None:
    evidence = reduce_latency_benchmark(_batch())

    latency_only = QualificationEvidence(
        frozen_blind_corpus=True,
        production_e2e=True,
        latency_slo=evidence.latency_slo_met,
        complete_trace=False,
        critical_safety_escape=False,
    )
    missing_slo = replace(latency_only, latency_slo=False, complete_trace=True)

    assert latency_only.hard_caps(corpus_meets_floor=True) == (
        QualityHardCap.NO_LATENCY_SLO_OR_COMPLETE_TRACE,
    )
    assert missing_slo.hard_caps(corpus_meets_floor=True) == (
        QualityHardCap.NO_LATENCY_SLO_OR_COMPLETE_TRACE,
    )
