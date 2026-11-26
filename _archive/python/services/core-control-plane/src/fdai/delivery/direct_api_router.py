"""ActionType router for independently bound direct-API adapters."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from fdai.shared.providers.direct_api import (
    DirectApiExecutor,
    DirectApiPreconditionError,
    DirectApiReceipt,
    DirectApiRequest,
)


@dataclass(frozen=True, slots=True)
class RoutedDirectApiExecutor:
    routes: Mapping[str, DirectApiExecutor]
    identity_routes: Mapping[str, DirectApiExecutor] = field(default_factory=dict)
    fallback: DirectApiExecutor | None = None

    def __post_init__(self) -> None:
        if not self.routes and not self.identity_routes and self.fallback is None:
            raise ValueError("direct-API router requires a route or fallback")
        if any(
            not action_type.strip() or action_type != action_type.strip() or len(action_type) > 256
            for action_type in self.routes
        ):
            raise ValueError("direct-API route names MUST be non-empty")
        object.__setattr__(self, "routes", MappingProxyType(dict(self.routes)))
        if any(not identity.strip() for identity in self.identity_routes):
            raise ValueError("direct-API identity route names MUST be non-empty")
        object.__setattr__(
            self,
            "identity_routes",
            MappingProxyType(dict(self.identity_routes)),
        )

    async def execute(self, request: DirectApiRequest) -> DirectApiReceipt:
        executor = self.routes.get(request.action_type_name)
        identity_ref = request.metadata.get("executor_identity_ref")
        if executor is None and identity_ref is not None:
            executor = self.identity_routes.get(identity_ref)
            if executor is None:
                raise DirectApiPreconditionError(
                    f"no direct-API adapter is registered for executor identity {identity_ref}"
                )
        if executor is None:
            executor = self.fallback
        if executor is None:
            raise DirectApiPreconditionError(
                f"no direct-API adapter is registered for {request.action_type_name}"
            )
        return await executor.execute(request)


__all__ = ["RoutedDirectApiExecutor"]
