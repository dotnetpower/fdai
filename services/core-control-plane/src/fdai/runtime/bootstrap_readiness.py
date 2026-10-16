"""Operational Readiness runtime composition."""

from __future__ import annotations

from fdai.composition import Container
from fdai.composition.readiness import (
    OperationalReadinessEventHandler,
    build_operational_readiness_event_handler,
)
from fdai.composition.readiness_catalog import load_runtime_best_practice_bindings
from fdai.core.notifications.matrix import load_matrix_from_yaml
from fdai.core.readiness.self_health import SelfHealthCatalog, load_self_health_catalog
from fdai.runtime.configuration import _resolve_catalog_root
from fdai.shared.providers.state_store import StateStore


def load_runtime_self_health_catalog() -> SelfHealthCatalog:
    """Load self-health policy with the notification matrix's fallback routes."""

    config_root = _resolve_catalog_root().parent / "config"
    matrix = load_matrix_from_yaml(config_root / "notifications-matrix.yaml")
    route_fallbacks = {name: route.on_all_fail.value for name, route in matrix.routes.items()}
    return load_self_health_catalog(
        config_root / "self-health-signals.yaml",
        route_fallbacks=route_fallbacks,
    )


def build_runtime_operational_readiness(
    *,
    container: Container,
    state_store: StateStore,
) -> OperationalReadinessEventHandler | None:
    """Build the optional complete ORR runtime binding."""

    best_practices, checklist_evidence = load_runtime_best_practice_bindings(
        _resolve_catalog_root()
    )
    return build_operational_readiness_event_handler(
        posture=container.operational_readiness_posture,
        publisher=container.operational_readiness_report_publisher,
        feasibility_probes=container.feasibility_probes,
        event_validator=container.event_validator,
        state_store=state_store,
        decision_evidence=container.decision_evidence_admission_provider,
        best_practices=best_practices,
        checklist_evidence=checklist_evidence,
        remediation_binding=container.operational_readiness_remediation,
    )


__all__ = ["build_runtime_operational_readiness", "load_runtime_self_health_catalog"]
