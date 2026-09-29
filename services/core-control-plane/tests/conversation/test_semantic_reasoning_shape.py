"""The development shape of a question form names ids and closed values only."""

from __future__ import annotations

import re

from fdai.core.conversation.semantic_reasoning_form import SemanticQuestionForm
from fdai.core.conversation.semantic_reasoning_shape import MAX_SHAPE_TOKENS, form_shape

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
