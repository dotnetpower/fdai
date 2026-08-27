"""Compatibility exports for the unified context and locale observations."""

from fdai.core.conversation_assurance.quality_context_locale_observations import (
    ContextIsolationScenarioResult,
    LocaleParityScenarioResult,
    PersistenceFidelityScenarioResult,
    PersonalizationAccuracyScenarioResult,
    ScreenAwarenessScenarioResult,
    critical_safety_escape_item_ids,
    observe_context_and_locale,
    observe_context_isolation,
    observe_locale_parity,
    observe_persistence_fidelity,
    observe_personalization_accuracy,
    observe_screen_awareness,
)

__all__ = [
    "ContextIsolationScenarioResult",
    "LocaleParityScenarioResult",
    "PersistenceFidelityScenarioResult",
    "PersonalizationAccuracyScenarioResult",
    "ScreenAwarenessScenarioResult",
    "critical_safety_escape_item_ids",
    "observe_context_and_locale",
    "observe_context_isolation",
    "observe_locale_parity",
    "observe_persistence_fidelity",
    "observe_personalization_accuracy",
    "observe_screen_awareness",
]
