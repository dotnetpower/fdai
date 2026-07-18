"""Canonical pantheon agent names for the stewardship layer.

`core/` MUST NOT import `agents/` (module-boundary rule in
`scripts/quality/architecture/check-core-imports.sh` keeps the control plane layered and portable).
The stewardship config therefore carries its **own** copy of the 15 agent
names, and a parity test
(`tests/core/stewardship/test_pantheon_parity.py`) pins this tuple to
`fdai.agents._framework.pantheon.PANTHEON_NAMES` so the two can never drift.

Order mirrors `PANTHEON_SPECS` for readability; membership (not order) is what
the parity test and the config validation assert.
"""

from __future__ import annotations

from typing import Final

AGENT_NAMES: Final[tuple[str, ...]] = (
    "Odin",
    "Thor",
    "Forseti",
    "Huginn",
    "Heimdall",
    "Vidar",
    "Var",
    "Bragi",
    "Saga",
    "Mimir",
    "Muninn",
    "Norns",
    "Njord",
    "Freyr",
    "Loki",
)

AGENT_NAME_SET: Final[frozenset[str]] = frozenset(AGENT_NAMES)

__all__ = ["AGENT_NAMES", "AGENT_NAME_SET"]
