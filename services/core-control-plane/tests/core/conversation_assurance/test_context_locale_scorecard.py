from fdai.core.conversation_assurance import (
    context_locale_scorecard,
    quality_context_locale_observations,
)


def test_compatibility_module_reexports_unified_context_locale_observations() -> None:
    assert (
        context_locale_scorecard.observe_context_and_locale
        is quality_context_locale_observations.observe_context_and_locale
    )
    assert (
        context_locale_scorecard.ContextIsolationScenarioResult
        is quality_context_locale_observations.ContextIsolationScenarioResult
    )
