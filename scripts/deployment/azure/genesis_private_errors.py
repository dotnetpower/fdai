#!/usr/bin/env python3
"""Stable failures for the composed private Genesis lifecycle."""

from __future__ import annotations


class PrivateExecutionError(RuntimeError):
    """Carry a private-stage failure without exposing child diagnostics."""

    def __init__(self, stage: str, reason_code: str, exit_code: int = 4) -> None:
        super().__init__(reason_code)
        self.stage = stage
        self.reason_code = reason_code
        self.exit_code = exit_code


class PrivateExecutionWaitError(RuntimeError):
    """Stop safely at one exact prerequisite or human-approval checkpoint."""

    def __init__(self, stage: str, reason_code: str, next_action: str) -> None:
        super().__init__(reason_code)
        self.stage = stage
        self.reason_code = reason_code
        self.next_action = next_action
