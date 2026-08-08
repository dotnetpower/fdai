"""ControlLoop orchestrator package (G-2, tracker #14).

The 1725-LOC ``core/control_loop.py`` monolith becomes a package. The
``ControlLoop`` class stays in :mod:`.orchestrator`; the module-level
helpers (resource-prop extraction, environment classification, unified
authority computation, audit-record shaping) live in
:mod:`._helpers`, typed terminal results live in :mod:`.models`, and the
authoritative operator proposal path lives in :mod:`.operator_request`.

Public API preserved via re-export: callers continue to
``from fdai.core.control_loop import ControlLoop, ControlLoopResult,
ControlLoopOutcome`` unchanged.

**Follow-up scope:** the tracker's ideal state is a ``Stage`` protocol
with one stage per pipeline step (route / evaluate_tier / quality_gate
/ risk_gate / hil_park / execute / audit / notify). Extracting the
``ControlLoop.process`` method (~411 LOC) into stages is a **separate,
larger surgery** deliberately not attempted in this commit - it
requires reworking the internal method dependencies (shared state on
``self``, dispatch/notify sequencing, HIL-approval fan-out) without
regressing any of the 5,200+ existing integration tests. This package
layout is the enabling step: once the helpers extract cleanly, the
Stage refactor can extract one stage at a time from ``orchestrator.py``
without touching ``__init__.py`` or ``_helpers.py``.
"""

from __future__ import annotations

from fdai.core.control_loop._helpers import (
    _compute_authority,
    _extract_environment,
    _extract_resource_id,
    _extract_resource_props,
    _is_execution_success,
    _synthetic_action_build_failure,
    _unified_audit_dict,
    build_shadow_authority_audit,
    build_unified_risk_audit,
    evaluate_unified,
)
from fdai.core.control_loop.models import ControlLoopOutcome, ControlLoopResult
from fdai.core.control_loop.orchestrator import ControlLoop

__all__ = [
    "ControlLoop",
    "ControlLoopOutcome",
    "ControlLoopResult",
    "build_shadow_authority_audit",
    "build_unified_risk_audit",
    "evaluate_unified",
    # Private helpers exported for tests that used to reach into
    # control_loop.py directly. Their leading underscore signals
    # "not stable public API" but the name resolution is preserved.
    "_compute_authority",
    "_extract_environment",
    "_extract_resource_id",
    "_extract_resource_props",
    "_is_execution_success",
    "_synthetic_action_build_failure",
    "_unified_audit_dict",
]
