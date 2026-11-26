#!/usr/bin/env python3
"""Run bounded read-only Azure deployment checks from the protected runner."""

from live_preflight.cli import main
from live_preflight.runner import run_preflight
from live_preflight.transport import PreflightError

__all__ = ["PreflightError", "main", "run_preflight"]


if __name__ == "__main__":
    raise SystemExit(main())
