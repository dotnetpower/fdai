"""Ontology-driven recovery planning, readiness, and verification."""

from fdai.core.recovery.compiler import (
    compile_recovery_plan,
    reverse_topological_compensation,
)
from fdai.core.recovery.control import (
    PreauthorizedRecoveryController,
    RecoveryActionDispatcher,
    RecoveryControlResult,
)
from fdai.core.recovery.models import (
    ProbeVerdict,
    RecoveryAction,
    RecoveryPlanRecord,
    RecoveryPlanStatus,
    RecoveryProbeKind,
    RecoveryProbeResult,
    RecoveryReadiness,
    RecoveryStrategy,
    RecoveryVerification,
    RecoveryVerificationOutcome,
)
from fdai.core.recovery.projection import RecoveryPlanProjector
from fdai.core.recovery.readiness import evaluate_recovery_readiness, preauthorization_covers
from fdai.core.recovery.verification import verify_recovery_postconditions

__all__ = [
    "compile_recovery_plan",
    "evaluate_recovery_readiness",
    "PreauthorizedRecoveryController",
    "preauthorization_covers",
    "ProbeVerdict",
    "RecoveryAction",
    "RecoveryActionDispatcher",
    "RecoveryControlResult",
    "RecoveryPlanRecord",
    "RecoveryPlanProjector",
    "RecoveryPlanStatus",
    "RecoveryProbeKind",
    "RecoveryProbeResult",
    "RecoveryReadiness",
    "RecoveryStrategy",
    "RecoveryVerification",
    "RecoveryVerificationOutcome",
    "reverse_topological_compensation",
    "verify_recovery_postconditions",
]
