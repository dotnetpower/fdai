"""Service-local dependency and ASGI contracts for Operator composition."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, MutableMapping
from typing import Any, Protocol

type AsgiScope = MutableMapping[str, Any]
type AsgiMessage = MutableMapping[str, Any]
type AsgiReceive = Callable[[], Awaitable[AsgiMessage]]
type AsgiSend = Callable[[AsgiMessage], Awaitable[None]]


class AsgiApplication(Protocol):
    """Handle one ASGI connection without exposing a framework implementation."""

    def __call__(
        self,
        scope: AsgiScope,
        receive: AsgiReceive,
        send: AsgiSend,
    ) -> Awaitable[None]: ...


class ApplicationFactory(Protocol):
    """Build one Operator ASGI application from an environment snapshot."""

    def __call__(self, environ: Mapping[str, str]) -> AsgiApplication: ...


class ApplicationFactoryResolver(Protocol):
    """Resolve a configured application factory by reference."""

    def __call__(self, reference: str) -> ApplicationFactory: ...


class ServerRunner(Protocol):
    """Run an ASGI factory until process shutdown."""

    def __call__(
        self,
        factory_reference: str,
        *,
        factory: bool,
        host: str,
        port: int,
    ) -> object: ...
