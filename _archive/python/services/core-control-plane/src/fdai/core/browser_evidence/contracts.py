"""Compatibility exports for the public browser evidence policy contracts."""

from fdai.shared.providers.browser_evidence import (
    BrowserCaptureLimits,
    BrowserOriginPolicy,
    BrowserRedirectPolicy,
    TrustedBrowserDestination,
    canonical_browser_hostname,
)

canonical_hostname = canonical_browser_hostname


__all__ = [
    "BrowserCaptureLimits",
    "BrowserOriginPolicy",
    "BrowserRedirectPolicy",
    "TrustedBrowserDestination",
    "canonical_hostname",
]
