"""Production composition for the standalone typed RPC surface."""

from __future__ import annotations

from dataclasses import dataclass

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from fdai.core.conversation import RuntimeToolDiscovery
from fdai.core.rpc import RpcIdempotencyStore, RpcMethod, RpcRegistry
from fdai.core.rpc.skill_discovery import skill_discovery_rpc_methods
from fdai.core.rpc.tool_discovery import tool_discovery_rpc_methods
from fdai.core.skills import RuntimeSkillDisclosure
from fdai.delivery.persistence.postgres_rpc_idempotency import (
    PostgresRpcIdempotencyStore,
    PostgresRpcIdempotencyStoreConfig,
)
from fdai.delivery.rpc.http import RpcAuthorization, make_rpc_route


@dataclass(frozen=True, slots=True)
class ProductionRpcConfig:
    dsn: str
    path: str = "/rpc"
    statement_timeout_ms: int = 15_000
    connect_timeout_s: int = 10

    def __post_init__(self) -> None:
        if not self.dsn:
            raise ValueError("ProductionRpcConfig.dsn MUST NOT be empty")
        if not self.path.startswith("/") or self.path == "/healthz":
            raise ValueError("ProductionRpcConfig.path MUST be a non-health absolute path")
        if self.statement_timeout_ms < 1 or self.connect_timeout_s < 1:
            raise ValueError("ProductionRpcConfig timeouts MUST be positive")


def build_production_rpc_app(
    *,
    config: ProductionRpcConfig,
    discovery: RuntimeToolDiscovery,
    authorize: RpcAuthorization,
    additional_methods: tuple[RpcMethod, ...] = (),
    idempotency_store: RpcIdempotencyStore | None = None,
    skill_disclosure: RuntimeSkillDisclosure | None = None,
) -> Starlette:
    """Build an opt-in RPC app with explicit methods and durable side-effect claims."""
    store = idempotency_store or PostgresRpcIdempotencyStore(
        config=PostgresRpcIdempotencyStoreConfig(
            dsn=config.dsn,
            statement_timeout_ms=config.statement_timeout_ms,
            connect_timeout_s=config.connect_timeout_s,
        )
    )
    registry = RpcRegistry(idempotency_store=store)
    skill_methods = (
        () if skill_disclosure is None else skill_discovery_rpc_methods(skill_disclosure)
    )
    for method in (*tool_discovery_rpc_methods(discovery), *skill_methods, *additional_methods):
        registry = registry.register(method)

    async def healthz(_request: Request) -> Response:
        return JSONResponse({"status": "ok"})

    app = Starlette(
        routes=[
            Route("/healthz", healthz, methods=["GET"]),
            make_rpc_route(registry=registry, authorize=authorize, path=config.path),
        ]
    )
    app.state.rpc_registry = registry
    return app


__all__ = ["ProductionRpcConfig", "build_production_rpc_app"]
