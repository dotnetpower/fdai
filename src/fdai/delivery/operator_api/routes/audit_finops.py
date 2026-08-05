"""Compatibility shim for the owned audit FinOps projection.

Implementation lives in :mod:`fdai.delivery.operator_api.projections.audit`.
This module preserves the published route-era import path and owns no behavior.
"""

from fdai.delivery.operator_api.projections.audit.audit_finops import AuditFinOpsPanel

__all__ = ["AuditFinOpsPanel"]
