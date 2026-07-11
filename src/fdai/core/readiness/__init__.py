"""Operational Readiness Review - the dev-to-ops handoff gate.

The ORR binds the whole-scope [assurance-twin](../assurance_twin) posture
assessment and the [deploy-preflight](../deploy_preflight) feasibility pass to a
single ``ownership_transfer`` event and returns one verdict - ``clear`` /
``needs_review`` / ``blocked`` - so nothing crosses the dev-to-ops boundary
un-reviewed. Full design:
``docs/roadmap/operations/operational-readiness.md``.

This package holds only the CSP-neutral machinery and the generic
:class:`ReadinessReport` shape (a fork supplies the trigger label, the
required-rule set, and the gating severity). It imports only ``shared/``
contracts and the two existing report types; it holds no cloud SDK and no
privileged identity, and it executes nothing - every proposed fix flows through
``risk-gate -> executor`` like any other action.
"""

from __future__ import annotations

from fdai.core.readiness.coordinator import compose_readiness_report
from fdai.core.readiness.report import (
    HandoffVerdict,
    ReadinessFinding,
    ReadinessReport,
)
from fdai.core.readiness.signal import OwnershipTransfer

__all__ = [
    "HandoffVerdict",
    "OwnershipTransfer",
    "ReadinessFinding",
    "ReadinessReport",
    "compose_readiness_report",
]
