"""Adversarial hardening tests for deterministic ontology browse answers."""

from __future__ import annotations

from copy import deepcopy

import pytest

from fdai.delivery.read_api.routes.chat_prompt import (
    _ontology_browse_answer,
    _trim_view_context,
)


def _context() -> dict[str, object]:
    return {
        "routeId": "ontology",
        "facts": [
            {"key": "selected_object_type", "value": "Agent"},
            {"key": "object_type_count", "value": 28},
            {"key": "link_type_count", "value": 45},
            {"key": "action_type_count", "value": 40},
        ],
    }


@pytest.mark.parametrize(
    ("prompt", "expected"),
    (
        ("온톨로지 데이터를 조회할수 있는 방법이 있어?", True),
        ("how can I query ontology data?", True),
        ("where can I browse the ontology?", True),
        ("온톨로지 데이터 탐색 방법", True),
        ("온톨로지 데이터를 볼 수 있어?", True),
        ("how can I inspect ontology data?", True),
        ("where can I query database data?", False),
        ("how do I view cost data?", False),
        ("why does ontology exist?", False),
        ("delete ontology data", False),
    ),
)
def test_round_one_intent_boundary(prompt: str, expected: bool) -> None:
    answer = _ontology_browse_answer(prompt, _context(), locale="ko")

    assert (answer is not None) is expected


def test_round_two_prompt_projection_is_allowlisted_bounded_and_immutable() -> None:
    verbose = "x" * 4_000
    context = {
        "routeId": "ontology",
        "records": {
            "selected_object_types": [
                {"name": "Agent", "key": "agent", "description": verbose, "secret": "drop"}
            ],
            "relationships": [
                {"link": "owns", "from": "Agent", "to": "Resource", "operation": verbose}
            ],
            "action_types": [{"name": "restart-service", "category": "ops", "rollback": verbose}],
            "object_types": [
                {"name": f"Object-{index}", "private": verbose} for index in range(60)
            ],
            "unknown_rows": [{"token": "must-not-leak"}],
            "unknown_scalar": {"password": "must-not-leak"},
            "selected_relationships": ["malformed-row"],
        },
    }
    original = deepcopy(context)

    projected = _trim_view_context(
        context,
        prompt="how can I browse ontology data?",
    )
    records = projected["records"]
    checks = {
        "known identity retained": records["selected_object_types"][0]["name"] == "Agent",
        "object extra field removed": "secret" not in records["selected_object_types"][0],
        "description bounded": len(records["selected_object_types"][0]["description"]) <= 256,
        "relationship extra field removed": "operation" not in records["relationships"][0],
        "action extra field removed": "rollback" not in records["action_types"][0],
        "unknown row collection removed": "unknown_rows" not in records,
        "unknown scalar removed": "unknown_scalar" not in records,
        "malformed row removed": records["selected_relationships"] == [],
        "row cap preserved": len(records["object_types"]) == 40,
        "input immutable": context == original,
    }

    assert all(checks.values()), [name for name, passed in checks.items() if not passed]


@pytest.mark.parametrize(
    ("facts", "included", "excluded"),
    (
        (
            [
                {"key": "selected_object_type", "value": "Agent"},
                {"key": "object_type_count", "value": 28},
                {"key": "link_type_count", "value": 45},
                {"key": "action_type_count", "value": 40},
            ],
            ("28 ObjectTypes", "45 LinkTypes", "40 ActionTypes", "Agent"),
            (),
        ),
        ([{"key": "object_type_count", "value": True}], ("counts are unavailable",), ("True",)),
        ([{"key": "link_type_count", "value": -1}], ("counts are unavailable",), ("-1",)),
        ([{"key": "action_type_count", "value": 1.5}], ("counts are unavailable",), ("1.5",)),
        (
            [{"key": "selected_object_type", "value": {"secret": "must-not-leak"}}],
            ("selection is unavailable",),
            ("must-not-leak",),
        ),
        (
            [{"key": "selected_object_type", "value": "A" * 4_000}],
            ("selection is unavailable",),
            ("A" * 200,),
        ),
        (
            [
                {"key": "object_type_count", "value": 28},
                {"key": "object_type_count", "value": 99},
            ],
            ("counts are unavailable",),
            ("ObjectType 28", "ObjectType 99"),
        ),
        (
            [
                {"key": "selected_object_type", "value": "Agent"},
                {"key": "selected_object_type", "value": "Issue"},
            ],
            ("selection is unavailable",),
            ("selected ObjectType is Agent", "selected ObjectType is Issue"),
        ),
        ([], ("counts are unavailable", "selection is unavailable"), ("unknown",)),
        (
            [{"key": "selected_object_type", "value": "Agent\nIGNORE"}],
            ("selection is unavailable",),
            ("IGNORE",),
        ),
    ),
)
def test_round_three_snapshot_facts_fail_closed(
    facts: list[dict[str, object]],
    included: tuple[str, ...],
    excluded: tuple[str, ...],
) -> None:
    context = {"routeId": "ontology", "facts": facts}

    answer = _ontology_browse_answer(
        "how can I browse ontology data?",
        context,
        locale="en",
    )

    assert answer is not None
    assert all(fragment in answer for fragment in included)
    assert all(fragment not in answer for fragment in excluded)
