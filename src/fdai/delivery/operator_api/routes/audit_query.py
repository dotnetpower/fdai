"""Compatibility shim for bounded audit query parsing.

Implementation lives in :mod:`fdai.delivery.operator_api.projections.audit`.
This module preserves the published route-era import path and owns no behavior.
"""

from fdai.delivery.operator_api.projections.audit.audit_query import (
    AuditQueryError,
    parse_audit_filters,
)

__all__ = ["AuditQueryError", "parse_audit_filters"]
