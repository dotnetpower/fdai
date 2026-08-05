"""Assemble optional reporting and Process view route families."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from starlette.requests import Request
from starlette.routing import BaseRoute, Route

from fdai.delivery.operator_api.routes.process_views import (
    ProcessViewsConfig,
    build_process_view_routes,
)
from fdai.delivery.operator_api.routes.reporting import (
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


def validate_route_method_collisions(routes: list[BaseRoute]) -> None:
    """Fail startup when two routes claim the same path and HTTP method."""
    claimed: dict[tuple[str, str], int] = {}
    for index, route in enumerate(routes):
        if not isinstance(route, Route):
            continue
        for method in route.methods or ():
            key = (route.path, method)
            if key in claimed:
                raise ValueError(
                    f"route {route.path!r} method {method!r} collides with an existing route"
                )
            claimed[key] = index


def validate_panel_path_collisions(
    routes: list[BaseRoute],
    panel_paths: set[str],
) -> None:
    """Fail startup when another route claims an extension panel's path."""
    path_counts: dict[str, int] = {path: 0 for path in panel_paths}
    for route in routes:
        if isinstance(route, Route) and route.path in path_counts:
            path_counts[route.path] += 1
    collisions = sorted(path for path, count in path_counts.items() if count != 1)
    if collisions:
        raise ValueError(f"panel paths collide with another route or are missing: {collisions}")


__all__ = [
    "build_dynamic_view_routes",
    "validate_panel_path_collisions",
    "validate_route_method_collisions",
]
