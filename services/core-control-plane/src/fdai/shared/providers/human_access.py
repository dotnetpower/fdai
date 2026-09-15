"""Compatibility imports for the implementation-free shared membership contracts."""

from fdai_service_contracts.human_access import (
    HumanAccessOperation,
    HumanAccessOutcome,
    HumanAccessPlan,
    HumanAccessProvisioner,
    HumanAccessReceipt,
    parse_human_access_role_groups,
)

__all__ = [
    "HumanAccessOperation",
    "HumanAccessOutcome",
    "HumanAccessPlan",
    "HumanAccessProvisioner",
    "HumanAccessReceipt",
    "parse_human_access_role_groups",
]
