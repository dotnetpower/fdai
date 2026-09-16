"""Server-owned read-only browser policy for the public storefront."""

from __future__ import annotations

from fdai.shared.providers.browser_evidence import (
    BrowserCaptureLimits,
    BrowserOriginPolicy,
    BrowserRedirectPolicy,
)


def storefront_browser_policy(hostname: str) -> BrowserOriginPolicy:
    """Build the exact-host policy used by the isolated evidence worker."""

    return BrowserOriginPolicy(
        policy_id="aks-commerce-storefront",
        version=1,
        allowed_schemes=("https",),
        allowed_hosts=(hostname,),
        allowed_path_prefixes=("/",),
        auth_profile_ref="auth-profile:anonymous-read",
        redirect_policy=BrowserRedirectPolicy(max_redirects=0),
        limits=BrowserCaptureLimits(
            max_response_bytes=2_000_000,
            max_text_chars=20_000,
            max_snapshot_chars=40_000,
            max_screenshot_bytes=5_000_000,
            max_selectors=8,
            timeout_seconds=30,
        ),
        sensitive_region_selectors=(),
        text_redaction_patterns=(),
        secret_canary_markers=(),
        allowed_query_keys=(),
        retention_days=7,
    )


__all__ = ["storefront_browser_policy"]
