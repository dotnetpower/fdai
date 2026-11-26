"""Provider-schema review projection boundary for sensing agents."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol, runtime_checkable


@runtime_checkable
class ProviderSchemaDriftProjector(Protocol):
    """Validate one provider review package and return a no-authority drift payload."""

    def __call__(self, package: Mapping[str, object], /) -> dict[str, object]: ...


__all__ = ["ProviderSchemaDriftProjector"]
