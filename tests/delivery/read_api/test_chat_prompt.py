"""Prompt-assembly tests for the console chat backend.

These exercise :func:`_build_messages` and :func:`_is_concept_query` across
30+ operator-question conditions WITHOUT calling a live model. They lock in
the efficiency contract: the system prompt stays lean by default and only
carries the FDAI glossary when the operator actually asks to define a term.

Korean literals in the parametrised cases are the literal subject under test
(the operator's own-language phrasing) and are written as ``\\uXXXX`` escapes
so the source stays ASCII for the english-only gate - matching the language
policy's "quoted data" exception.
"""

from __future__ import annotations

import json

import pytest

from fdai.delivery.read_api.chat import (
    _GLOSSARY,
    DEFAULT_MAX_CONTEXT_BYTES,
    DEFAULT_MAX_HISTORY_TURNS,
    _build_messages,
    _is_concept_query,
)

_GLOSSARY_MARKER = _GLOSSARY.splitlines()[0]
"""First line of the glossary block - present in the system message iff the
glossary was injected."""

# Rough per-turn budget for the STATIC prompt (everything before the snapshot
# JSON). The lean prompt must stay well under this; the glossary variant may
# exceed the lean size but must still be bounded. Guards against prompt bloat.
_LEAN_BASE_BUDGET = 1_300

_SNAPSHOT_MARKER = "Current view snapshot (JSON):"


def _system_of(messages: list[dict[str, str]]) -> str:
    assert messages[0]["role"] == "system"
    return messages[0]["content"]


def _base_of(system: str) -> str:
    """The static prefix of the system prompt, up to the snapshot marker."""
    return system.split(_SNAPSHOT_MARKER)[0]


# ---------------------------------------------------------------------------
# Concept vs data classification (drives glossary injection)
# ---------------------------------------------------------------------------

# Concept questions -> glossary MUST be injected. Mix of English + Korean.
CONCEPT_QUERIES: list[str] = [
    "explain T2",
    "what is HIL?",
    "what are the verticals?",
    "define shadow mode",
    "what does abstain mean?",
    "glossary please",
    "explain the difference between shadow and enforce",
    "what is a gate decision",
    "\uc124\uba85\ud574\uc918 T2\uac00 \ubb50\uc57c",  # "explain, what is T2"
    "HIL\uc774 \ubb54\uc9c0?",  # "what is HIL?"
    "shadow mode\uc758 \uc758\ubbf8\uac00 \ubb54\uc57c?",  # "what does shadow mode mean?"
    "\uac1c\ub150 \uc124\uba85 \ud574\uc918",  # "explain the concept"
    "abstain \uc815\uc758",  # "abstain definition"
    "T0\ub780 \ubb34\uc5c7\uc778\uac00",  # "what is T0"
]

# Data / screen questions -> glossary MUST be omitted (lean prompt). Note the
# tricky "what is the shadow share?" - concept phrasing but a data word.
DATA_QUERIES: list[str] = [
    "how many rules are active?",
    "what is the shadow share?",
    "list all pending kinds",
    "how many tiles need attention?",
    "which tiles are failed?",
    "count of audit rows",
    "nsg",
    "show me the tier mix",
    "total events this session",
    "what is the current EPS?",
    "how many ObjectTypes are registered?",
    "was the traversal truncated?",
    "\ud65c\uc131 \ub8f0\uc774 \uba87 \uac1c\uc57c?",  # "how many active rules?" (count marker)
    "\ub300\uae30 \uc911\uc778 \ud56d\ubaa9 \uac1c\uc218",  # "count of pending items"
    "nsg \uad00\ub828 \ub8f0 \ubcf4\uc5ec\uc918",  # "show nsg-related rules"
    "\uc2dc\ub098\ub9ac\uc624 \ubaa9\ub85d",  # "list scenarios"
]


@pytest.mark.parametrize("query", CONCEPT_QUERIES)
def test_concept_query_injects_glossary(query: str) -> None:
    assert _is_concept_query(query) is True
    system = _system_of(_build_messages(query, {}, []))
    assert _GLOSSARY_MARKER in system


@pytest.mark.parametrize("query", DATA_QUERIES)
def test_data_query_omits_glossary(query: str) -> None:
    assert _is_concept_query(query) is False
    system = _system_of(_build_messages(query, {}, []))
    assert _GLOSSARY_MARKER not in system


# ---------------------------------------------------------------------------
# Prompt size / efficiency regression
# ---------------------------------------------------------------------------


def test_lean_prompt_is_small() -> None:
    system = _system_of(_build_messages("how many rules?", {}, []))
    assert _base_of(system).strip() != ""
    assert len(_base_of(system)) < _LEAN_BASE_BUDGET


def test_glossary_prompt_is_larger_but_bounded() -> None:
    lean = _base_of(_system_of(_build_messages("how many rules?", {}, [])))
    rich = _base_of(_system_of(_build_messages("explain T2", {}, [])))
    assert len(rich) > len(lean)
    # The glossary variant is the lean base plus (roughly) the glossary block.
    assert len(rich) < len(lean) + len(_GLOSSARY) + 32


# ---------------------------------------------------------------------------
# Message structure invariants (30+ combined conditions above already, plus
# these plumbing guarantees)
# ---------------------------------------------------------------------------


def test_user_turn_is_last_and_verbatim() -> None:
    msgs = _build_messages("which tiles are failed?", {"routeId": "live"}, [])
    assert msgs[-1] == {"role": "user", "content": "which tiles are failed?"}


def test_snapshot_is_embedded_in_system() -> None:
    ctx = {"routeId": "rules", "facts": [{"key": "active_rules", "value": 61}]}
    system = _system_of(_build_messages("hi", ctx, []))
    assert json.dumps(ctx, ensure_ascii=False) in system


def test_history_is_bounded_and_sanitised() -> None:
    history = [{"role": "user", "content": f"q{i}"} for i in range(DEFAULT_MAX_HISTORY_TURNS + 5)]
    # Interleave some invalid entries that must be dropped.
    history.append({"role": "system", "content": "should be dropped"})
    history.append({"role": "user", "content": ""})
    msgs = _build_messages("final", {}, history)
    convo = msgs[1:-1]  # exclude system + final user turn
    assert len(convo) <= DEFAULT_MAX_HISTORY_TURNS
    assert all(m["role"] in {"user", "assistant"} for m in convo)
    assert all(m["content"] for m in convo)
    assert "should be dropped" not in [m["content"] for m in convo]


def test_oversized_snapshot_is_truncated() -> None:
    big = {"blob": "x" * (DEFAULT_MAX_CONTEXT_BYTES + 5_000)}
    system = _system_of(_build_messages("hi", big, []))
    assert "...(truncated)" in system


def test_braces_in_snapshot_do_not_break_formatting() -> None:
    # A value containing format-like braces must survive str.format.
    ctx = {"note": "value with {curly} and {snapshot_json} tokens"}
    system = _system_of(_build_messages("hi", ctx, []))
    assert "{curly}" in system


def test_long_prompt_is_truncated_to_cap() -> None:
    msgs = _build_messages("z" * 9_000, {}, [])
    assert len(msgs[-1]["content"]) == 4_000
