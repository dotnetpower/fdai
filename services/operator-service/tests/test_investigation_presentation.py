"""Readable deterministic presentation for competing causal evidence."""

from __future__ import annotations

from typing import cast

import pytest
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
        {"label": "Target", "value": "service:a", "tone": "neutral"},
        {"label": "Symptom", "value": "service.latency", "tone": "neutral"},
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


@pytest.mark.parametrize("hypothesis_count", [0, 1])
def test_incomplete_competing_hypotheses_remain_an_explicit_limitation(
    hypothesis_count: int,
) -> None:
    outputs = _outputs()[: 1 + hypothesis_count]

    blocks = _general_query_blocks(
        outputs,
        bounded_refs=["evidence:1"],
        korean=False,
    )

    assert [block["slot_id"] for block in blocks] == [
        "overview",
        "hypotheses",
        "limitations",
    ]
    table = cast(dict[str, object], blocks[1]["data"])
    assert len(cast(list[dict[str, object]], table["rows"])) == hypothesis_count
    limitation = cast(dict[str, object], blocks[2]["data"])
    assert limitation["lines"] == ["Fewer than two verified causal hypotheses were available."]


def test_korean_incomplete_competing_hypotheses_remain_an_explicit_limitation() -> None:
    blocks = _general_query_blocks(
        _outputs()[:1],
        bounded_refs=["evidence:1"],
        korean=True,
    )

    limitation = cast(dict[str, object], blocks[2]["data"])
    assert limitation["lines"] == ["검증된 인과 가설이 두 개 미만입니다."]


def test_unrelated_metric_comparison_cannot_replace_the_symptom() -> None:
    unrelated = {
        "node_id": "dependency-change",
        "result_kind": "metric.comparison",
        "summary": {
            "concept_id": "dependency.latency",
            "resource_id": "dependency:a",
            "unit": "ms",
            "baseline_value": 1.0,
            "current_value": 2.0,
            "absolute_change": 1.0,
            "execution_authority": False,
        },
    }

    blocks = _general_query_blocks(
        [*_outputs(), unrelated],
        bounded_refs=["evidence:1"],
        korean=False,
    )

    overview = cast(dict[str, object], blocks[0]["data"])
    assert overview["items"][:2] == [
        {"label": "Target", "value": "service:a", "tone": "neutral"},
        {"label": "Symptom", "value": "service.latency", "tone": "neutral"},
    ]
