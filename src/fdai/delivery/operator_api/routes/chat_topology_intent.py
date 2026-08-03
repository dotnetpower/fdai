"""Strict context-free topology intent classification for operator chat."""

from __future__ import annotations

import re
from typing import Final

_TOPOLOGY_QUESTION: Final = re.compile(
    r"\b(?:dependencies|dependency\s+path|trace\s+the\s+path|reach|end\s+to\s+end|"
    r"resource\s+relationships?|inbound\s+(?:ports|rules)|peerings?|blast\s+radius|"
    r"impact\s+scope)\b|"
    r"(?:의존\s*관계|의존\s*리소스|dependency\s*경로|통신할\s*수|인바운드\s*포트|"
    r"피어링|영향을\s*받|영향\s*범위)",
    re.IGNORECASE,
)


def is_topology_question(prompt: str) -> bool:
    """Return whether the prompt requires exact topology selectors."""

    return bool(_TOPOLOGY_QUESTION.search(prompt))


__all__ = ["is_topology_question"]
