"""Isolated read-only browser evidence delivery adapter."""

from fdai.delivery.browser.adapter import IsolatedBrowserEvidenceProvider
from fdai.delivery.browser.playwright_driver import (
    AsyncPlaywrightCaptureDriver,
    SystemBrowserDnsResolver,
)

__all__ = [
    "AsyncPlaywrightCaptureDriver",
    "IsolatedBrowserEvidenceProvider",
    "SystemBrowserDnsResolver",
]
