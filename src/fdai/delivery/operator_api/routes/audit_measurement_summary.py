"""Compatibility shim for the audit autonomy measurement panel.

Implementation lives in :mod:`fdai.delivery.operator_api.projections.audit`.
This module preserves the published route-era import path and owns no behavior.
"""

from fdai.delivery.operator_api.projections.audit.audit_measurement_summary import (
    AuditAutonomyMeasurementPanel,
)

__all__ = ["AuditAutonomyMeasurementPanel"]
