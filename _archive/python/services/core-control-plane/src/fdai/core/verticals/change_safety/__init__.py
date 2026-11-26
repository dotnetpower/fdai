"""Change Safety vertical - integrated risk classification + out-of-band detector.

Phase 3 § Change Safety. Change events (drift, config change, IaC diff)
land on the shared control loop; this subpackage groups:

- :mod:`.orchestrator` - :class:`ChangeRisk` classification, the
  risk-gate integration primitives.
- :mod:`.detector` - :class:`ChangeSafetyDetector` shadow-mode
  attribution pipeline for Azure Activity Log events.

Every symbol below is re-exported at the package facade so callers
continue to write ``from fdai.core.verticals.change_safety import
ChangeRisk`` unchanged after G-6 (tracker #14, issue #20).
"""

from __future__ import annotations

from fdai.core.verticals.change_safety.detector import (
    ACTIVITY_LOG_SIGNAL_KIND,
    DEFAULT_SETTLING_WINDOW_SECONDS,
    OUT_OF_BAND_ALERT_TOPIC,
    ChangeAttribution,
    ChangeSafetyDecision,
    ChangeSafetyDetector,
    ChangeSafetyDetectorConfig,
    DetectorOutcome,
)
from fdai.core.verticals.change_safety.orchestrator import (
    ChangeContext,
    ChangeDecision,
    ChangeDecisionOutcome,
    ChangeRisk,
    ChangeSafetyClassifier,
    ChangeSafetyConfig,
)

__all__ = [
    "ACTIVITY_LOG_SIGNAL_KIND",
    "ChangeAttribution",
    "ChangeContext",
    "ChangeDecision",
    "ChangeDecisionOutcome",
    "ChangeRisk",
    "ChangeSafetyClassifier",
    "ChangeSafetyConfig",
    "ChangeSafetyDecision",
    "ChangeSafetyDetector",
    "ChangeSafetyDetectorConfig",
    "DEFAULT_SETTLING_WINDOW_SECONDS",
    "DetectorOutcome",
    "OUT_OF_BAND_ALERT_TOPIC",
]
