"""Pipeline stages scaffold (G-2 phase 2 - deferred, tracker #14).

This subpackage is the intended home for the Stage-protocol refactor
of ``ControlLoop.process`` (~411 LOC in :mod:`..orchestrator`). Phase 1
extracted the module-level helpers; phase 2 will extract one method at
a time from ``ControlLoop`` into a stage class here without regressing
any of the 5,200+ existing integration tests.

The stages the tracker enumerates (see :file:`../__init__.py`):

  * ``ingest.py`` - normalize + dedup + correlate the raw event
  * ``route.py`` - trust-router tier selection
  * ``evaluate_tier.py`` - T0 -> T1 -> T2 branching
  * ``quality_gate.py`` - mixed-model cross-check + verifier + grounding
  * ``risk_gate.py`` - unified risk-gate authority
  * ``hil_park.py`` - HIL approval round-trip
  * ``execute.py`` - executor dispatch
  * ``audit.py`` - append-only audit + KPI emission
  * ``notify.py`` - channel routing

Empty for now; the presence of the subpackage signals the intent and
gives the Stage refactor a natural home to land into.
"""

from fdai.core.control_loop.stages.base import Stage

__all__ = ["Stage"]
