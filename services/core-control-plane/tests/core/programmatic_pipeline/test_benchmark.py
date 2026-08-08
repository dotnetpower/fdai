from __future__ import annotations

from fdai.core.programmatic_pipeline import benchmark_programmatic_pipeline


def test_programmatic_pipeline_benchmark_beats_sequential_model_calls() -> None:
    sequential_turns = tuple(
        {
            "call": index,
            "model_context": "inventory-result:" + "x" * 500,
            "intermediate": {"accepted": index % 2 == 0},
        }
        for index in range(20)
    )
    compact = {
        "status": "succeeded",
        "complete": True,
        "final": {"accepted": 10, "total": 20},
        "receipt_refs": [f"pipeline-call:benchmark:{index}" for index in range(20)],
    }

    benchmark = benchmark_programmatic_pipeline(
        sequential_turns=sequential_turns,
        compact_projection=compact,
        model_roundtrip_ms=250,
        broker_roundtrip_ms=10,
    )

    assert benchmark.tool_calls == 20
    assert benchmark.context_reduction_ratio > 0.9
    assert benchmark.latency_reduction_ratio > 0.8
