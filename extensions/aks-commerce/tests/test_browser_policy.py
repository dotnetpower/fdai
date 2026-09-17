from datetime import UTC, datetime, timedelta

import pytest

from fdai_aks_commerce import (
    AsyncPlaywrightStorefrontDriver,
    StorefrontJourneyConfig,
    storefront_browser_policy,
)


def test_storefront_policy_is_https_read_only_and_exact_host() -> None:
    policy = storefront_browser_policy("store.example.com")

    assert policy.allowed_schemes == ("https",)
    assert policy.allowed_hosts == ("store.example.com",)
    assert policy.auth_profile_ref == "auth-profile:anonymous-read"
    assert policy.redirect_policy.max_redirects == 0


def test_storefront_journey_requires_credential_free_https() -> None:
    with pytest.raises(ValueError, match="HTTPS"):
        StorefrontJourneyConfig(
            url="http://store.example.com",
            authorization_ref="standing-authorization:synthetic-order",
            authorization_expires_at=datetime.now(UTC) + timedelta(hours=1),
        )

    with pytest.raises(ValueError, match="HTTPS"):
        StorefrontJourneyConfig(
            url="https://user:password@store.example.com",
            authorization_ref="standing-authorization:synthetic-order",
            authorization_expires_at=datetime.now(UTC) + timedelta(hours=1),
        )


def test_storefront_journey_requires_an_opaque_authorization_reference() -> None:
    with pytest.raises(ValueError, match="authorization_ref"):
        StorefrontJourneyConfig(
            url="https://store.example.com",
            authorization_ref="token=not-allowed",
            authorization_expires_at=datetime.now(UTC) + timedelta(hours=1),
        )


async def test_expired_authorization_stops_before_browser_launch() -> None:
    now = datetime(2026, 9, 17, tzinfo=UTC)
    driver = AsyncPlaywrightStorefrontDriver(clock=lambda: now)
    config = StorefrontJourneyConfig(
        url="https://store.example.com",
        authorization_ref="standing-authorization:synthetic-order",
        authorization_expires_at=now - timedelta(seconds=1),
    )

    with pytest.raises(RuntimeError, match="expired"):
        await driver.run(config)
