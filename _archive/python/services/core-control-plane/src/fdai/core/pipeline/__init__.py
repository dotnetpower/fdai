"""Permanent facade-only Pipeline domain for the core package.

Groups these subsystems: event_ingest, trust_router, tiers, quality_gate,
risk_gate, hil_resume, executor, audit, control_loop.

Physical subsystems stay at ``fdai.core.<subsystem>``. This facade-only
layout is the final G-1 architecture: grouped imports provide navigation,
while direct imports preserve compatibility and keep safety coverage and
fan-out gates scoped to the real subsystem. A future physical move requires
its own reviewed design and is not implied by this facade.
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
