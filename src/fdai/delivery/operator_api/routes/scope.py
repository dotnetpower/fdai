"""Read-only ``GET /scope`` route - effective monitoring / action scope.

Projects the governance scope (which subscriptions / resource groups FDAI
**observes**, and which an autonomous action may **touch**) into a
read-only console view. Two axes are kept distinct because they map to
different mechanisms: observation targets vs the risk-gate blast-radius +
governance bindings guarded by the RG-scoped executor identity.

This surface is **strictly read-only** (``app-shape.instructions.md`` §
Operator console). It renders the effective scope and the hard executor
IAM boundary; it never writes scope. Authoring a scope change is a
policy-as-code artifact the operator submits as a remediation / config PR
(GitOps), never a console button - the console builder generates the
artifact text client-side.

Composes the existing CSP-neutral scope schema
(:class:`fdai.rule_catalog.schema.scope.ScopeBinding` /
:class:`~fdai.rule_catalog.schema.scope.ScopeRef`); it introduces no
parallel scope model. Registered by
:func:`~fdai.delivery.operator_api.main.build_app` only when
:attr:`~fdai.delivery.operator_api.main.OperatorApiConfig.scope_source` is set.
Reader-role gate; GET-only.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any, Literal, Protocol, runtime_checkable

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import BaseRoute, Route

from fdai.rule_catalog.schema.scope import ScopeBinding, ScopeLevel, ScopeRef

DEFAULT_ROUTE_PATH = "/scope"

ScopeAxisName = Literal["monitoring", "action"]
ScopeEntryState = Literal["included", "excluded"]
ScopeEntryLevel = Literal["subscription", "resource_group"]

_LEVEL_LABEL: dict[ScopeLevel, ScopeEntryLevel] = {
    ScopeLevel.ACCOUNT: "subscription",
    ScopeLevel.RESOURCE_GROUP: "resource_group",
}


@dataclass(frozen=True, slots=True)
class ScopeEntry:
    """One in-scope or excluded subscription / resource-group address.

    ``address`` is the canonical ``scope://`` URI
    (:meth:`fdai.rule_catalog.schema.scope.ScopeRef.render`). ``subscription``
    and ``resource_group`` are the decoded hierarchy segments so the console
    can render a table without re-parsing the URI.
    """

    address: str
    level: ScopeEntryLevel
    subscription: str
    resource_group: str | None
    state: ScopeEntryState

    def to_dict(self) -> dict[str, Any]:
        return {
            "address": self.address,
            "level": self.level,
            "subscription": self.subscription,
            "resource_group": self.resource_group,
            "state": self.state,
        }


@dataclass(frozen=True, slots=True)
class ScopeAxis:
    """One scope axis (monitoring or automated-action) as include/exclude entries."""

    axis: ScopeAxisName
    entries: tuple[ScopeEntry, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "axis": self.axis,
            "entries": [entry.to_dict() for entry in self.entries],
        }


@dataclass(frozen=True, slots=True)
class ExecutorBoundary:
    """Read-only reflection of the hard executor IAM ceiling.

    The executor is an RG-scoped, action-whitelisted managed identity
    (``infra/main.tf``). No governance scope can widen it, so the console
    surfaces it alongside the soft monitoring / action scope to make the
    hard limit visible. ``resource_groups`` are the RGs the executor
    identity is scoped to.
    """

    resource_groups: tuple[str, ...]
    note: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "resource_groups": list(self.resource_groups),
            "note": self.note,
        }


@dataclass(frozen=True, slots=True)
class EffectiveScopeView:
    """The effective monitoring + action scope plus the executor boundary."""

    monitoring: ScopeAxis
    action: ScopeAxis
    executor_boundary: ExecutorBoundary

    def to_dict(self) -> dict[str, Any]:
        return {
            "monitoring": self.monitoring.to_dict(),
            "action": self.action.to_dict(),
            "executor_boundary": self.executor_boundary.to_dict(),
        }


@runtime_checkable
class ScopeSource(Protocol):
    """Async provider of the effective scope view.

    Bound at the composition root. Upstream ships :class:`StaticScopeSource`
    (config-driven); a fork can compute the effective scope from live
    governance bindings + inventory. Async because a real backend queries
    state.
    """

    async def effective_scope(self) -> EffectiveScopeView:
        """Return the current effective monitoring / action scope."""
        ...


@dataclass(frozen=True, slots=True)
class StaticScopeSource(ScopeSource):
    """A :class:`ScopeSource` backed by a fixed, config-supplied view."""

    view: EffectiveScopeView

    async def effective_scope(self) -> EffectiveScopeView:
        return self.view


def project_scope_axis(axis: ScopeAxisName, binding: ScopeBinding) -> ScopeAxis:
    """Project a :class:`ScopeBinding` into a console scope axis.

    Only subscription- (``ACCOUNT``) and resource-group-level addresses are
    surfaced - the granularity this UI edits. An organization- or
    resource-level address raises ``ValueError`` so an out-of-granularity
    binding is caught at build time, not rendered ambiguously.
    """
    entries = tuple(_project_entry(ref, "included") for ref in binding.includes) + tuple(
        _project_entry(ref, "excluded") for ref in binding.excludes
    )
    return ScopeAxis(axis=axis, entries=entries)


def _project_entry(ref: ScopeRef, state: ScopeEntryState) -> ScopeEntry:
    level = ref.level
    label = _LEVEL_LABEL.get(level)
    if label is None:
        raise ValueError(
            f"scope address {ref.render()!r} MUST be subscription- or "
            f"resource-group-level for the console scope view"
        )
    segments = ref.segments
    subscription = segments[ScopeLevel.ACCOUNT]
    resource_group = (
        segments[ScopeLevel.RESOURCE_GROUP] if level >= ScopeLevel.RESOURCE_GROUP else None
    )
    return ScopeEntry(
        address=ref.render(),
        level=label,
        subscription=subscription,
        resource_group=resource_group,
        state=state,
    )


def make_scope_route(
    *,
    source: ScopeSource,
    authorize: Callable[[Request], Awaitable[str]],
    path: str = DEFAULT_ROUTE_PATH,
) -> Route:
    """Return a Starlette :class:`Route` serving the effective-scope view."""

    async def handler(request: Request) -> Response:
        await authorize(request)
        view = await source.effective_scope()
        return JSONResponse(view.to_dict())

    return Route(path, handler, methods=["GET"])


def append_scope_route(
    routes: list[BaseRoute],
    source: ScopeSource | None,
    authorize: Callable[[Request], Awaitable[str]],
    core_paths: frozenset[str],
    panel_paths: set[str],
) -> None:
    """Fail-fast register ``GET /scope`` onto ``routes`` when ``source`` is set.

    No-op when ``source`` is ``None`` so the app factory stays a one-liner.
    Keeps the composition root (``main.py``) slim: the collision check and
    route construction live here, not inline in the app factory.
    """
    if source is None:
        return
    if DEFAULT_ROUTE_PATH in core_paths or DEFAULT_ROUTE_PATH in panel_paths:
        raise ValueError(f"scope path {DEFAULT_ROUTE_PATH!r} collides with another route")
    routes.append(make_scope_route(source=source, authorize=authorize))


def build_scope_view(
    *,
    monitoring: ScopeBinding,
    action: ScopeBinding,
    executor_resource_groups: Sequence[str],
    executor_note: str | None = None,
) -> EffectiveScopeView:
    """Convenience: compose an :class:`EffectiveScopeView` from two bindings.

    Reuses :class:`ScopeBinding` for both axes so the console view never
    invents a parallel scope model.
    """
    return EffectiveScopeView(
        monitoring=project_scope_axis("monitoring", monitoring),
        action=project_scope_axis("action", action),
        executor_boundary=ExecutorBoundary(
            resource_groups=tuple(executor_resource_groups),
            note=executor_note,
        ),
    )


__all__ = [
    "DEFAULT_ROUTE_PATH",
    "EffectiveScopeView",
    "ExecutorBoundary",
    "ScopeAxis",
    "ScopeEntry",
    "ScopeSource",
    "StaticScopeSource",
    "append_scope_route",
    "build_scope_view",
    "make_scope_route",
    "project_scope_axis",
]
