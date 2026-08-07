"""Pure intent classifiers shared by conversation application services."""

from __future__ import annotations

import re
from typing import Final

_TOPOLOGY_QUESTION: Final = re.compile(
    r"\b(?:dependencies|dependency\s+path|trace\s+the\s+path|reach|end\s+to\s+end|"
    r"resource\s+relationships?|inbound\s+(?:ports|rules?|traffic)|peerings?|peered|"
    r"blast\s+radius|impact\s+scope|dependent\s+resources?.{0,32}affected)"
    r"(?![A-Za-z0-9_])|"
    r"(?:의존\s*관계|의존\s*리소스|dependency\s*경로|통신할\s*수|인바운드\s*포트|"
    r"인바운드.{0,24}(?:rule|포트|열려)|피어링|영향(?:을)?\s*받|영향\s*범위)",
    re.IGNORECASE,
)


def is_topology_question(prompt: str) -> bool:
    """Return whether the prompt requires exact topology selectors."""

    return bool(_TOPOLOGY_QUESTION.search(prompt))


__all__ = ["is_topology_question"]
