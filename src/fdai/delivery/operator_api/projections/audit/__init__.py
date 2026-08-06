"""Audit query and measurement read-projection facade.

Responsibility:
Expose the cohesive audit projection family through one lazy public package.

Boundary:
Own no route registration, authorization, CORS, lifespan, or persistence.

Authority and state:
Read-only, with no approval or execution authority. State and provenance come
from the injected Operator API read model.

Dependencies:
Focused audit projection modules loaded only for requested public symbols.

Deployment:
Used by app and panel composition while route shims preserve older imports.
"""

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from fdai.delivery.operator_api.projections.audit.audit_finops import AuditFinOpsPanel
    from fdai.delivery.operator_api.projections.audit.audit_measurement_summary import (
        AuditAutonomyMeasurementPanel,
    )
    from fdai.delivery.operator_api.projections.audit.audit_query import (
        AuditQueryError,
        parse_audit_filters,
    )

__all__ = [
    "AuditAutonomyMeasurementPanel",
    "AuditFinOpsPanel",
    "AuditQueryError",
    "parse_audit_filters",
]


def __getattr__(name: str) -> Any:
    """Load only the explicitly requested public audit symbol."""
    if name == "AuditFinOpsPanel":
        from fdai.delivery.operator_api.projections.audit.audit_finops import AuditFinOpsPanel

        return AuditFinOpsPanel
    if name == "AuditAutonomyMeasurementPanel":
        from fdai.delivery.operator_api.projections.audit.audit_measurement_summary import (
            AuditAutonomyMeasurementPanel,
        )

        return AuditAutonomyMeasurementPanel
    if name in {"AuditQueryError", "parse_audit_filters"}:
        from fdai.delivery.operator_api.projections.audit.audit_query import (
            AuditQueryError,
            parse_audit_filters,
        )

        return {
            "AuditQueryError": AuditQueryError,
            "parse_audit_filters": parse_audit_filters,
        }[name]
    raise AttributeError(name)
