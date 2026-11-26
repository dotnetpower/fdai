"""Unit tests for the verifier's bounded constant evaluation and list tracking."""

from __future__ import annotations

import ast

import pytest
from fdai.core.security.code_findings import verifier_lists as lists
from fdai.core.security.code_findings.verifier_constants import (
    UNKNOWN,
    evaluate,
    irrefutable,
    selected_case,
    single_assignment_constants,
)


def _expr(source: str) -> ast.expr:
    return ast.parse(source, mode="eval").body


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("7 * 42 - 86 > 200", True),
        ("-3 + +2", -1),
        ("not 0", True),
        ("'abc'[1]", "b"),
        ("'help-me-now'[5:-4]", "me"),
        ("(1, 2)[0]", 1),
        ("'a' in 'cat'", True),
        ("'z' not in 'cat'", True),
        ("1 < 2 < 3", True),
        ("1 < 3 < 2", False),
        ("0 or 'x'", "x"),
        ("1 and 0", 0),
        ("10 // 3 % 2", 1),
        ("None", None),
    ],
)
def test_evaluate_folds_fixed_expressions(source: str, expected: object) -> None:
    assert evaluate(_expr(source), {}) == expected


@pytest.mark.parametrize(
    "source",
    [
        "name",
        "f(1)",
        "[1, 2]",
        "1 / 0",
        "2 ** 3",
        "'ab' * 5000",
        "10 ** 30",
        "-'a'",
        "~1",
        "'abc'[name]",
        "'abc'[1.5]",
        "'abc'[name:2]",
        "(1, name)",
        "1 is 1",
        "1 < name",
        "name or 1",
        "'abc'[9]",
        "b'x' * 9000",
    ],
)
def test_evaluate_leaves_open_expressions_unknown(source: str) -> None:
    assert evaluate(_expr(source), {}) is UNKNOWN


def test_evaluate_rejects_oversized_literals_and_reads_constants() -> None:
    assert evaluate(_expr("'x' * 3"), {}) == "xxx"
    assert evaluate(_expr("big"), {"big": "y" * 5000}) == "y" * 5000
    assert evaluate(_expr("(big, 1)"), {"big": "y" * 5000}) == ("y" * 5000, 1)
    assert evaluate(_expr("big + 'y'"), {"big": "y" * 4096}) is UNKNOWN
    assert evaluate(_expr("n * 2"), {"n": 2**63}) is UNKNOWN


def _function(source: str) -> ast.FunctionDef:
    node = ast.parse(source).body[0]
    assert isinstance(node, ast.FunctionDef)
    return node


def test_single_assignment_constants_skip_rebound_and_external_names() -> None:
    function = _function(
        "def run(arg, *rest, **extra):\n"
        "    num = 86\n"
        "    word = 'ABC'\n"
        "    pick = word[1]\n"
        "    twice = 1\n"
        "    twice = 2\n"
        "    arg = 3\n"
        "    import os\n"
        "    os = 4\n"
        "    global shared\n"
        "    shared = 5\n"
        "    def inner(): pass\n"
        "    inner = 6\n"
        "    class Kind: pass\n"
        "    Kind = 7\n"
        "    try:\n"
        "        pass\n"
        "    except ValueError as error:\n"
        "        error = 8\n"
        "    match word:\n"
        "        case [*others]:\n"
        "            others = 9\n"
        "        case {'k': 1, **remainder}:\n"
        "            remainder = 10\n"
        "        case captured:\n"
        "            captured = 11\n"
        "    later = derived + 1\n"
        "    derived = num * 2\n"
        "    for item in []:\n"
        "        pass\n"
        "    item = 12\n"
    )
    constants = single_assignment_constants(function)
    assert constants == {"num": 86, "word": "ABC", "pick": "B", "derived": 172, "later": 173}
    assert single_assignment_constants(None) == {}


def _match(source: str) -> ast.Match:
    node = ast.parse(source).body[0]
    assert isinstance(node, ast.Match)
    return node


@pytest.mark.parametrize(
    ("source", "constants", "expected"),
    [
        ("match g:\n case 'A': pass\n case 'B': pass", {"g": "B"}, 1),
        ("match g:\n case 'A' | 'B': pass", {"g": "B"}, 0),
        ("match g:\n case 'A': pass", {"g": "Z"}, -1),
        ("match g:\n case None: pass\n case _: pass", {"g": None}, 0),
        ("match g:\n case 'A': pass\n case x: pass", {"g": "Z"}, 1),
        ("match g:\n case 'A' as y: pass", {"g": "A"}, 0),
        ("match g:\n case 'A': pass", {}, None),
        ("match g:\n case 'A' if ok: pass", {"g": "A"}, None),
        ("match g:\n case [a]: pass", {"g": "A"}, None),
        ("match g:\n case k.A: pass", {"g": "A"}, None),
        ("match g:\n case 'Z' | k.A: pass", {"g": "A"}, None),
    ],
)
def test_selected_case(source: str, constants: dict[str, object], expected: int | None) -> None:
    node = _match(source)
    assert selected_case(node.subject, node.cases, constants) == expected


def test_irrefutable_requires_an_unguarded_capture() -> None:
    assert irrefutable(_match("match g:\n case _: pass").cases)
    assert not irrefutable(_match("match g:\n case _ if ok: pass").cases)
    assert not irrefutable(_match("match g:\n case 'A': pass").cases)


def test_list_tracking_shifts_elements_and_merges_conservatively() -> None:
    state: lists.State = {}
    lists.track(state, "items", [None, "tainted", None])
    assert lists.length(state, "items") == 3
    assert lists.element(state, "items", 1) == "tainted"
    assert lists.element(state, "items", -2) == "tainted"
    assert lists.element(state, "items", 7) is None
    assert lists.pop(state, "items", 0)
    assert lists.element(state, "items", 0) == "tainted"
    lists.append(state, "items", "late")
    assert lists.element(state, "items", -1) == "late"
    assert not lists.pop(state, "items", 9)
    assert lists.length(state, "items") is None
    lists.append(state, "items", "ignored")
    assert lists.length(state, "items") is None
    state["other"] = "whole"
    assert lists.element(state, "other", 0) == "whole"

    same_left: lists.State = {}
    same_right: lists.State = {}
    lists.track(same_left, "items", [None])
    lists.track(same_right, "items", ["tainted"])
    merged = {**same_right, **same_left}
    lists.merge([same_left, same_right], merged)
    assert lists.length(merged, "items") == 1

    shorter: lists.State = {}
    lists.track(shorter, "items", [])
    merged = {**same_left, **shorter}
    lists.merge([same_left, shorter], merged)
    assert lists.length(merged, "items") is None
