"""The development shape of a question form names ids and closed values only."""

from __future__ import annotations

import re
from typing import Any

import pytest
from fdai.core.conversation.semantic_reasoning_form import SemanticQuestionForm
from fdai.core.conversation.semantic_reasoning_shape import (
    MAX_SHAPE_TOKENS,
    form_shape,
    reads_beyond_list,
)

from tests.conversation.semantic_reasoning_support import span

_CLOSED_TOKEN = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}(?:[.:][A-Za-z0-9_]{1,63}){0,3}$")


def test_a_form_shape_shows_how_the_question_was_read_without_its_text() -> None:
    utterance = "Which resource group contains kv-app-01 in the last 3 days?"
    form = SemanticQuestionForm.model_validate(
        {
            "mentions": [
                {
                    "id": "m1",
                    "form": "concept",
                    "domain": "resource_type",
                    "span": span(utterance, "resource group"),
                },
                {
                    "id": "m2",
                    "form": "name",
                    "domain": "instance",
                    "span": span(utterance, "kv-app-01"),
                    "qualifier": {"mention": "m1", "sense": "containment"},
                },
            ],
            "goals": [
                {
                    "id": "g1",
                    "level": "instance",
                    "operation": "select",
                    "subject": "m1",
                    "subject_scope": "collection",
                    "relation": {
                        "sense": "containment",
                        "anchor": "m2",
                        "anchor_role": "member",
                        "result_role": "container",
                        "cue": span(utterance, "contains"),
                    },
                    "measure": {"kind": "count", "group_by": "container", "mention": "m1"},
                    "time": {
                        "kind": "window",
                        "value": {"duration": {"amount": 3, "unit": "day"}},
                        "cue": span(utterance, "in the last 3 days"),
                    },
                    "cue": span(utterance, "Which"),
                    "confidence": 0.9,
                }
            ],
        }
    )

    shape = form_shape(form)

    assert shape == (
        "reading:beyond_list",
        "m1:resource_type:concept",
        "m2:instance:name",
        "qualifier:m2:m1:containment",
        "g1:instance:select:collection",
        "subject:g1:m1",
        "measure:g1:count:container",
        "measure_mention:g1:m1",
        "relation:g1:containment:one_sense",
        "roles:g1:member:container",
        "anchor:g1:m2",
        "time:g1:window",
    )
    assert all(_CLOSED_TOKEN.fullmatch(token) for token in shape)
    assert not any("kv-app" in token or "group" in token for token in shape)
    assert len(shape) <= MAX_SHAPE_TOKENS


_LIST = "How many storage accounts are in rg-app?"


def _list_form(**goal: Any) -> SemanticQuestionForm:
    base: dict[str, Any] = {
        "id": "g1",
        "level": "instance",
        "operation": "select",
        "subject": "m1",
        "subject_scope": "collection",
        "relation": {
            "sense": "containment",
            "anchor": "m2",
            "anchor_role": "container",
            "result_role": "member",
            "cue": span(_LIST, "are in"),
        },
        "cue": span(_LIST, "How many"),
        "confidence": 0.9,
    }
    base.update(goal)
    return SemanticQuestionForm.model_validate(
        {
            "mentions": [
                {
                    "id": "m1",
                    "form": "concept",
                    "domain": "resource_type",
                    "span": span(_LIST, "storage accounts"),
                },
                {"id": "m2", "form": "name", "domain": "instance", "span": span(_LIST, "rg-app")},
                {"id": "m3", "form": "value", "domain": "state", "span": span(_LIST, "are")},
            ],
            "goals": [base],
        }
    )


@pytest.mark.parametrize(
    ("goal", "beyond"),
    (
        ({}, False),
        ({"operation": "count", "measure": {"kind": "count"}}, False),
        ({"operation": "aggregate", "measure": {"kind": "count", "group_by": "container"}}, True),
        ({"filters": [{"role": "state", "mention": "m3"}]}, True),
        ({"level": "schema"}, True),
        ({"subject_scope": "anchor", "subject": "m2", "operation": "traverse"}, True),
        (
            {
                "relation": {
                    "sense": "containment",
                    "anchor": "m2",
                    "anchor_role": "member",
                    "result_role": "container",
                    "cue": span(_LIST, "are in"),
                }
            },
            True,
        ),
    ),
)
def test_only_a_filtered_list_reading_is_answerable_by_one_filtered_list(
    goal: dict[str, Any], beyond: bool
) -> None:
    # A kind in a named container, listed or counted, is one filtered list; a grouping,
    # state, schema level, traversal, or the container of a member asks for more.
    assert reads_beyond_list(_list_form(**goal)) is beyond
