"""Request-local prompt policy shared by conversation transports."""

from __future__ import annotations

import re
from typing import Final

from fdai.delivery.operator_api.application.conversation.backend.contracts import (
    ChatContentPolicyError,
)

_DIRECT_OVERRIDE: Final = re.compile(
    r"\bignore\s+(?:all\s+)?(?:previous\s+)?(?:instructions?|rules?|system)\b"
    r"|\bdisregard\s+(?:all\s+)?(?:previous\s+)?(?:instructions?|rules?|system)\b"
    "|모든\\s+지시\\s+무시"
    "|이전\\s+지시\\s+무시",
    re.IGNORECASE,
)


def reject_direct_override(prompt: str) -> None:
    """Block explicit attempts to replace the trusted instruction hierarchy."""

    if _DIRECT_OVERRIDE.search(prompt):
        raise ChatContentPolicyError(stage="input")
