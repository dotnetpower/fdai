"""Fork-extensible read-only console panels.

The upstream console ships a deliberately **minimal** UI - three views
(KPI dashboard, audit log, HIL queue) served by the three core routes in
:mod:`fdai.delivery.read_api.main`. A fork that wants a richer,
vertical-specific surface (a FinOps cost dashboard, a Change-Safety drift
board, a DR-drill history) does **not** edit ``core/`` or the core routes.
Instead it implements the :class:`ReadPanel` Protocol and registers its
panels at the composition root via
:attr:`~fdai.delivery.read_api.main.ReadApiConfig.extra_panels`.

Seam contract
-------------
- A panel is **read-only**. :meth:`ReadPanel.render` returns a
  JSON-serializable mapping; there is no mutating back-channel. The app
  factory registers every panel as a ``GET``-only route, so the
  read-only invariant (``app-shape.instructions.md § Operator console``)
  holds for extensions exactly as it does for the core routes.
- A panel never sees the executor identity. Its route is authorized with
  the same reader-role gate as the core routes; approvals/actions still
  flow through ChatOps / remediation PRs, never a console button.
- ``path`` MUST start with ``/`` and MUST NOT collide with a core route
  (``/audit``, ``/kpi``, ``/hil-queue``, ``/healthz``). The app factory
  fails fast at build time on a malformed or colliding path.

This module also ships :class:`ExampleFinOpsPanel` as a **reference
implementation**. It is intentionally *not* registered by the upstream
default composition root (the upstream UI stays minimal); a fork opts in
by passing it (or its own panel) to ``ReadApiConfig.extra_panels``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol, runtime_checkable

from fdai.core.capability_catalog import (
    CapabilityCatalog,
    CapabilityCategory,
    default_capability_catalog,
)
from fdai.core.verticals.cost_governance.finops import FinOpsActionKind
from fdai.delivery.read_api.read_model import ConsoleReadModel, clamp_limit


class PanelQueryError(ValueError):
    """A caller-supplied panel query parameter failed validation."""


@runtime_checkable
class ReadPanel(Protocol):
    """A fork-supplied read-only console panel.

    Implementations are bound at the composition root and handed to the
    app factory. The factory wraps each panel in a ``GET``-only route
    that authorizes the caller and serializes :meth:`render`'s return
    value - the implementation only computes the payload.
    """

    @property
    def path(self) -> str:
        """Route path, e.g. ``"/finops"``. MUST start with ``/``."""
        ...

    @property
    def name(self) -> str:
        """Stable identifier for logs/metrics, e.g. ``"finops"``."""
        ...

    async def render(self, *, params: Mapping[str, str]) -> Mapping[str, Any]:
        """Return the panel payload as a JSON-serializable mapping.

        ``params`` carries the request query string (already parsed) so a
        panel MAY support filters/pagination. The return value MUST be
        JSON-serializable and MUST NOT expose secrets or a callable
        back-channel.
        """
        ...


# Cost-vertical action kinds, sourced from the FinOps vertical so the
# example panel stays in sync with the guardrail ontology.
_FINOPS_ACTION_KINDS: frozenset[str] = frozenset(kind.value for kind in FinOpsActionKind)


class ExampleFinOpsPanel:
    """Reference :class:`ReadPanel` - a minimal FinOps cost summary.

    Derives a small cost-vertical snapshot from the audit stream: how
    many cost actions ran, split by kind, plus a summed savings estimate
    pulled from each entry's optional ``estimated_savings`` field. It is
    intentionally simple - a fork's real dashboard would query a
    purpose-built read model (Cost Management pull, savings ledger)
    rather than re-deriving from audit. The point is to show the seam:
    implement ``ReadPanel``, register it, done.

    The panel is **not** wired by the upstream default composition root;
    it exists as copy-paste-ready guidance for forks.
    """

    def __init__(
        self,
        read_model: ConsoleReadModel,
        *,
        path: str = "/finops",
        sample_size: int = 500,
    ) -> None:
        if not path.startswith("/"):
            raise ValueError(f"ReadPanel path MUST start with '/', got {path!r}")
        self._read_model = read_model
        self._path = path
        self._sample_size = clamp_limit(sample_size)

    @property
    def path(self) -> str:
        return self._path

    @property
    def name(self) -> str:
        return "finops"

    async def render(self, *, params: Mapping[str, str]) -> Mapping[str, Any]:
        del params  # This reference panel takes no filters.
        page = await self._read_model.list_audit(limit=self._sample_size)
        by_kind: dict[str, int] = {}
        total_actions = 0
        estimated_monthly_savings = 0.0
        for item in page.items:
            if item.action_kind not in _FINOPS_ACTION_KINDS:
                continue
            total_actions += 1
            by_kind[item.action_kind] = by_kind.get(item.action_kind, 0) + 1
            savings = item.entry.get("estimated_savings")
            if isinstance(savings, (int, float)) and not isinstance(savings, bool):
                estimated_monthly_savings += float(savings)
        return {
            "vertical": "finops",
            "total_actions": total_actions,
            "by_kind": by_kind,
            "estimated_monthly_savings": round(estimated_monthly_savings, 2),
            "sampled_events": len(page.items),
        }


class CapabilityCatalogPanel:
    """Read-only panel projecting the capability catalog (slide 20).

    Renders the customer-agnostic
    :class:`~fdai.core.capability_catalog.CapabilityCatalog` so the console
    can show operators what FDAI can do, each capability's side-effect class,
    and its default autonomy mode. Pure projection - listing a capability
    grants no execution eligibility, and the payload is inert metadata.

    Supports an optional ``category`` query filter matching a
    :class:`~fdai.core.capability_catalog.CapabilityCategory` value.
    """

    def __init__(
        self,
        catalog: CapabilityCatalog | None = None,
        *,
        path: str = "/capabilities",
    ) -> None:
        if not path.startswith("/"):
            raise ValueError(f"ReadPanel path MUST start with '/', got {path!r}")
        self._catalog = catalog or default_capability_catalog()
        self._path = path

    @property
    def path(self) -> str:
        return self._path

    @property
    def name(self) -> str:
        return "capabilities"

    async def render(self, *, params: Mapping[str, str]) -> Mapping[str, Any]:
        requested = params.get("category")
        category: CapabilityCategory | None = None
        if requested:
            try:
                category = CapabilityCategory(requested)
            except ValueError:
                category = None
        items = (
            self._catalog.list(category=category) if category is not None else self._catalog.list()
        )
        return {
            "surface": "capabilities",
            "count": len(items),
            "capabilities": [
                {
                    "capability_id": cap.capability_id,
                    "name": cap.name,
                    "category": cap.category.value,
                    "summary": cap.summary,
                    "side_effect_class": cap.side_effect_class.value,
                    "default_mode": cap.default_mode.value,
                    "required_role": cap.required_role,
                    "slide_ref": cap.slide_ref,
                    "tags": list(cap.tags),
                }
                for cap in items
            ],
        }


__all__ = [
    "CapabilityCatalogPanel",
    "ExampleFinOpsPanel",
    "ReadPanel",
]
