from __future__ import annotations

from types import SimpleNamespace

import pytest
from fdai.core.browser_evidence.service import BrowserEvidenceUnavailableError
from fdai.delivery.browser.playwright_driver import AsyncPlaywrightCaptureDriver
from fdai.delivery.browser.protocols import BrowserDriverRequest


class _Gate:
    async def authorize(self, **kwargs: object) -> bool:
        del kwargs
        return True


class _Locator:
    def __init__(self, page: _Page, selector: str) -> None:
        self.page = page
        self.selector = selector

    async def wait_for(self, **kwargs: object) -> None:
        del kwargs

    async def count(self) -> int:
        return 0

    async def inner_text(self, **kwargs: object) -> str:
        del kwargs
        return self.page.visible_text

    async def aria_snapshot(self, **kwargs: object) -> str:
        del kwargs
        return self.page.aria_snapshot

    async def evaluate_all(self, expression: str) -> None:
        del expression


class _Page:
    def __init__(self, *, content_length: str = "", screenshot: bytes = b"png") -> None:
        self.url = "https://dashboard.example/evidence"
        self.content_length = content_length
        self.screenshot_bytes = screenshot
        self.visible_text = "safe"
        self.aria_snapshot = "main"
        self.screenshot_calls = 0

    async def route(self, pattern: str, handler: object) -> None:
        del pattern, handler

    def on(self, event: str, handler: object) -> None:
        del event, handler

    async def goto(self, *args: object, **kwargs: object) -> object:
        del args, kwargs
        headers = {"content-length": self.content_length} if self.content_length else {}
        return SimpleNamespace(headers=headers)

    def locator(self, selector: str) -> _Locator:
        return _Locator(self, selector)

    async def screenshot(self, **kwargs: object) -> bytes:
        del kwargs
        self.screenshot_calls += 1
        return self.screenshot_bytes


class _Browser:
    version = "fake"

    def __init__(self, page: _Page) -> None:
        self.page = page

    async def new_context(self, **kwargs: object) -> object:
        del kwargs
        return SimpleNamespace(new_page=self._new_page)

    async def _new_page(self) -> _Page:
        return self.page

    async def close(self) -> None:
        pass


class _PlaywrightContext:
    def __init__(self, page: _Page) -> None:
        self.playwright = SimpleNamespace(
            chromium=SimpleNamespace(launch=self._launch),
        )
        self.page = page

    async def _launch(self, **kwargs: object) -> _Browser:
        del kwargs
        return _Browser(self.page)

    async def __aenter__(self) -> object:
        return self.playwright

    async def __aexit__(self, *args: object) -> None:
        del args


def _request(*, response: int = 100, screenshot: int = 100) -> BrowserDriverRequest:
    return BrowserDriverRequest(
        url="https://dashboard.example/evidence",
        stable_selectors=("main",),
        sensitive_region_selectors=(),
        capture_kinds=("screenshot", "visible_text", "aria_snapshot"),
        timeout_seconds=1,
        max_response_bytes=response,
        max_screenshot_bytes=screenshot,
        max_text_chars=100,
        max_snapshot_chars=100,
    )


def _module(page: _Page) -> object:
    return SimpleNamespace(async_playwright=lambda: _PlaywrightContext(page))


@pytest.mark.parametrize(
    ("page", "driver_request", "message", "screenshot_calls"),
    (
        (_Page(content_length="101"), _request(response=100), "response", 0),
        (_Page(content_length="invalid"), _request(response=100), "invalid", 0),
        (_Page(screenshot=b"x" * 101), _request(screenshot=100), "screenshot", 1),
    ),
)
async def test_playwright_driver_rejects_declared_and_screenshot_overflow(
    monkeypatch: pytest.MonkeyPatch,
    page: _Page,
    driver_request: BrowserDriverRequest,
    message: str,
    screenshot_calls: int,
) -> None:
    monkeypatch.setattr(
        "fdai.delivery.browser.playwright_driver.importlib.import_module",
        lambda _name: _module(page),
    )

    with pytest.raises(BrowserEvidenceUnavailableError, match=message):
        await AsyncPlaywrightCaptureDriver().capture(
            driver_request,
            gate=_Gate(),
            auth_state=None,
        )

    assert page.screenshot_calls == screenshot_calls


async def test_playwright_driver_rejects_aggregate_text_overflow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = _Page(content_length="1")
    page.visible_text = "x" * 60
    page.aria_snapshot = "y" * 60
    monkeypatch.setattr(
        "fdai.delivery.browser.playwright_driver.importlib.import_module",
        lambda _name: _module(page),
    )

    with pytest.raises(BrowserEvidenceUnavailableError, match="response"):
        await AsyncPlaywrightCaptureDriver().capture(
            _request(response=100), gate=_Gate(), auth_state=None
        )
