"""Compatibility imports for focused workflow catalog projections."""

from fdai_operator_service.workflow_framework_projection import (
    _caf_catalog_payload,
    _mcsb_catalog_payload,
    _wara_catalog_payload,
)
from fdai_operator_service.workflow_rule_projection import (
    _best_practice_catalog_payload,
    _promotion_gate_payload,
    _rule_catalog_payload,
    _rule_findings_summary_payload,
    rule_activation_history_payload,
    rule_activation_status_payload,
)

__all__ = [
    "_best_practice_catalog_payload",
    "_caf_catalog_payload",
    "_mcsb_catalog_payload",
    "_promotion_gate_payload",
    "_rule_catalog_payload",
    "_rule_findings_summary_payload",
    "_wara_catalog_payload",
    "rule_activation_history_payload",
    "rule_activation_status_payload",
]
