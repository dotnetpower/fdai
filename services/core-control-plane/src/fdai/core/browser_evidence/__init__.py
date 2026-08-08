"""Provider-neutral, read-only browser evidence contracts and policy."""

from fdai.core.browser_evidence.contracts import (
    BrowserCaptureLimits,
    BrowserOriginPolicy,
    BrowserRedirectPolicy,
    TrustedBrowserDestination,
)
from fdai.core.browser_evidence.policy import (
    BrowserPolicyViolationError,
    BrowserUrlPolicyValidator,
    CanonicalBrowserUrl,
)

__all__ = [
    "BrowserCaptureLimits",
    "BrowserOriginPolicy",
    "BrowserPolicyViolationError",
    "BrowserRedirectPolicy",
    "BrowserUrlPolicyValidator",
    "CanonicalBrowserUrl",
    "TrustedBrowserDestination",
]
