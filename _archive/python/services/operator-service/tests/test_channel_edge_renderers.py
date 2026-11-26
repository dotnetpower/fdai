"""Provider rendering parity and fail-closed artifact tests."""

from __future__ import annotations

import copy
import json

import pytest
from fdai_operator_service.families.conversation.channel_edge.presentation import (
    normalize_terminal_presentation,
    serialized_size,
)
from fdai_operator_service.families.conversation.channel_edge.renderers import (
    SLACK_CAPABILITIES,
    TEAMS_CAPABILITIES,
    SlackPresentationRenderer,
    TeamsPresentationRenderer,
)
from fdai_service_contracts import AdaptiveAnswer

_REF = "ontology-function:verified-output"


def _artifact() -> dict[str, object]:
    return {
        "schema_version": 2,
        "layout": "stack",
        "evidence_refs": [_REF],
        "blocks": [
            {
                "slot_id": "trend",
                "kind": "time_series",
                "title": "Request trend",
                "emphasis": "primary",
                "collapsed": False,
                "evidence_refs": [_REF],
                "data": {
                    "description": "Ordered observations for requests.",
                    "metric": "requests",
                    "unit": "count",
                    "points": [
                        {"timestamp": "2026-08-19T00:00:00Z", "value": 1},
                        {"timestamp": "2026-08-19T00:01:00Z", "value": 3},
                        {"timestamp": "2026-08-19T00:02:00Z", "value": 2},
                    ],
                    "exact_table": {
                        "columns": [
                            {"key": "c0", "label": "timestamp"},
                            {"key": "c1", "label": "value"},
                        ],
                        "rows": [
                            {"c0": "2026-08-19T00:00:00Z", "c1": "1"},
                            {"c0": "2026-08-19T00:01:00Z", "c1": "3"},
                            {"c0": "2026-08-19T00:02:00Z", "c1": "2"},
                        ],
                        "status_key": None,
                    },
                },
            },
            {
                "slot_id": "limitations",
                "kind": "callout",
                "title": "Limitations",
                "emphasis": "supporting",
                "collapsed": False,
                "evidence_refs": [_REF],
                "data": {"tone": "warning", "lines": ["One source is unavailable."]},
            },
        ],
    }


def _terminal(artifact: object | None = None) -> dict[str, object]:
    result: dict[str, object] = {
        "status": "answered",
        "answer": "Requests were 1, 3, and 2 at the three verified timestamps.",
        "verification": {
            "authority": "ontology-query",
            "evidence_refs": [_REF],
        },
    }
    if artifact is not None:
        result["presentation_artifact"] = artifact
    return result


def test_slack_and_teams_preserve_exact_facts_and_mandatory_context() -> None:
    envelope = normalize_terminal_presentation(_terminal(_artifact()), web_url="/deck")
    slack = SlackPresentationRenderer().render(envelope)
    teams = TeamsPresentationRenderer().render(envelope)

    assert envelope.artifact_version == 2
    assert [fact.value for fact in envelope.sections[0].facts] == ["1", "3", "2"]
    assert slack.fallback_text == teams.fallback_text
    for required in (
        envelope.canonical_text,
        "One source is unavailable.",
        _REF,
        "Authority: ontology-query",
        "Execution authority: none",
    ):
        assert required in slack.fallback_text
    assert serialized_size(slack.body) <= SLACK_CAPABILITIES.max_serialized_bytes
    assert serialized_size(teams.body) <= TEAMS_CAPABILITIES.max_serialized_bytes


def test_direct_response_is_available_without_invented_evidence_authority() -> None:
    envelope = normalize_terminal_presentation(
        {
            "status": "direct_response",
            "answer": "Hello. What would you like to inspect?",
        }
    )

    assert envelope.unavailable is False
    assert envelope.evidence_refs == ()
    assert envelope.authority == "no_execution_authority"


@pytest.mark.parametrize(
    ("locale", "knowledge", "example"),
    [("en", "General knowledge", "Environment example"), ("ko", "일반 지식", "현재 환경의 예시")],
)
def test_advisory_channel_renderers_preserve_goal_local_support(
    locale: str, knowledge: str, example: str
) -> None:
    adaptive = AdaptiveAnswer.model_validate(
        {
            "answer": "An SLO is a measurable service objective.",
            "goals": [
                {"goal_id": "concept", "kind": "knowledge", "status": "answered", "required": True},
                {
                    "goal_id": "example",
                    "kind": "environment_example",
                    "status": "answered",
                    "required": False,
                    "evidence_refs": [_REF],
                },
            ],
            "role_agent": "Mimir",
            "quality_status": "passed",
        }
    )
    terminal = {
        "status": "advisory_response",
        "source": "semantic-advisory-response",
        "answer": adaptive.answer,
        "adaptive_answer": adaptive.model_dump(mode="json"),
        "execution_authority": False,
        "locale": locale,
    }
    envelope = normalize_terminal_presentation(terminal)
    assert envelope.adaptive_answer == adaptive
    assert envelope.unavailable is False
    assert envelope.evidence_refs == ()
    for renderer in (SlackPresentationRenderer(), TeamsPresentationRenderer()):
        rendered = renderer.render(envelope)
        assert knowledge in rendered.fallback_text
        assert example in rendered.fallback_text
        assert _REF in rendered.fallback_text
        assert "Evidence:\n- none recorded" not in rendered.fallback_text
        assert "Availability: unavailable" not in rendered.fallback_text
    with pytest.raises(ValueError, match="goal-local"):
        normalize_terminal_presentation({**terminal, "verification": {}})


def test_malformed_artifact_degrades_to_canonical_text_without_leaking_shape() -> None:
    malformed = copy.deepcopy(_artifact())
    blocks = malformed["blocks"]
    assert isinstance(blocks, list) and isinstance(blocks[0], dict)
    blocks[0]["kind"] = "html"

    envelope = normalize_terminal_presentation(_terminal(malformed))
    payload = SlackPresentationRenderer().render(envelope)

    assert envelope.artifact_version is None
    assert envelope.sections == ()
    assert payload.degraded_to_text is True
    assert envelope.canonical_text in payload.fallback_text
    assert "html" not in json.dumps(payload.body)


def test_terminal_cannot_grant_execution_authority() -> None:
    terminal = _terminal()
    terminal["execution_authority"] = True

    try:
        normalize_terminal_presentation(terminal)
    except ValueError as exc:
        assert "deny execution authority" in str(exc)
    else:
        raise AssertionError("authority-bearing terminal data was accepted")


def test_channel_normalizes_scatter_and_heatmap_to_exact_facts() -> None:
    exact_table = {
        "columns": [{"key": "value", "label": "Value"}],
        "rows": [{"value": "1"}],
        "status_key": None,
    }
    artifact = _artifact()
    artifact["blocks"] = [
        {
            "slot_id": "correlation",
            "kind": "scatter",
            "title": "Correlation",
            "emphasis": "primary",
            "collapsed": False,
            "evidence_refs": [_REF],
            "data": {
                "description": "Latency and errors.",
                "x_label": "latency",
                "y_label": "errors",
                "points": [
                    {"label": "api", "x": 1, "y": 2},
                    {"label": "worker", "x": 2, "y": 4},
                ],
                "exact_table": exact_table,
            },
        },
        {
            "slot_id": "matrix",
            "kind": "heatmap",
            "title": "Matrix",
            "emphasis": "primary",
            "collapsed": False,
            "evidence_refs": [_REF],
            "data": {
                "description": "Service and region values.",
                "row_label": "service",
                "column_label": "region",
                "cells": [
                    {"row": "api", "column": "east", "value": 1},
                    {"row": "api", "column": "west", "value": 2},
                ],
                "exact_table": exact_table,
            },
        },
    ]

    envelope = normalize_terminal_presentation(_terminal(artifact))

    assert envelope.artifact_version == 2
    assert [fact.value for fact in envelope.sections[0].facts] == ["x=1, y=2", "x=2, y=4"]
    assert [fact.label for fact in envelope.sections[1].facts] == ["api / east", "api / west"]


def test_channel_rejects_visualization_outside_the_kind_allowlist() -> None:
    artifact = _artifact()
    blocks = artifact["blocks"]
    assert isinstance(blocks, list) and isinstance(blocks[0], dict)
    data = blocks[0]["data"]
    assert isinstance(data, dict)
    data["visualization"] = "donut"

    envelope = normalize_terminal_presentation(_terminal(artifact))

    assert envelope.artifact_version is None
    assert envelope.artifact_degraded is True


@pytest.mark.parametrize(
    ("kind", "visualization", "data", "expected_values"),
    (
        (
            "bar",
            "bar",
            {
                "description": "Values.",
                "unit": "count",
                "items": [
                    {"label": "A", "value": 3, "tone": "neutral"},
                    {"label": "B", "value": 5, "tone": "neutral"},
                ],
            },
            ["3", "5"],
        ),
        (
            "bar",
            "bar_list",
            {
                "description": "Ranked values.",
                "unit": "count",
                "items": [
                    {"label": "A", "value": 5, "tone": "neutral"},
                    {"label": "B", "value": 3, "tone": "neutral"},
                ],
            },
            ["5", "3"],
        ),
        (
            "bar",
            "donut",
            {
                "description": "Parts.",
                "unit": "count",
                "items": [
                    {"label": "A", "value": 3, "tone": "neutral"},
                    {"label": "B", "value": 7, "tone": "neutral"},
                ],
            },
            ["3", "7"],
        ),
        (
            "coverage",
            "category_bar",
            {
                "description": "Coverage.",
                "unit": "ratio",
                "items": [{"label": "Observed", "value": 8, "total": 10, "tone": "neutral"}],
            },
            ["8 / 10"],
        ),
        (
            "time_series",
            "line",
            {
                "description": "Trend.",
                "metric": "requests",
                "unit": "count",
                "points": [
                    {"timestamp": "2026-08-19T00:00:00Z", "value": 1},
                    {"timestamp": "2026-08-19T00:01:00Z", "value": 3},
                    {"timestamp": "2026-08-19T00:02:00Z", "value": 2},
                ],
            },
            ["1", "3", "2"],
        ),
        (
            "time_series",
            "area",
            {
                "description": "Cumulative trend.",
                "metric": "cost",
                "unit": "usd",
                "points": [
                    {"timestamp": "2026-08-19T00:00:00Z", "value": 1},
                    {"timestamp": "2026-08-19T00:01:00Z", "value": 3},
                    {"timestamp": "2026-08-19T00:02:00Z", "value": 6},
                ],
            },
            ["1", "3", "6"],
        ),
        (
            "comparison",
            "comparison_bar",
            {
                "description": "Comparison.",
                "metric": "latency",
                "unit": "milliseconds",
                "items": [
                    {"role": "baseline", "label": "Before", "value": 4},
                    {"role": "current", "label": "Now", "value": 6},
                ],
            },
            ["4", "6"],
        ),
        (
            "timeline",
            "tracker",
            {
                "description": "Events.",
                "items": [
                    {"timestamp": "2026-08-19T00:00:00Z", "label": "Started"},
                    {"timestamp": "2026-08-19T00:01:00Z", "label": "Completed"},
                ],
            },
            ["Started", "Completed"],
        ),
    ),
)
def test_channel_normalizes_all_hinted_visualizations_to_exact_facts(
    kind: str,
    visualization: str,
    data: dict[str, object],
    expected_values: list[str],
) -> None:
    slot_id = {
        "bar": "distribution",
        "coverage": "coverage",
        "time_series": "trend",
        "comparison": "comparison",
        "timeline": "timeline",
    }[kind]
    artifact = _artifact()
    artifact["blocks"] = [
        {
            "slot_id": slot_id,
            "kind": kind,
            "title": "Verified visualization",
            "emphasis": "primary",
            "collapsed": False,
            "evidence_refs": [_REF],
            "data": {
                **data,
                "visualization": visualization,
                "exact_table": {
                    "columns": [{"key": "value", "label": "Value"}],
                    "rows": [{"value": "1"}],
                    "status_key": None,
                },
            },
        }
    ]

    envelope = normalize_terminal_presentation(_terminal(artifact))

    assert envelope.artifact_version == 2
    assert envelope.artifact_degraded is False
    assert [fact.value for fact in envelope.sections[0].facts] == expected_values


@pytest.mark.parametrize(
    ("kind", "data"),
    (
        (
            "bar",
            {
                "description": "Values.",
                "unit": "count",
                "visualization": "bar",
                "items": [
                    {"label": "A", "value": -1, "tone": "neutral"},
                    {"label": "B", "value": 2, "tone": "neutral"},
                ],
            },
        ),
        (
            "bar",
            {
                "description": "Values.",
                "unit": "count",
                "visualization": "bar",
                "items": [
                    {"label": "A", "value": 1, "tone": "invented"},
                    {"label": "B", "value": 2, "tone": "neutral"},
                ],
            },
        ),
        (
            "coverage",
            {
                "description": "Coverage.",
                "unit": "ratio",
                "visualization": "category_bar",
                "items": [{"label": "Observed", "value": 11, "total": 10, "tone": "neutral"}],
            },
        ),
        (
            "comparison",
            {
                "description": "Comparison.",
                "metric": "latency",
                "unit": "milliseconds",
                "visualization": "comparison_bar",
                "items": [
                    {"role": "current", "label": "Now", "value": 6},
                    {"role": "current", "label": "Again", "value": 7},
                ],
            },
        ),
        (
            "time_series",
            {
                "description": "Trend.",
                "metric": "requests",
                "unit": "count",
                "visualization": "line",
                "points": [
                    {"timestamp": "2026-08-19 00:00:00+00:00", "value": 1},
                    {"timestamp": "2026-08-19 00:01:00+00:00", "value": 3},
                    {"timestamp": "2026-08-19 00:02:00+00:00", "value": 2},
                ],
            },
        ),
    ),
)
def test_channel_rejects_artifacts_the_console_contract_rejects(
    kind: str,
    data: dict[str, object],
) -> None:
    artifact = _artifact()
    artifact["blocks"] = [
        {
            "slot_id": "visual",
            "kind": kind,
            "title": "Invalid visualization",
            "emphasis": "primary",
            "collapsed": False,
            "evidence_refs": [_REF],
            "data": {
                **data,
                "exact_table": {
                    "columns": [{"key": "value", "label": "Value"}],
                    "rows": [{"value": "1"}],
                    "status_key": None,
                },
            },
        }
    ]

    envelope = normalize_terminal_presentation(_terminal(artifact))

    assert envelope.artifact_version is None
    assert envelope.artifact_degraded is True


def test_channel_rejects_artifact_refs_above_the_console_bound() -> None:
    refs = [f"ontology-function:evidence-{index}" for index in range(9)]
    artifact = _artifact()
    artifact["evidence_refs"] = refs
    blocks = artifact["blocks"]
    assert isinstance(blocks, list)
    for block in blocks:
        assert isinstance(block, dict)
        block["evidence_refs"] = refs
    terminal = _terminal(artifact)
    verification = terminal["verification"]
    assert isinstance(verification, dict)
    verification["evidence_refs"] = refs

    envelope = normalize_terminal_presentation(terminal)

    assert envelope.artifact_version is None
    assert envelope.artifact_degraded is True


@pytest.mark.parametrize(
    "data",
    (
        {
            "items": [
                {"label": "State", "value": "ready", "tone": "invented"},
            ]
        },
        {
            "items": [
                {"label": "State", "value": "ready", "tone": "neutral"},
                {"label": "State", "value": "waiting", "tone": "neutral"},
            ]
        },
    ),
)
def test_channel_rejects_invalid_summary_identity_or_tone(data: dict[str, object]) -> None:
    artifact = _artifact()
    artifact["blocks"] = [
        {
            "slot_id": "overview",
            "kind": "summary",
            "title": "Summary",
            "emphasis": "primary",
            "collapsed": False,
            "evidence_refs": [_REF],
            "data": data,
        }
    ]

    envelope = normalize_terminal_presentation(_terminal(artifact))

    assert envelope.artifact_version is None
    assert envelope.artifact_degraded is True


@pytest.mark.parametrize(
    "table",
    (
        {
            "columns": [
                {"key": "value", "label": "Value"},
                {"key": "value", "label": "Duplicate"},
            ],
            "rows": [{"value": "1"}],
            "status_key": None,
        },
        {
            "columns": [{"key": "value", "label": "Value"}],
            "rows": [{"value": "1"}],
            "status_key": "missing",
        },
        {
            "columns": [{"key": "value", "label": "Value"}],
            "rows": [{"value": "x" * 600}],
            "status_key": None,
        },
    ),
)
def test_channel_rejects_tables_outside_the_console_contract(
    table: dict[str, object],
) -> None:
    artifact = _artifact()
    artifact["blocks"] = [
        {
            "slot_id": "records",
            "kind": "table",
            "title": "Records",
            "emphasis": "primary",
            "collapsed": False,
            "evidence_refs": [_REF],
            "data": table,
        }
    ]

    envelope = normalize_terminal_presentation(_terminal(artifact))

    assert envelope.artifact_version is None
    assert envelope.artifact_degraded is True


@pytest.mark.parametrize(
    ("kind", "data"),
    (
        (
            "summary",
            {
                "items": [
                    {"label": "State", "value": "x" * 513, "tone": "neutral"},
                ]
            },
        ),
        (
            "callout",
            {"tone": "warning", "lines": ["x" * 513]},
        ),
        (
            "time_series",
            {
                "description": "x" * 513,
                "metric": "requests",
                "unit": "count",
                "visualization": "line",
                "points": [
                    {"timestamp": "2026-08-19T00:00:00Z", "value": 1},
                    {"timestamp": "2026-08-19T00:01:00Z", "value": 3},
                    {"timestamp": "2026-08-19T00:02:00Z", "value": 2},
                ],
                "exact_table": {
                    "columns": [{"key": "value", "label": "Value"}],
                    "rows": [{"value": "1"}],
                    "status_key": None,
                },
            },
        ),
    ),
)
def test_channel_rejects_text_above_the_console_bound(
    kind: str,
    data: dict[str, object],
) -> None:
    artifact = _artifact()
    artifact["blocks"] = [
        {
            "slot_id": "limitations"
            if kind == "callout"
            else "trend"
            if kind == "time_series"
            else "overview",
            "kind": kind,
            "title": "Bounded text",
            "emphasis": "primary",
            "collapsed": False,
            "evidence_refs": [_REF],
            "data": data,
        }
    ]

    envelope = normalize_terminal_presentation(_terminal(artifact))

    assert envelope.artifact_version is None
    assert envelope.artifact_degraded is True


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("schema_version", True),
        ("slot_id", "Trend"),
        ("kind", "summary"),
        ("emphasis", "critical"),
        ("collapsed", "false"),
    ),
)
def test_channel_rejects_block_envelopes_outside_the_console_contract(
    field: str,
    value: object,
) -> None:
    artifact = _artifact()
    blocks = artifact["blocks"]
    assert isinstance(blocks, list) and isinstance(blocks[0], dict)
    if field == "schema_version":
        artifact[field] = value
    else:
        blocks[0][field] = value

    envelope = normalize_terminal_presentation(_terminal(artifact))

    assert envelope.artifact_version is None
    assert envelope.artifact_degraded is True


@pytest.mark.parametrize(
    ("kind", "slot_id", "data"),
    (
        ("summary", "overview", {"items": [{"label": "State", "value": "ready"}]}),
        (
            "summary",
            "overview",
            {"items": [{"label": "Count", "value": 3, "tone": "neutral"}]},
        ),
        (
            "evidence",
            "evidence",
            {"items": [{"label": "Source", "value": "ref", "tone": "neutral"}]},
        ),
        ("evidence", "evidence", {"items": [{"label": "Count", "value": 3}]}),
        ("callout", "limitations", {"tone": "invented", "lines": ["Unavailable."]}),
    ),
)
def test_channel_rejects_item_schemas_outside_the_console_contract(
    kind: str,
    slot_id: str,
    data: dict[str, object],
) -> None:
    artifact = _artifact()
    artifact["blocks"] = [
        {
            "slot_id": slot_id,
            "kind": kind,
            "title": "Invalid item schema",
            "emphasis": "primary",
            "collapsed": False,
            "evidence_refs": [_REF],
            "data": data,
        }
    ]

    envelope = normalize_terminal_presentation(_terminal(artifact))

    assert envelope.artifact_version is None
    assert envelope.artifact_degraded is True


def test_channel_rejects_fractional_v1_chart_values() -> None:
    artifact = _artifact()
    artifact["schema_version"] = 1
    artifact["blocks"] = [
        {
            "slot_id": "distribution",
            "kind": "bar",
            "title": "Legacy values",
            "emphasis": "primary",
            "collapsed": False,
            "evidence_refs": [_REF],
            "data": {
                "items": [
                    {"label": "A", "value": 1.5, "tone": "neutral"},
                    {"label": "B", "value": 2, "tone": "neutral"},
                ]
            },
        }
    ]

    envelope = normalize_terminal_presentation(_terminal(artifact))

    assert envelope.artifact_version is None
    assert envelope.artifact_degraded is True


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("title", "Line one\nLine two"),
        ("value", "Line one\nLine two"),
    ),
)
def test_channel_rejects_artifact_control_characters(
    field: str,
    value: str,
) -> None:
    artifact = _artifact()
    artifact["blocks"] = [
        {
            "slot_id": "overview",
            "kind": "summary",
            "title": value if field == "title" else "Summary",
            "emphasis": "primary",
            "collapsed": False,
            "evidence_refs": [_REF],
            "data": {
                "items": [
                    {
                        "label": "State",
                        "value": value if field == "value" else "ready",
                        "tone": "neutral",
                    }
                ]
            },
        }
    ]

    envelope = normalize_terminal_presentation(_terminal(artifact))

    assert envelope.artifact_version is None
    assert envelope.artifact_degraded is True
