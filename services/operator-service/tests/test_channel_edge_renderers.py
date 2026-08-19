"""Provider rendering parity and fail-closed artifact tests."""

from __future__ import annotations

import copy
import json

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
