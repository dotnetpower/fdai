"""Parity: the stewardship canonical names match the pantheon exactly.

`core/stewardship` cannot import `agents/` (module boundary), so it keeps its
own `AGENT_NAMES`. This test is the bridge that stops the two from drifting.
"""

from __future__ import annotations

from fdai.agents import PANTHEON_NAMES
from fdai.core.stewardship.names import AGENT_NAME_SET, AGENT_NAMES


def test_stewardship_names_match_pantheon_exactly() -> None:
    assert AGENT_NAME_SET == PANTHEON_NAMES


def test_stewardship_names_have_no_duplicates() -> None:
    assert len(AGENT_NAMES) == len(set(AGENT_NAMES)) == 15
