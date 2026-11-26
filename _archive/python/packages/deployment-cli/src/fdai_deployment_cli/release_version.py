"""Validate immutable Release identifiers used by deployment publications."""

from __future__ import annotations

import re

_PRERELEASE_IDENTIFIER = r"(?:0|[1-9][0-9]*|[0-9A-Za-z-]*[A-Za-z-][0-9A-Za-z-]*)"
_RELEASE_VERSION = re.compile(
    r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    rf"(?:-{_PRERELEASE_IDENTIFIER}(?:\.{_PRERELEASE_IDENTIFIER})*)?\Z",
    re.ASCII,
)


def canonical_release_version(value: object, *, context: str) -> str:
    """Return one bounded canonical SemVer without build metadata."""

    if not isinstance(value, str) or len(value) > 64 or _RELEASE_VERSION.fullmatch(value) is None:
        raise ValueError(f"{context} MUST be canonical SemVer")
    return value


__all__ = ["canonical_release_version"]
