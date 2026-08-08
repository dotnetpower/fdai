"""Optional async Playwright implementation for isolated evidence capture."""

from __future__ import annotations

import asyncio
import importlib
import socket
from collections.abc import Mapping
from typing import Any

from fdai.core.browser_evidence.service import BrowserEvidenceUnavailableError
from fdai.delivery.browser.protocols import (
    BrowserDriverRequest,
    BrowserDriverResult,
    BrowserRequestGate,
)


class SystemBrowserDnsResolver:
    """Resolve A and AAAA records without retaining a DNS cache."""

    async def resolve(self, hostname: str) -> tuple[str, ...]:
        loop = asyncio.get_running_loop()
        records = await loop.getaddrinfo(
            hostname,
            443,
            family=socket.AF_UNSPEC,
            type=socket.SOCK_STREAM,
        )
        return tuple(sorted({str(record[4][0]) for record in records}))


class AsyncPlaywrightCaptureDriver:
    """Use one ephemeral context and page for a read-only capture."""

    async def capture(
        self,
        request: BrowserDriverRequest,
        *,
        gate: BrowserRequestGate,
        auth_state: Mapping[str, object] | None,
    ) -> BrowserDriverResult:
        try:
            module = importlib.import_module("playwright.async_api")
        except ImportError as exc:
            raise BrowserEvidenceUnavailableError(
                "Playwright is not installed in the browser evidence runtime"
            ) from exc

        event_state = {
            "popup": False,
            "download": False,
            "filechooser": False,
            "websocket": False,
        }
        async with module.async_playwright() as playwright:
            browser = await playwright.chromium.launch(
                headless=True,
                env={"LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"},
                args=(
                    "--disable-extensions",
                    "--disable-background-networking",
                    "--disable-component-update",
                    "--no-default-browser-check",
                    "--no-first-run",
                ),
            )
            try:
                context = await browser.new_context(
                    accept_downloads=False,
                    java_script_enabled=True,
                    service_workers="block",
                    storage_state=dict(auth_state) if auth_state is not None else None,
                    viewport={"width": 1280, "height": 720},
                    device_scale_factor=1,
                )
                page = await context.new_page()
                await page.route("**/*", _route_handler(gate))
                page.on("popup", _popup_handler(event_state))
                page.on("download", _download_handler(event_state))
                page.on("filechooser", _file_chooser_handler(event_state, page))
                page.on("websocket", _websocket_handler(event_state, page))
                timeout_ms = request.timeout_seconds * 1000
                response = await page.goto(
                    request.url,
                    wait_until="domcontentloaded",
                    timeout=timeout_ms,
                )
                if response is None:
                    raise BrowserEvidenceUnavailableError("browser navigation returned no response")
                for selector in request.stable_selectors:
                    await page.locator(selector).wait_for(state="visible", timeout=timeout_ms)
                redacted_selectors = await _present_selectors(
                    page,
                    request.sensitive_region_selectors,
                )
                screenshot = None
                if "screenshot" in request.capture_kinds:
                    screenshot = await page.screenshot(
                        full_page=False,
                        animations="disabled",
                        caret="hide",
                        mask=[page.locator(selector) for selector in redacted_selectors],
                        timeout=timeout_ms,
                        type="png",
                    )
                await _redact_regions(page, redacted_selectors)
                visible_text = None
                if "visible_text" in request.capture_kinds:
                    visible_text = await page.locator("body").inner_text(timeout=timeout_ms)
                    visible_text = visible_text[: request.max_text_chars + 1]
                aria_snapshot = None
                if "aria_snapshot" in request.capture_kinds:
                    body = page.locator("body")
                    if not hasattr(body, "aria_snapshot"):
                        raise BrowserEvidenceUnavailableError(
                            "Playwright runtime does not support ARIA snapshots"
                        )
                    aria_snapshot = await body.aria_snapshot(timeout=timeout_ms)
                    aria_snapshot = aria_snapshot[: request.max_snapshot_chars + 1]
                response_bytes = _response_bytes(response, visible_text, aria_snapshot)
                return BrowserDriverResult(
                    final_url=page.url,
                    screenshot=screenshot,
                    visible_text=visible_text,
                    aria_snapshot=aria_snapshot,
                    redacted_selectors=redacted_selectors,
                    browser_version=str(browser.version),
                    response_bytes=response_bytes,
                    popup_detected=event_state["popup"],
                    download_detected=event_state["download"],
                    file_chooser_detected=event_state["filechooser"],
                    websocket_detected=event_state["websocket"],
                )
            finally:
                await browser.close()


def _route_handler(gate: BrowserRequestGate) -> Any:
    async def handle(route: Any, playwright_request: Any) -> None:
        redirected_from = playwright_request.redirected_from
        allowed = await gate.authorize(
            method=str(playwright_request.method),
            url=str(playwright_request.url),
            redirect_from=(str(redirected_from.url) if redirected_from is not None else None),
        )
        if allowed:
            await route.continue_()
        else:
            await route.abort("blockedbyclient")

    return handle


def _popup_handler(event_state: dict[str, bool]) -> Any:
    def handle(popup: Any) -> None:
        event_state["popup"] = True
        asyncio.create_task(popup.close())

    return handle


def _download_handler(event_state: dict[str, bool]) -> Any:
    def handle(download: Any) -> None:
        event_state["download"] = True
        asyncio.create_task(download.cancel())

    return handle


def _file_chooser_handler(event_state: dict[str, bool], page: Any) -> Any:
    def handle(_chooser: Any) -> None:
        event_state["filechooser"] = True
        asyncio.create_task(page.close())

    return handle


def _websocket_handler(event_state: dict[str, bool], page: Any) -> Any:
    def handle(_websocket: Any) -> None:
        event_state["websocket"] = True
        asyncio.create_task(page.close())

    return handle


async def _present_selectors(page: Any, selectors: tuple[str, ...]) -> tuple[str, ...]:
    present: list[str] = []
    for selector in selectors:
        if await page.locator(selector).count() > 0:
            present.append(selector)
    return tuple(present)


async def _redact_regions(page: Any, selectors: tuple[str, ...]) -> None:
    for selector in selectors:
        await page.locator(selector).evaluate_all(
            """elements => elements.forEach(element => {
                element.textContent = '[REDACTED]';
                for (const name of ['aria-label', 'title', 'value']) element.removeAttribute(name);
            })"""
        )


def _response_bytes(response: Any, visible_text: str | None, aria_snapshot: str | None) -> int:
    content_length = str(response.headers.get("content-length", ""))
    if content_length.isdigit():
        return int(content_length)
    return len((visible_text or "").encode()) + len((aria_snapshot or "").encode())


__all__ = ["AsyncPlaywrightCaptureDriver", "SystemBrowserDnsResolver"]
