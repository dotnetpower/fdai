"""Local-only development diagnostic lifecycle binding for Operator."""

from __future__ import annotations

from collections.abc import Mapping

from fdai_runtime_diagnostics import (
    DevelopmentDiagnosticsConfig,
    DevelopmentDiagnosticServer,
)


def build_development_diagnostics(
    environment: Mapping[str, str],
) -> DevelopmentDiagnosticServer | None:
    """Build an explicit local probe or fail closed on a partial binding."""
    enabled = environment.get("FDAI_DEVELOPMENT_DIAGNOSTICS", "").strip().lower()
    if enabled not in {"1", "true"}:
        return None
    receipt_digest = environment.get("FDAI_RUNTIME_SCOPE_RECEIPT_DIGEST", "")
    config = DevelopmentDiagnosticsConfig.from_environment(
        "operator-service",
        receipt_digest,
        environment,
    )
    if config is None:  # pragma: no cover - guarded by explicit enabled state
        raise ValueError("development diagnostics configuration is unavailable")
    return DevelopmentDiagnosticServer(config)


__all__ = ["build_development_diagnostics"]
