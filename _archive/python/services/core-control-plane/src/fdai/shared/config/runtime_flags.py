"""Shared runtime feature-activation flags."""

from __future__ import annotations

from collections.abc import Mapping

_FALSE_VALUES = frozenset({"0", "false", "no", "off"})


def pantheon_start_enabled(environ: Mapping[str, str]) -> bool:
    """Start all agents unless the operator explicitly disables the runtime."""
    raw = environ.get("FDAI_START_PANTHEON", "").strip().casefold()
    return raw not in _FALSE_VALUES


__all__ = ["pantheon_start_enabled"]
