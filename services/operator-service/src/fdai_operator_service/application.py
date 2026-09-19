"""Application lifecycle boundary for the independent Operator service."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace

from fdai_operator_service.composition import (
    OperatorComposition,
    ProductionOperatorComposition,
    compose_application_lifecycle,
)
from fdai_operator_service.contracts import AsgiApplication
from fdai_operator_service.development_diagnostics import build_development_diagnostics


def create_app(
    environ: Mapping[str, str] | None = None,
    *,
    composition: OperatorComposition | None = None,
) -> AsgiApplication:
    """Build the configured production application through injected dependencies."""
    selected = composition or ProductionOperatorComposition()
    runtime = selected.build_runtime(environ)
    lifecycle = compose_application_lifecycle(
        runtime.lifecycle,
        build_development_diagnostics(runtime.environment.values),
    )
    return replace(runtime, lifecycle=lifecycle).create_app()
