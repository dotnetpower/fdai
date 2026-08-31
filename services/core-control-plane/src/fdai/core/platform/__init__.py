"""Permanent facade-only Platform domain for the core package.

Groups these subsystems: scheduler, metering, measurement, security,
reporting, onboarding, workflow, detection, deploy_preflight, assurance_twin.

Physical subsystems stay at ``fdai.core.<subsystem>``. This facade-only
layout is the final G-1 architecture: grouped imports provide navigation,
while direct imports preserve compatibility and keep subsystem gates precise.
A future physical move requires its own reviewed design.
"""

from __future__ import annotations

from fdai.core import assurance_twin as assurance_twin  # noqa: F401 - facade re-export
from fdai.core import deploy_preflight as deploy_preflight  # noqa: F401 - facade re-export
from fdai.core import detection as detection  # noqa: F401 - facade re-export
from fdai.core import measurement as measurement  # noqa: F401 - facade re-export
from fdai.core import metering as metering  # noqa: F401 - facade re-export
from fdai.core import onboarding as onboarding  # noqa: F401 - facade re-export
from fdai.core import reporting as reporting  # noqa: F401 - facade re-export
from fdai.core import scheduler as scheduler  # noqa: F401 - facade re-export
from fdai.core import security as security  # noqa: F401 - facade re-export
from fdai.core import workflow as workflow  # noqa: F401 - facade re-export

__all__ = [
    "scheduler",
    "metering",
    "measurement",
    "security",
    "reporting",
    "onboarding",
    "workflow",
    "detection",
    "deploy_preflight",
    "assurance_twin",
]
