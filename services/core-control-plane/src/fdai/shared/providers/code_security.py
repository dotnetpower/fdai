"""Seam for projecting code-security review packages into Heimdall's Drift ownership."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol, runtime_checkable


@runtime_checkable
class CodeSecurityDriftProjector(Protocol):
    """Validate one code-security review package and return a no-authority drift payload."""

    def __call__(self, package: Mapping[str, object], /) -> dict[str, object]: ...


__all__ = ["CodeSecurityDriftProjector"]
