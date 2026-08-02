"""Tests for onboarding probe provenance in the Operator API panel."""

from __future__ import annotations

from fdai.core.onboarding import EmptyResourceProbe
from fdai.delivery.operator_api.routes.onboarding import OnboardingPanel


async def test_onboarding_panel_marks_an_unconfigured_probe() -> None:
    payload = await OnboardingPanel(
        probe=EmptyResourceProbe(),
        configured=False,
    ).render(params={})

    assert payload["probe_mode"] == "not-configured"
    assert payload["blocked"] is True
    assert payload["present_resource_count"] == 0


async def test_onboarding_panel_marks_a_configured_probe() -> None:
    payload = await OnboardingPanel(
        probe=EmptyResourceProbe(),
        configured=True,
    ).render(params={})

    assert payload["probe_mode"] == "configured"
