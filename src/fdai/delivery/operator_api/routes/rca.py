"""First-class read-only RCA (root-cause analysis) view panel.

Given an incident ``correlation_id``, projects the shadow
``rca.hypothesis`` audit entries into a grounded RCA view: the tiered
root-cause hypotheses (``T0`` direct / ``T1`` correlation / ``T2``
reasoning), their citations, and the linked response / remediation plan.

Read-only by construction (``app-shape.instructions.md`` § Operator
console): the panel is registered as a ``GET``-only route and renders a
JSON-serializable projection of the audit ledger. It never executes
anything - an RCA hypothesis answers "why", while execution eligibility
stays with the risk gate + verifier.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fdai.delivery.operator_api.read_model import (
    MAX_LIMIT,
    ConsoleReadModel,
)
from fdai.delivery.operator_api.routes.panels import PanelNotFoundError, PanelQueryError
from fdai.delivery.operator_api.routes.rca_projection import project_rca


class RcaPanel:
    """Project the audit ledger into a per-incident RCA view."""

    def __init__(self, read_model: ConsoleReadModel) -> None:
        self._read_model = read_model

    @property
    def path(self) -> str:
        return "/rca"

    @property
    def name(self) -> str:
        return "rca"

    async def render(self, *, params: Mapping[str, str]) -> Mapping[str, Any]:
        correlation = params.get("correlation") or params.get("correlation_id")
        if not correlation or not correlation.strip():
            raise PanelQueryError("correlation MUST be provided")
        correlation = correlation.strip()
        page = await self._read_model.list_audit(correlation_id=correlation, limit=MAX_LIMIT)
        if not page.items:
            raise PanelNotFoundError(f"no audit evidence for correlation {correlation!r}")
        view = project_rca(page.items, correlation_id=correlation)
        return view.to_dict()


__all__ = ["RcaPanel"]
