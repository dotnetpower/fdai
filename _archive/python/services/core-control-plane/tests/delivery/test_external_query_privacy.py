"""External-query privacy admission tests."""

from __future__ import annotations

import pytest
from fdai.delivery.external_query_privacy import DeterministicExternalQueryPrivacyVerifier


@pytest.mark.parametrize(
    "query",
    (
        "current Azure service status",
        "서울의 현재 날씨",
        "public cloud operations guidance",
        "search https://learn.microsoft.com for Azure guidance",
    ),
)
def test_public_queries_are_clear(query: str) -> None:
    assert DeterministicExternalQueryPrivacyVerifier().is_safe(query) is True


@pytest.mark.parametrize(
    "query",
    (
        "search for operator@example.net",
        "search 10.0.0.8 service health",
        "search https://10.0.0.8/admin service health",
        "search https://[fd00::8]/admin service health",
        "search 00000000-0000-0000-0000-000000000000",
        (
            "search /subscriptions/00000000-0000-0000-0000-000000000000/"
            "resourceGroups/private/providers/Microsoft.App/containerApps/app"
        ),
        "search token=" + "".join(("sensitive", "-", "value")),
    ),
)
def test_sensitive_queries_are_held_without_echoing_values(query: str) -> None:
    assert DeterministicExternalQueryPrivacyVerifier().is_safe(query) is False
