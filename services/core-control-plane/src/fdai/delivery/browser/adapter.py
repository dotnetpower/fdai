"""Evidence-only adapter that applies policy around an isolated browser driver."""

from __future__ import annotations

from collections.abc import Mapping

from fdai.core.browser_evidence.policy import (
    BrowserDnsResolver,
    BrowserPolicyViolationError,
    BrowserUrlPolicyValidator,
    CanonicalBrowserUrl,
)
from fdai.core.browser_evidence.service import BrowserEvidenceUnavailableError
from fdai.delivery.browser.protocols import (
    BrowserAuthStateLoader,
    BrowserCaptureDriver,
    BrowserDriverRequest,
)
from fdai.shared.providers.browser_evidence import (
    BrowserCaptureMaterial,
    BrowserCaptureRequest,
    BrowserOriginPolicy,
    BrowserRuntimeIsolation,
)


class _EmptyAuthStateLoader:
    async def load(self, auth_profile_ref: str) -> Mapping[str, object] | None:
        return None


class _ReadOnlyRequestGate:
    def __init__(
        self,
        *,
        validator: BrowserUrlPolicyValidator,
        source: CanonicalBrowserUrl,
    ) -> None:
        self._validator = validator
        self._last = source
        self._redirect_count = 0
        self.denials: list[str] = []

    async def authorize(
        self,
        *,
        method: str,
        url: str,
        redirect_from: str | None = None,
    ) -> bool:
        normalized_method = method.upper()
        if normalized_method not in {"GET", "HEAD"}:
            self.denials.append(f"method:{normalized_method}")
            return False
        try:
            if redirect_from is not None:
                self._redirect_count += 1
                self._last = await self._validator.validate_redirect(
                    url,
                    source=self._last,
                    redirect_count=self._redirect_count,
                )
            else:
                self._last = await self._validator.validate_connection(url)
        except BrowserPolicyViolationError:
            self.denials.append("destination")
            return False
        return True


class IsolatedBrowserEvidenceProvider:
    """Implement only the provider's typed capture operation."""

    def __init__(
        self,
        *,
        driver: BrowserCaptureDriver,
        resolver: BrowserDnsResolver,
        isolation: BrowserRuntimeIsolation,
        auth_states: BrowserAuthStateLoader | None = None,
    ) -> None:
        if not isolation.verified:
            raise ValueError("browser delivery isolation profile MUST be verified")
        self._driver = driver
        self._resolver = resolver
        self._isolation = isolation
        self._auth_states = auth_states or _EmptyAuthStateLoader()

    async def capture(
        self,
        *,
        policy: BrowserOriginPolicy,
        request: BrowserCaptureRequest,
    ) -> BrowserCaptureMaterial:
        validator = BrowserUrlPolicyValidator(policy=policy, resolver=self._resolver)
        source = await validator.validate_navigation(request.source_url)
        gate = _ReadOnlyRequestGate(validator=validator, source=source)
        auth_state = await self._auth_states.load(policy.auth_profile_ref)
        result = await self._driver.capture(
            BrowserDriverRequest(
                url=source.url,
                stable_selectors=request.stable_selectors,
                sensitive_region_selectors=policy.sensitive_region_selectors,
                capture_kinds=request.capture_kinds,
                timeout_seconds=policy.limits.timeout_seconds,
                max_text_chars=policy.limits.max_text_chars,
                max_snapshot_chars=policy.limits.max_snapshot_chars,
            ),
            gate=gate,
            auth_state=auth_state,
        )
        final = await validator.validate_connection(result.final_url)
        if gate.denials:
            raise BrowserEvidenceUnavailableError("browser request was denied by policy")
        if result.popup_detected:
            raise BrowserEvidenceUnavailableError("browser popup was detected")
        if result.download_detected:
            raise BrowserEvidenceUnavailableError("browser download was detected")
        if result.file_chooser_detected:
            raise BrowserEvidenceUnavailableError("browser file chooser was detected")
        if result.websocket_detected:
            raise BrowserEvidenceUnavailableError("browser WebSocket was detected")
        return BrowserCaptureMaterial(
            canonical_source_url=source.url,
            canonical_final_url=final.url,
            screenshot=result.screenshot,
            visible_text=result.visible_text,
            aria_snapshot=result.aria_snapshot,
            selectors=request.stable_selectors,
            redacted_selectors=result.redacted_selectors,
            redactions=(),
            browser_version=result.browser_version,
            isolation=self._isolation,
            response_bytes=result.response_bytes,
        )


__all__ = ["IsolatedBrowserEvidenceProvider"]
