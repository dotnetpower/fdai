"""Compatibility shim for audit autonomy payload aggregation.

Implementation lives in :mod:`fdai.delivery.operator_api.projections.audit`.
This module preserves the published route-era import path and owns no behavior.
"""

from fdai.delivery.operator_api.projections.audit.audit_measurement_projection import (
    audit_payload,
)

__all__ = ["audit_payload"]
