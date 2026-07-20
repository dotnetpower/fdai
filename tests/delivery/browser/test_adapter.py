from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping

import pytest

from fdai.core.browser_evidence.policy import BrowserPolicyViolationError
from fdai.core.browser_evidence.service import BrowserEvidenceUnavailableError
from fdai.delivery.browser import SystemBrowserDnsResolver
from fdai.delivery.browser.adapter import IsolatedBrowserEvidenceProvider
from fdai.delivery.browser.protocols import (
    BrowserDriverRequest,
    BrowserDriverResult,
    BrowserRequestGate,
)
from fdai.shared.providers.browser_evidence import (
    BrowserCaptureLimits,
    BrowserCaptureRequest,
    BrowserOriginPolicy,
    BrowserRedirectPolicy,
    BrowserRuntimeIsolation,
)

_ISOLATION = BrowserRuntimeIsolation(
    executor_identity_present=False,
    host_filesystem_mounted=False,
    environment_scrubbed=True,
    restricted_egress=True,
    ephemeral_profile=True,
)


def test_browser_delivery_facade_exports_only_capture_runtime_components() -> None:
    assert SystemBrowserDnsResolver.__name__ == "SystemBrowserDnsResolver"


class Resolver:
    def __init__(self, answers: Mapping[str, tuple[str, ...]] | None = None) -> None:
        self.answers = answers or {"dashboard.example": ("93.184.216.34",)}
        self.calls: defaultdict[str, int] = defaultdict(int)

    async def resolve(self, hostname: str) -> tuple[str, ...]:
        self.calls[hostname] += 1
        return self.answers[hostname]


class AuthStateLoader:
    def __init__(self) -> None:
        self.refs: list[str] = []

    async def load(self, auth_profile_ref: str) -> Mapping[str, object] | None:
        self.refs.append(auth_profile_ref)
        return {"cookies": [{"name": "session", "value": "internal-only"}]}


class SimulatedDriver:
    def __init__(
        self,
        *,
        requests: tuple[tuple[str, str, str | None], ...] = (),
        popup: bool = False,
        download: bool = False,
        file_chooser: bool = False,
        websocket: bool = False,
        final_url: str = "https://dashboard.example/evidence",
    ) -> None:
        self.requests = requests
        self.popup = popup
        self.download = download
        self.file_chooser = file_chooser
        self.websocket = websocket
        self.final_url = final_url
        self.auth_state: Mapping[str, object] | None = None
        self.decisions: list[bool] = []

    async def capture(
        self,
        request: BrowserDriverRequest,
        *,
        gate: BrowserRequestGate,
        auth_state: Mapping[str, object] | None,
    ) -> BrowserDriverResult:
        self.auth_state = auth_state
        for method, url, redirect_from in self.requests:
            self.decisions.append(
                await gate.authorize(
                    method=method,
                    url=url,
                    redirect_from=redirect_from,
                )
            )
        return BrowserDriverResult(
            final_url=self.final_url,
            screenshot=b"masked",
            visible_text="safe",
            aria_snapshot="main: safe",
            redacted_selectors=("#secret",),
            browser_version="fake-browser",
            response_bytes=20,
            popup_detected=self.popup,
            download_detected=self.download,
            file_chooser_detected=self.file_chooser,
            websocket_detected=self.websocket,
        )


def _policy() -> BrowserOriginPolicy:
    return BrowserOriginPolicy(
        policy_id="browser-dashboard",
        version=1,
        allowed_schemes=("https",),
        allowed_hosts=("dashboard.example",),
        allowed_path_prefixes=("/evidence",),
        auth_profile_ref="dashboard-reader",
        redirect_policy=BrowserRedirectPolicy(max_redirects=2),
        limits=BrowserCaptureLimits(
            max_response_bytes=1_000,
            max_text_chars=100,
            max_snapshot_chars=100,
            timeout_seconds=1,
        ),
        sensitive_region_selectors=("#secret",),
    )


def _request(url: str = "https://dashboard.example/evidence") -> BrowserCaptureRequest:
    return BrowserCaptureRequest(
        request_id="capture-1",
        policy_id="browser-dashboard",
        policy_version=1,
        source_url=url,
        stable_selectors=("main",),
        capture_kinds=("screenshot", "visible_text", "aria_snapshot"),
        correlation_id="correlation-1",
    )


def _provider(
    driver: SimulatedDriver,
    *,
    resolver: Resolver | None = None,
    auth_states: AuthStateLoader | None = None,
) -> IsolatedBrowserEvidenceProvider:
    return IsolatedBrowserEvidenceProvider(
        driver=driver,
        resolver=resolver or Resolver(),
        isolation=_ISOLATION,
        auth_states=auth_states,
    )


async def test_safe_get_and_head_capture_without_exposing_credentials() -> None:
    driver = SimulatedDriver(
        requests=(
            ("GET", "https://dashboard.example/evidence/app.js", None),
            ("HEAD", "https://dashboard.example/evidence/data", None),
        )
    )
    auth_states = AuthStateLoader()

    material = await _provider(driver, auth_states=auth_states).capture(
        policy=_policy(),
        request=_request(),
    )

    assert driver.decisions == [True, True]
    assert auth_states.refs == ["dashboard-reader"]
    assert driver.auth_state is not None
    assert "internal-only" not in repr(material)
    assert not hasattr(_request(), "credentials")


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
async def test_mutating_http_methods_are_aborted(method: str) -> None:
    driver = SimulatedDriver(
        requests=((method, "https://dashboard.example/evidence/action", None),)
    )

    with pytest.raises(BrowserEvidenceUnavailableError, match="denied"):
        await _provider(driver).capture(policy=_policy(), request=_request())

    assert driver.decisions == [False]


@pytest.mark.parametrize(
    "url",
    [
        "https://other.example/evidence",
        "https://169.254.169.254/evidence",
        "file:///tmp/upload.txt",
    ],
)
async def test_cross_origin_metadata_and_file_requests_are_denied(url: str) -> None:
    answers = {
        "dashboard.example": ("93.184.216.34",),
        "other.example": ("93.184.216.35",),
        "169.254.169.254": ("169.254.169.254",),
    }
    driver = SimulatedDriver(requests=(("GET", url, None),))

    with pytest.raises(BrowserEvidenceUnavailableError, match="denied"):
        await _provider(driver, resolver=Resolver(answers)).capture(
            policy=_policy(),
            request=_request(),
        )

    assert driver.decisions == [False]


@pytest.mark.parametrize(
    ("popup", "download", "file_chooser", "websocket", "reason"),
    [
        (True, False, False, False, "popup"),
        (False, True, False, False, "download"),
        (False, False, True, False, "file chooser"),
        (False, False, False, True, "WebSocket"),
    ],
)
async def test_popup_download_and_upload_are_denied(
    popup: bool,
    download: bool,
    file_chooser: bool,
    websocket: bool,
    reason: str,
) -> None:
    driver = SimulatedDriver(
        popup=popup,
        download=download,
        file_chooser=file_chooser,
        websocket=websocket,
    )

    with pytest.raises(BrowserEvidenceUnavailableError, match=reason):
        await _provider(driver).capture(policy=_policy(), request=_request())


async def test_initial_unsafe_url_is_denied_before_driver() -> None:
    driver = SimulatedDriver()

    with pytest.raises(BrowserPolicyViolationError):
        await _provider(driver).capture(
            policy=_policy(),
            request=_request("file:///etc/passwd"),
        )

    assert driver.auth_state is None


def test_public_adapter_has_no_general_browser_control_methods() -> None:
    public_names = {
        name for name in dir(IsolatedBrowserEvidenceProvider) if not name.startswith("_")
    }

    assert public_names == {"capture"}
    assert not public_names & {
        "click",
        "fill",
        "press",
        "select",
        "select_option",
        "clipboard",
        "evaluate",
        "page",
        "context",
    }
