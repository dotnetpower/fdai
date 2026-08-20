"""Readable deterministic presentation for competing causal evidence."""

from __future__ import annotations

from typing import cast

from fdai_operator_service.families.conversation.semantic_turn_presentation import (
    _general_query_blocks,
)


def _outputs() -> list[object]:
    return [
        {
            "node_id": "symptom-change",
            "result_kind": "metric.comparison",
            "summary": {
                "concept_id": "service.latency",
                "resource_id": "service:a",
                "unit": "ms",
                "baseline_value": 15.0,
                "current_value": 40.0,
                "absolute_change": 25.0,
                "relative_change": 1.6667,
                "complete": True,
                "reason": None,
                "execution_authority": False,
            },
        },
        {
            "node_id": "hypothesis-dependency-latency",
            "result_kind": "causal.join",
            "summary": {
                "hypothesis_id": "dependency-latency",
                "status": "supported",
                "limitations": [],
                "temporal_claim": {
                    "cause_metric": "dependency.latency",
                    "lag_seconds": 60,
                    "correlation": 0.81,
                },
                "execution_authority": False,
            },
        },
        {
            "node_id": "hypothesis-resource-saturation",
            "result_kind": "causal.join",
            "summary": {
                "hypothesis_id": "resource-saturation",
                "status": "refuted",
                "limitations": ["reverse_direction_stronger"],
                "temporal_claim": {
                    "cause_metric": "resource.saturation",
                    "lag_seconds": 0,
                    "correlation": 0.12,
                },
                "execution_authority": False,
            },
        },
    ]


def test_verified_investigation_renders_symptom_and_competing_hypotheses() -> None:
    blocks = _general_query_blocks(
        _outputs(),
        bounded_refs=["evidence:1"],
        korean=False,
    )

    assert [block["slot_id"] for block in blocks] == [
        "overview",
        "hypotheses",
        "limitations",
    ]
    overview = cast(dict[str, object], blocks[0]["data"])
    assert overview["items"] == [
        {"label": "Baseline", "value": "15 ms", "tone": "neutral"},
        {"label": "Current", "value": "40 ms", "tone": "neutral"},
        {"label": "Observed change", "value": "25 ms", "tone": "attention"},
    ]
    table = cast(dict[str, object], blocks[1]["data"])
    rows = cast(list[dict[str, object]], table["rows"])
    assert rows[0] == {
        "hypothesis": "dependency latency",
        "status": "supported",
        "cause": "dependency.latency",
        "lag": "60 s",
        "correlation": "0.81",
        "limitations": "-",
    }
    assert rows[1]["status"] == "refuted"


def test_korean_investigation_keeps_the_same_block_contract() -> None:
    blocks = _general_query_blocks(
        _outputs(),
        bounded_refs=["evidence:1"],
        korean=True,
    )

    assert [block["title"] for block in blocks] == [
        "증상 변화",
        "경쟁 원인 가설",
        "제한 사항",
    ]
