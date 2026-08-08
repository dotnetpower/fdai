"""Platform domain facade for the core package (G-1 phase 1, tracker #14).

Groups these subsystems: scheduler, metering, measurement, security,
reporting, onboarding, workflow, detection, deploy_preflight, assurance_twin.

Phase 1 (this commit) creates the facade only - the physical subsystems
stay at ``fdai.core.<subsystem>`` and this package re-exports them so
new code can already write ``from fdai.core.platform import <subsystem>``
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
