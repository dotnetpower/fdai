"""Local-only development diagnostic lifecycle binding for Core."""

from __future__ import annotations

from collections.abc import Mapping

from fdai_runtime_diagnostics import (
    DevelopmentDiagnosticsConfig,
    DevelopmentDiagnosticServer,
)


def build_development_diagnostics(
    environment: Mapping[str, str],
    *,
    runtime_scope_receipt_digest: str | None,
) -> DevelopmentDiagnosticServer | None:
    """Build an explicit local probe or fail closed on a partial binding."""
    enabled = environment.get("FDAI_DEVELOPMENT_DIAGNOSTICS", "").strip().lower()
    if enabled not in {"1", "true"}:
        return None
    if runtime_scope_receipt_digest is None:
        raise ValueError("development diagnostics require a runtime scope receipt")
    config = DevelopmentDiagnosticsConfig.from_environment(
        "core-control-plane",
        runtime_scope_receipt_digest,
        environment,
    )
    if config is None:  # pragma: no cover - guarded by explicit enabled state
        raise ValueError("development diagnostics configuration is unavailable")
    return DevelopmentDiagnosticServer(config)


__all__ = ["build_development_diagnostics"]
