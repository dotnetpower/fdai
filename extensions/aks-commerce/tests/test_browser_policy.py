from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

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


class _Route:
    def __init__(self) -> None:
        self.continued = 0
        self.aborted = 0

    async def continue_(self) -> None:
        self.continued += 1

    async def abort(self, reason: str) -> None:
        assert reason == "blockedbyclient"
        self.aborted += 1


class _Page:
    def __init__(self, *, now: list[datetime], behavior: str) -> None:
        self.now = now
        self.behavior = behavior
        self.requests: list[_Route] = []
        self.closed = False
        self.button = ""
        self.handler: Any = None
        self.dialog_handler: Any = None

    async def route(self, pattern: str, handler: Any) -> None:
        self.handler = handler

    async def goto(self, url: str, **kwargs: Any) -> SimpleNamespace:
        if self.behavior == "timeout":
            await asyncio.Future()
        return SimpleNamespace(status=200)

    def locator(self, selector: str) -> _Page:
        return self

    @property
    def first(self) -> _Page:
        return self

    async def wait_for(self, **kwargs: Any) -> None:
        pass

    def get_by_role(self, role: str, *, name: str) -> _Page:
        self.button = name
        return self

    async def click(self, **kwargs: Any) -> None:
        if self.button != "Proceed to Checkout":
            return
        if self.behavior == "expired":
            self.now[0] += timedelta(minutes=2)
        for _attempt in range(2 if self.behavior == "duplicate" else 1):
            route = _Route()
            self.requests.append(route)
            url = (
                "https://other.example.com/api/orders"
                if self.behavior == "cross_origin"
                else "https://store.example.com/api/orders"
            )
            await self.handler(route, SimpleNamespace(url=url, method="POST"))
        self.now[0] += timedelta(seconds=1)

        async def dismiss() -> None:
            pass

        await self.dialog_handler(
            SimpleNamespace(message="Order submitted successfully", dismiss=dismiss)
        )

    def once(self, event: str, handler: Any) -> None:
        assert event == "dialog"
        self.dialog_handler = handler

    async def new_context(self, **kwargs: Any) -> _Page:
        return self

    async def new_page(self) -> _Page:
        return self

    async def close(self) -> None:
        self.closed = True

    async def launch(self, **kwargs: Any) -> _Page:
        return self

    async def __aenter__(self) -> SimpleNamespace:
        return SimpleNamespace(chromium=self)

    async def __aexit__(self, *args: Any) -> None:
        pass


@pytest.mark.parametrize("behavior", ["normal", "duplicate", "expired", "cross_origin", "timeout"])
async def test_journey_request_limits_and_completion_time(
    monkeypatch: pytest.MonkeyPatch, behavior: str
) -> None:
    started_at = datetime(2026, 9, 17, tzinfo=UTC)
    now = [started_at]
    page = _Page(now=now, behavior=behavior)
    monkeypatch.setattr(
        "fdai_aks_commerce.synthetic.importlib.import_module",
        lambda name: SimpleNamespace(async_playwright=lambda: page),
    )
    config = StorefrontJourneyConfig(
        url="https://store.example.com",
        authorization_ref="standing-authorization:synthetic-order",
        authorization_expires_at=started_at + timedelta(minutes=1),
        timeout_seconds=1,
    )

    result = await AsyncPlaywrightStorefrontDriver(clock=lambda: now[0]).run(config)

    assert page.closed
    assert result.execution_authority is False
    assert result.success is (behavior == "normal")
    assert result.observed_at == now[0]
    if behavior == "normal":
        assert result.observed_at > started_at
        assert sum(request.continued for request in page.requests) == 1
    elif behavior == "duplicate":
        assert sum(request.continued for request in page.requests) == 1
        assert sum(request.aborted for request in page.requests) == 1
    elif behavior in {"expired", "cross_origin"}:
        assert sum(request.continued for request in page.requests) == 0
    else:
        assert result.failed_step == "browse"
        assert result.duration_ms < 3000
