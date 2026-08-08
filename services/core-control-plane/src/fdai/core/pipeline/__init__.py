"""Pipeline domain facade for the core package (G-1 phase 1, tracker #14).

Groups these subsystems: event_ingest, trust_router, tiers, quality_gate,
risk_gate, hil_resume, executor, audit, control_loop.

Phase 1 (this commit) creates the facade only - the physical subsystems
stay at ``fdai.core.<subsystem>`` and this package re-exports them so
new code can already write ``from fdai.core.pipeline import <subsystem>``
while pre-existing callsites continue to work unchanged.

Phase 2 (deferred, per tracker #14): physically ``git mv`` each
subsystem into this directory + codemod all callsites. That is a
mass-mv touching hundreds of imports; sequencing it as a separate PR
keeps the diff readable and the safety-core coverage boundary clean.

Why the two phases split matters: the docs already describe this
taxonomy as the target state, and the CI gates (check-file-loc,
check-subsystem-fanout) already stabilize the file-level shape. This
facade is the "code catches up with the docs" bridge - it makes the
taxonomy real at the Python-package level without a mass move.
"""

from __future__ import annotations

from fdai.core import audit as audit  # noqa: F401 - facade re-export
from fdai.core import control_loop as control_loop  # noqa: F401 - facade re-export
from fdai.core import event_ingest as event_ingest  # noqa: F401 - facade re-export
from fdai.core import executor as executor  # noqa: F401 - facade re-export
from fdai.core import hil_resume as hil_resume  # noqa: F401 - facade re-export
from fdai.core import quality_gate as quality_gate  # noqa: F401 - facade re-export
from fdai.core import risk_gate as risk_gate  # noqa: F401 - facade re-export
from fdai.core import tiers as tiers  # noqa: F401 - facade re-export
from fdai.core import trust_router as trust_router  # noqa: F401 - facade re-export

__all__ = [
    "event_ingest",
    "trust_router",
    "tiers",
    "quality_gate",
    "risk_gate",
    "hil_resume",
    "executor",
    "audit",
    "control_loop",
]
