from __future__ import annotations

from collections.abc import Mapping

import pytest
from fdai.core.browser_evidence.service import BrowserEvidenceUnavailableError
from fdai.delivery.browser.adapter import IsolatedBrowserEvidenceProvider
from fdai.delivery.browser.protocols import BrowserDriverRequest, BrowserDriverResult
from fdai.shared.providers.browser_evidence import (
    BrowserCaptureLimits,
    BrowserCaptureRequest,
    BrowserOriginPolicy,
    BrowserRedirectPolicy,
    BrowserRuntimeIsolation,
    TrustedBrowserDestination,
)

_ISOLATION = BrowserRuntimeIsolation(False, False, True, True, True)


class _Resolver:
    def __init__(self, addresses: tuple[tuple[str, ...], ...] = (("93.184.216.34",),)) -> None:
        self._addresses = addresses
        self._index = 0

    async def resolve(self, hostname: str) -> tuple[str, ...]:
        del hostname
        result = self._addresses[min(self._index, len(self._addresses) - 1)]
        self._index += 1
        return result


class _AuthLoader:
    async def load(self, auth_profile_ref: str) -> Mapping[str, object] | None:
        assert auth_profile_ref == "reader-profile"
        return {"cookies": [{"name": "session", "value": "opaque"}]}


class _Driver:
    def __init__(
        self,
        *,
        method: str = "GET",
        target_url: str = "https://dashboard.example/evidence",
        redirect_from: str | None = None,
        event: str | None = None,
    ) -> None:
        self.method = method
        self.target_url = target_url
        self.redirect_from = redirect_from
        self.event = event
        self.request: BrowserDriverRequest | None = None
        self.auth_state: Mapping[str, object] | None = None

    async def capture(
        self,
        request: BrowserDriverRequest,
        *,
        gate: object,
        auth_state: Mapping[str, object] | None,
    ) -> BrowserDriverResult:
        self.request = request
        self.auth_state = auth_state
        await gate.authorize(  # type: ignore[attr-defined]
            method=self.method,
            url=self.target_url,
            redirect_from=self.redirect_from,
        )
        flags = {f"{self.event}_detected": True} if self.event is not None else {}
        return BrowserDriverResult(
            final_url="https://dashboard.example/evidence",
            screenshot=b"png",
            visible_text="safe",
            aria_snapshot="main",
            redacted_selectors=("#secret",),
            browser_version="fake",
            response_bytes=8,
            **flags,
        )


def _policy(*, redirects: int = 1) -> BrowserOriginPolicy:
    return BrowserOriginPolicy(
        policy_id="dashboard",
        version=1,
        allowed_schemes=("https",),
        allowed_hosts=("dashboard.example",),
        allowed_path_prefixes=("/evidence",),
        auth_profile_ref="reader-profile",
        redirect_policy=BrowserRedirectPolicy(
            max_redirects=redirects,
            trusted_destinations=(TrustedBrowserDestination("https", "cdn.example", ("/asset",)),),
        ),
        limits=BrowserCaptureLimits(
            max_response_bytes=123,
            max_text_chars=45,
            max_snapshot_chars=67,
            timeout_seconds=2,
            max_screenshot_bytes=89,
        ),
        sensitive_region_selectors=("#secret",),
    )


def _request() -> BrowserCaptureRequest:
    return BrowserCaptureRequest(
        request_id="capture-1",
        policy_id="dashboard",
        policy_version=1,
        source_url="https://dashboard.example/evidence",
        stable_selectors=("main",),
        capture_kinds=("screenshot", "visible_text", "aria_snapshot"),
        correlation_id="correlation-1",
    )


@pytest.mark.parametrize("method", ("GET", "HEAD"))
async def test_adapter_forwards_auth_and_exact_server_bounds(method: str) -> None:
    driver = _Driver(method=method)
    provider = IsolatedBrowserEvidenceProvider(
        driver=driver,
        resolver=_Resolver((("93.184.216.34",), ("93.184.216.34",), ("93.184.216.34",))),
        isolation=_ISOLATION,
        auth_states=_AuthLoader(),
    )

    material = await provider.capture(policy=_policy(), request=_request())

    assert driver.request == BrowserDriverRequest(
        url="https://dashboard.example/evidence",
        stable_selectors=("main",),
        sensitive_region_selectors=("#secret",),
        capture_kinds=("screenshot", "visible_text", "aria_snapshot"),
        timeout_seconds=2,
        max_response_bytes=123,
        max_screenshot_bytes=89,
        max_text_chars=45,
        max_snapshot_chars=67,
    )
    assert driver.auth_state == {"cookies": [{"name": "session", "value": "opaque"}]}
    assert material.isolation.executor_identity_present is False


@pytest.mark.parametrize("method", ("POST", "PUT", "DELETE"))
async def test_adapter_denies_mutating_driver_requests(method: str) -> None:
    provider = IsolatedBrowserEvidenceProvider(
        driver=_Driver(method=method), resolver=_Resolver(), isolation=_ISOLATION
    )

    with pytest.raises(BrowserEvidenceUnavailableError, match="denied by policy"):
        await provider.capture(policy=_policy(), request=_request())


@pytest.mark.parametrize("event", ("popup", "download", "file_chooser", "websocket"))
async def test_adapter_denies_browser_side_effect_events(event: str) -> None:
    provider = IsolatedBrowserEvidenceProvider(
        driver=_Driver(event=event),
        resolver=_Resolver((("93.184.216.34",), ("93.184.216.34",), ("93.184.216.34",))),
        isolation=_ISOLATION,
    )

    with pytest.raises(BrowserEvidenceUnavailableError):
        await provider.capture(policy=_policy(), request=_request())


async def test_adapter_denies_redirect_outside_policy_and_dns_rebinding() -> None:
    redirect_provider = IsolatedBrowserEvidenceProvider(
        driver=_Driver(
            target_url="https://outside.example/evidence",
            redirect_from="https://dashboard.example/evidence",
        ),
        resolver=_Resolver(),
        isolation=_ISOLATION,
    )
    with pytest.raises(BrowserEvidenceUnavailableError, match="denied by policy"):
        await redirect_provider.capture(policy=_policy(), request=_request())

    rebinding_provider = IsolatedBrowserEvidenceProvider(
        driver=_Driver(),
        resolver=_Resolver((("93.184.216.34",), ("93.184.216.35",))),
        isolation=_ISOLATION,
    )
    with pytest.raises(BrowserEvidenceUnavailableError, match="denied by policy"):
        await rebinding_provider.capture(policy=_policy(), request=_request())
