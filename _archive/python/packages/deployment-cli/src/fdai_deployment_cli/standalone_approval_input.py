"""Bounded interactive-input readiness for standalone plan approval."""

from __future__ import annotations

import select
import sys


def wait_for_approval_input(timeout_seconds: int) -> None:
    """Wait only on a real terminal within the invocation's remaining budget."""

    if timeout_seconds <= 0:
        raise TimeoutError("standalone approval deadline expired; no approval was granted")
    if not sys.stdin.isatty():
        raise ValueError("standalone approval requires an interactive terminal")
    try:
        readable, _, _ = select.select([sys.stdin], [], [], timeout_seconds)
    except (OSError, ValueError):
        raise ValueError("standalone approval input is unavailable") from None
    if not readable:
        raise TimeoutError("standalone approval input timed out; no approval was granted")


__all__ = ["wait_for_approval_input"]
