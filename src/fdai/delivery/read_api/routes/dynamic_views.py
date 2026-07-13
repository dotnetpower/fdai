"""Assemble optional reporting and Process view route families."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from starlette.requests import Request
from starlette.routing import Route

from fdai.delivery.read_api.routes.process_views import (
    ProcessViewsConfig,
    build_process_view_routes,
)
from fdai.delivery.read_api.routes.reporting import (
    ReportingConfig,
    build_reporting_routes,
)


def build_dynamic_view_routes(
    *,
    reporting: ReportingConfig | None,
    process_views: ProcessViewsConfig | None,
    authorize: Callable[[Request], Awaitable[str]],
    core_paths: frozenset[str],
    seen_extra_paths: set[str],
) -> list[Route]:
    routes: list[Route] = []
    if reporting is not None:
        routes.extend(
            build_reporting_routes(
                config=reporting,
                authorize=authorize,
                core_paths=core_paths,
                seen_extra_paths=seen_extra_paths,
            )
        )
    if process_views is not None:
        routes.extend(
            build_process_view_routes(
                config=process_views,
                authorize=authorize,
                core_paths=core_paths,
                seen_extra_paths=seen_extra_paths,
            )
        )
    return routes


def validate_route_method_collisions(routes: list[Route]) -> None:
    """Fail startup when two routes claim the same path and HTTP method."""
    claimed: dict[tuple[str, str], int] = {}
    for index, route in enumerate(routes):
        for method in route.methods or ():
            key = (route.path, method)
            if key in claimed:
                raise ValueError(
                    f"route {route.path!r} method {method!r} collides with an existing route"
                )
            claimed[key] = index


__all__ = ["build_dynamic_view_routes", "validate_route_method_collisions"]
