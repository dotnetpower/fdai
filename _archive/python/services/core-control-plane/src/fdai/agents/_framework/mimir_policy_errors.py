"""Shared policy-administration errors for Mimir helpers."""

from __future__ import annotations


class PolicyRevisionRejectedError(ValueError):
    """Raised when Mimir rejects a policy revision before activation."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


__all__ = ["PolicyRevisionRejectedError"]
