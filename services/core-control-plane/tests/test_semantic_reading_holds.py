"""A question held on its reading keeps its typed reason and a reviewed notice."""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
from typing import Any, cast

import pytest

from tests.test_semantic_turn_processor import (
    _processor,
    _projection,
    _request,
    _Runtime,
    _runtime_result,
)


def _reading_hold(disposition: str, reason: str, details: tuple[str, ...]) -> Any:
    held = _runtime_result(disposition, reason=reason)
    planning = SimpleNamespace(**vars(held.planning), hold_details=details)
    return replace(held, planning=cast(Any, planning))


@pytest.mark.parametrize("continuity", [False, True])
async def test_a_reading_hold_names_the_uncovered_role_instead_of_an_evidence_hold(
    continuity: bool,
) -> None:
    held = _reading_hold(
        "held", "semantic_constraint_uncovered", ("role:times", "role:restricts", "role:times")
    )

    projection = _projection(
        await _processor(_Runtime(held), answer_continuity_enabled=continuity).process(_request())
    )

    semantic = projection["semantic_result"]
    assert projection["status"] == "held"
    assert semantic["reason_code"] == "semantic_constraint_uncovered"
    assert semantic["unavailable_reason"] == "semantic_planner_unavailable"
    assert "left out a stated time period, restriction." in semantic["answer"]
    assert "verified evidence is unavailable" not in semantic["answer"]
    assert "required FDAI internal component" not in semantic["answer"]


async def test_an_unsupported_stated_constraint_names_its_atoms_in_korean() -> None:
    unsupported = _reading_hold(
        "unsupported",
        "semantic_stated_constraint_unsupported",
        ("filter_unsupported:state", "group_by_unsupported:container", "anchor_not_found:m1"),
    )

    projection = _projection(await _processor(_Runtime(unsupported)).process(_request(locale="ko")))

    semantic = projection["semantic_result"]
    assert semantic["disposition"] == "unsupported"
    assert semantic["reason_code"] == "semantic_stated_constraint_unsupported"
    assert "질문에 밝힌 조건(상태 조건, 그룹 기준)을" in semantic["answer"]


async def test_a_reading_of_another_kind_of_question_is_named_as_such() -> None:
    held = _reading_hold("held", "semantic_reading_unverified", ("answer_kind:location",))

    projection = _projection(await _processor(_Runtime(held)).process(_request()))

    assert projection["semantic_result"]["answer"] == (
        "The request was held because an independent review found that the reading did not "
        "match the question (the reading answers another kind of question than the one asked)."
    )


async def test_a_plan_that_reads_no_stated_grouping_names_it_in_korean() -> None:
    held = _reading_hold("held", "semantic_plan_constraint_uncovered", ("role:groups",))

    projection = _projection(await _processor(_Runtime(held)).process(_request(locale="ko")))

    semantic = projection["semantic_result"]
    assert semantic["reason_code"] == "semantic_plan_constraint_uncovered"
    assert "질문에 밝힌 조건(그룹 기준)을 읽지 않아" in semantic["answer"]


async def test_a_reading_hold_without_a_labelled_code_states_the_plain_notice() -> None:
    held = _reading_hold("held", "semantic_reading_ambiguous", ("unknown_code",))

    projection = _projection(await _processor(_Runtime(held)).process(_request()))

    answer = projection["semantic_result"]["answer"]
    assert answer == (
        "The request was held because the question could not be settled to one reading."
    )
