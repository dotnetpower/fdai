"""Unit tests for :mod:`fdai.core.web_search.policy`."""

from __future__ import annotations

import pytest
from fdai.core.web_search.policy import (
    WebSearchPolicyConfig,
    WebSearchRoute,
    WebSearchSignals,
    decide_web_search,
)


def _signals(**overrides: object) -> WebSearchSignals:
    base: dict[str, object] = {
        "is_reasoning_tier": True,
        "novelty_score": 0.9,
        "grounding_gap": True,
        "allowlist_has_web_search": True,
        "provider_available": True,
        "query_budget_remaining": 3,
        "cost_budget_remaining_usd": 1.0,
    }
    base.update(overrides)
    return WebSearchSignals(**base)  # type: ignore[arg-type]


def _enabled() -> WebSearchPolicyConfig:
    return WebSearchPolicyConfig(enabled=True)


def test_all_preconditions_met_searches() -> None:
    decision = decide_web_search(_enabled(), _signals())
    assert decision.route is WebSearchRoute.SEARCH
    assert decision.should_search is True
    assert decision.reason == "novel_reasoning_tier_grounding_gap"


def test_disabled_by_default_skips() -> None:
    decision = decide_web_search(WebSearchPolicyConfig(), _signals())
    assert decision.route is WebSearchRoute.SKIP
    assert decision.reason == "web_search_disabled"


def test_no_provider_skips() -> None:
    decision = decide_web_search(_enabled(), _signals(provider_available=False))
    assert decision.reason == "no_provider"


def test_capability_not_allowlisted_skips() -> None:
    decision = decide_web_search(_enabled(), _signals(allowlist_has_web_search=False))
    assert decision.reason == "capability_not_allowlisted"


def test_mini_tier_never_searches() -> None:
    decision = decide_web_search(_enabled(), _signals(is_reasoning_tier=False))
    assert decision.reason == "not_reasoning_tier"


def test_query_budget_exhausted_skips() -> None:
    decision = decide_web_search(_enabled(), _signals(query_budget_remaining=0))
    assert decision.reason == "query_budget_exhausted"


def test_cost_budget_exhausted_skips() -> None:
    decision = decide_web_search(_enabled(), _signals(cost_budget_remaining_usd=0.0))
    assert decision.reason == "cost_budget_exhausted"


def test_grounded_without_gap_skips() -> None:
    decision = decide_web_search(_enabled(), _signals(grounding_gap=False))
    assert decision.reason == "grounded_no_gap"


def test_relaxed_grounding_gap_allows_search() -> None:
    config = WebSearchPolicyConfig(enabled=True, require_grounding_gap=False)
    decision = decide_web_search(config, _signals(grounding_gap=False))
    assert decision.route is WebSearchRoute.SEARCH


def test_below_novelty_threshold_skips() -> None:
    decision = decide_web_search(_enabled(), _signals(novelty_score=0.5))
    assert decision.reason == "below_novelty_threshold"


def test_deny_order_provider_before_tier() -> None:
    # Both provider missing and mini tier - provider gate wins (earlier).
    decision = decide_web_search(
        _enabled(),
        _signals(provider_available=False, is_reasoning_tier=False),
    )
    assert decision.reason == "no_provider"


def test_config_rejects_bad_threshold() -> None:
    with pytest.raises(ValueError, match="novelty_threshold"):
        WebSearchPolicyConfig(novelty_threshold=1.5)


def test_signals_reject_bad_novelty() -> None:
    with pytest.raises(ValueError, match="novelty_score"):
        _signals(novelty_score=2.0)
