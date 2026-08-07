"""Application lifecycle boundary for the independent Operator service."""

from __future__ import annotations

from collections.abc import Mapping

from fdai_operator_service.composition import OperatorComposition, ProductionOperatorComposition
from fdai_operator_service.contracts import AsgiApplication


def create_app(
    environ: Mapping[str, str] | None = None,
    *,
    composition: OperatorComposition | None = None,
) -> AsgiApplication:
    """Build the configured production application through injected dependencies."""
    selected = composition or ProductionOperatorComposition()
    return selected.build_runtime(environ).create_app()
