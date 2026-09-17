"""Identity-free Playwright storefront journey with payload-free evidence."""

from __future__ import annotations

import asyncio
import hashlib
import importlib
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol
from urllib.parse import urlparse


@dataclass(frozen=True, slots=True)
class StorefrontJourneyConfig:
    """Exact HTTPS origin and stable selectors for one storefront revision."""

    url: str
    authorization_ref: str
    authorization_expires_at: datetime
    product_selector: str = ".product-card"
    add_to_cart_name: str = "Add to Cart"
    cart_link_name: str = "Cart"
    checkout_name: str = "Proceed to Checkout"
    success_dialog_text: str = "Order submitted successfully"
    timeout_seconds: int = 30

    def __post_init__(self) -> None:
        parsed = urlparse(self.url)
        if (
            parsed.scheme != "https"
            or not parsed.netloc
            or parsed.username is not None
            or parsed.password is not None
            or parsed.fragment
        ):
            raise ValueError("storefront journey URL must be a credential-free HTTPS URL")
        if not 1 <= self.timeout_seconds <= 120:
            raise ValueError("storefront journey timeout must be in [1, 120]")
        text_values = (
            self.authorization_ref,
            self.product_selector,
            self.add_to_cart_name,
            self.cart_link_name,
            self.checkout_name,
            self.success_dialog_text,
        )
        if any(not value or len(value) > 256 for value in text_values):
            raise ValueError("storefront journey selectors and labels must be bounded")
        if any(marker in self.authorization_ref.casefold() for marker in ("token=", "secret=")):
            raise ValueError("storefront journey authorization_ref must be an opaque reference")
        if (
            self.authorization_expires_at.tzinfo is None
            or self.authorization_expires_at.utcoffset() is None
        ):
            raise ValueError("storefront journey authorization expiry must be timezone-aware")


@dataclass(frozen=True, slots=True)
class StorefrontJourneyResult:
    """Payload-free result of one synthetic customer journey."""

    observed_at: datetime
    success: bool
    failed_step: str | None
    duration_ms: int
    evidence_ref: str
    authorization_ref: str
    synthetic: bool = True
    execution_authority: bool = False


class StorefrontJourneyDriver(Protocol):
    """Run one storefront journey without exposing a browser handle."""

    async def run(self, config: StorefrontJourneyConfig) -> StorefrontJourneyResult: ...


class AsyncPlaywrightStorefrontDriver:
    """Use one ephemeral same-origin browser context for a synthetic order."""

    def __init__(self, *, clock: Callable[[], datetime] | None = None) -> None:
        self._clock = clock or (lambda: datetime.now(UTC))

    async def run(self, config: StorefrontJourneyConfig) -> StorefrontJourneyResult:
        """Run browse, cart, and submit steps; return only bounded metadata."""

        started = time.monotonic()
        step = "launch"
        parsed = urlparse(config.url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        observed_at = self._clock()
        if observed_at.tzinfo is None or observed_at.utcoffset() is None:
            raise ValueError("storefront journey clock must be timezone-aware")
        if observed_at >= config.authorization_expires_at:
            raise RuntimeError("storefront journey standing authorization is expired")
        try:
            module = importlib.import_module("playwright.async_api")
        except ImportError as exc:
            raise RuntimeError("Playwright is unavailable in the synthetic journey worker") from exc
        order_posts = 0
        request_denied = False
        try:
            async with (
                asyncio.timeout(config.timeout_seconds),
                module.async_playwright() as playwright,
            ):
                browser = await playwright.chromium.launch(
                    headless=True,
                    env={"LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"},
                    args=("--disable-extensions", "--no-first-run"),
                )
                try:
                    context = await browser.new_context(
                        accept_downloads=False,
                        service_workers="block",
                        viewport={"width": 1280, "height": 720},
                    )
                    page = await context.new_page()

                    async def authorize(route: Any, request: Any) -> None:
                        nonlocal order_posts, request_denied
                        target = urlparse(str(request.url))
                        target_origin = f"{target.scheme}://{target.netloc}"
                        method = str(request.method).upper()
                        current = self._clock()
                        current_authority = (
                            current.tzinfo is not None
                            and current.utcoffset() is not None
                            and observed_at <= current < config.authorization_expires_at
                        )
                        allowed_origin = (
                            target_origin == origin
                            and target.username is None
                            and target.password is None
                            and not target.fragment
                        )
                        allowed_order = (
                            method == "POST"
                            and target.path == "/api/orders"
                            and not target.query
                            and order_posts == 0
                        )
                        if (
                            current_authority
                            and allowed_origin
                            and (method in {"GET", "HEAD"} or allowed_order)
                        ):
                            if method == "POST":
                                order_posts += 1
                            await route.continue_()
                        else:
                            request_denied = True
                            await route.abort("blockedbyclient")

                    await page.route("**/*", authorize)
                    timeout_ms = config.timeout_seconds * 1000
                    step = "browse"
                    response = await page.goto(
                        config.url,
                        wait_until="networkidle",
                        timeout=timeout_ms,
                    )
                    if response is None or response.status >= 400:
                        raise RuntimeError(
                            "storefront navigation did not return a successful response"
                        )
                    product = page.locator(config.product_selector).first
                    await product.wait_for(state="visible", timeout=timeout_ms)
                    step = "add_to_cart"
                    await product.get_by_role("button", name=config.add_to_cart_name).click(
                        timeout=timeout_ms
                    )
                    step = "open_cart"
                    await page.get_by_role("link", name=config.cart_link_name).click(
                        timeout=timeout_ms
                    )
                    step = "submit_order"
                    dialog_future: asyncio.Future[str] = asyncio.get_running_loop().create_future()

                    async def capture_dialog(dialog: Any) -> None:
                        if not dialog_future.done():
                            dialog_future.set_result(str(dialog.message))
                        await dialog.dismiss()

                    page.once("dialog", capture_dialog)
                    await page.get_by_role("button", name=config.checkout_name).click(
                        timeout=timeout_ms
                    )
                    dialog_text = await asyncio.wait_for(
                        dialog_future,
                        timeout=config.timeout_seconds,
                    )
                    if dialog_text != config.success_dialog_text:
                        raise RuntimeError("storefront checkout returned an unexpected result")
                    if request_denied or order_posts != 1:
                        step = "request_policy"
                        raise RuntimeError("storefront journey did not satisfy its request policy")
                    completed_at = self._clock()
                    if not observed_at <= completed_at < config.authorization_expires_at:
                        step = "authorization"
                        raise RuntimeError(
                            "storefront journey authorization expired before completion"
                        )
                    return _result(
                        completed_at,
                        started,
                        authorization_ref=config.authorization_ref,
                        success=True,
                        failed_step=None,
                    )
                finally:
                    await browser.close()
        except Exception:
            return _result(
                self._clock(),
                started,
                authorization_ref=config.authorization_ref,
                success=False,
                failed_step=step,
            )


def _result(
    observed_at: datetime,
    started: float,
    *,
    authorization_ref: str,
    success: bool,
    failed_step: str | None,
) -> StorefrontJourneyResult:
    duration_ms = max(0, int((time.monotonic() - started) * 1000))
    canonical = (
        f"{observed_at.isoformat()}:{authorization_ref}:"
        f"{success}:{failed_step or 'complete'}:{duration_ms}"
    )
    digest = hashlib.sha256(canonical.encode("ascii")).hexdigest()
    return StorefrontJourneyResult(
        observed_at=observed_at,
        success=success,
        failed_step=failed_step,
        duration_ms=duration_ms,
        evidence_ref=f"synthetic-journey:sha256:{digest}",
        authorization_ref=authorization_ref,
    )


__all__ = [
    "AsyncPlaywrightStorefrontDriver",
    "StorefrontJourneyConfig",
    "StorefrontJourneyDriver",
    "StorefrontJourneyResult",
]
