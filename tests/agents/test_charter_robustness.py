"""Charter robustness contracts for the 15 fixed agents.

The conversational charter can drift in two directions that no type
checker catches: a role directive can promise mechanics the agent never
exposes, and a declared read tool can go silent when the agent holds no
runtime state. Both turn an honest port into a plausible-sounding one.

These tests pin the invariants that keep every agent at the same
standard, so a future charter edit cannot quietly regress one of them.
"""

from __future__ import annotations

import pytest

from fdai.agents._framework.base import Agent
from fdai.agents._framework.charters import _ROLE_DIRECTIVES
from fdai.agents._framework.conversation_prompt import MAX_ROLE_DIRECTIVE_CHARS
from fdai.agents._framework.factory import instantiate_pantheon
from fdai.agents._framework.pantheon import PANTHEON_SPECS

_AGENT_NAMES = tuple(spec.name for spec in PANTHEON_SPECS)

#: Agents whose answers rest on accumulated runtime state and therefore
#: MUST report an evidence gap while that state is empty. Bragi is the
#: sole exception: it owns no runtime evidence at all, and its roster
#: answer is derived from the immutable specs, so it is always grounded.
_STATE_DEPENDENT_AGENTS = frozenset(set(_AGENT_NAMES) - {"Bragi"})


@pytest.mark.parametrize("name", _AGENT_NAMES)
def test_every_agent_declares_bounded_specific_role_mechanics(name: str) -> None:
    directive = _ROLE_DIRECTIVES[name]

    assert directive.strip()
    assert len(directive) <= MAX_ROLE_DIRECTIVE_CHARS
    # A directive that only restates the mandate adds nothing. Every one
    # names concrete mechanics, which takes more than a single clause.
    assert len(directive.split()) >= 25
    assert (
        directive.startswith(("Arbitration", "Execution", "Judgment", "Ingress"))
        or ":" in (directive.split(".")[0])
    )


@pytest.mark.parametrize("name", _AGENT_NAMES)
async def test_every_declared_tool_answers_when_the_agent_holds_no_state(name: str) -> None:
    """An empty agent MUST say it has no data, not fall silent.

    A tool that abstains with ``no_tool_data`` tells the operator nothing
    about whether the fact is unavailable or the tool is broken. Every
    tool projects its own fact scope and reports the absence instead.
    """
    agent = instantiate_pantheon()[name]
    spec = agent.spec

    for tool in spec.conversation.tool_specs:
        envelope = await agent.on_conversation_turn(
            f"what is the {tool.tool_id} state",
            {"conversation_tool": tool.tool_id},
        )
        assert envelope["abstain_reason"] is None, f"{name}:{tool.tool_id}"
        assert envelope["answer"]


@pytest.mark.parametrize("name", _AGENT_NAMES)
def test_state_dependent_agents_report_their_evidence_gap(name: str) -> None:
    """Configuration MUST NOT be narrated as if it were an outcome."""
    agent = instantiate_pantheon()[name]
    overrides = type(agent).conversation_evidence_available is not (
        Agent.conversation_evidence_available
    )

    if name in _STATE_DEPENDENT_AGENTS:
        assert overrides, f"{name} answers from runtime state and MUST report an evidence gap"
        assert agent.conversation_evidence_available({}) is False
    else:
        assert not overrides
        assert agent.conversation_evidence_available({}) is True


@pytest.mark.parametrize("name", _AGENT_NAMES)
async def test_a_fresh_agent_composes_the_evidence_gap_layer(name: str) -> None:
    agent = instantiate_pantheon()[name]

    envelope = await agent.on_conversation_turn("what is your current status", {})
    layers = envelope["prompt_composition"]["layers"]

    if name in _STATE_DEPENDENT_AGENTS:
        assert "evidence_gap" in layers, name
    else:
        assert "evidence_gap" not in layers, name


def test_every_agent_declares_at_least_three_owned_fact_keys() -> None:
    """A charter with one fact per tool cannot ground a real answer."""
    thin = {
        spec.name: sorted({key for tool in spec.conversation.tool_specs for key in tool.fact_keys})
        for spec in PANTHEON_SPECS
        if len({key for tool in spec.conversation.tool_specs for key in tool.fact_keys}) < 3
    }

    assert thin == {}
