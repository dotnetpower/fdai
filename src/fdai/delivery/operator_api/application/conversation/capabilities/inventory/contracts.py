"""Provider-neutral contracts for conversation inventory reads."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any, Final, Protocol, TypeGuard

_RESOURCE_NAME: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.()-]{1,127}$")


class InventoryGraphProvider(Protocol):
    """Read one bounded inventory graph projection."""

    async def __call__(
        self,
        scope: str | None,
        depth: int,
        link_types: tuple[str, ...],
        *,
        root: str | None = None,
        limit: int = 500,
    ) -> Mapping[str, Any]: ...


def is_bounded_resource_name(value: object) -> TypeGuard[str]:
    """Return whether a selector value is a bounded resource name."""

    return isinstance(value, str) and _RESOURCE_NAME.fullmatch(value) is not None


__all__ = ["InventoryGraphProvider", "is_bounded_resource_name"]
