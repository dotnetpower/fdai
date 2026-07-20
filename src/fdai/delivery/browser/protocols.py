"""Internal delivery protocols for an isolated browser capture driver."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from fdai.shared.providers.browser_evidence import BrowserCaptureKind


@dataclass(frozen=True, slots=True)
class BrowserDriverRequest:
    url: str
    stable_selectors: tuple[str, ...]
    sensitive_region_selectors: tuple[str, ...]
    capture_kinds: tuple[BrowserCaptureKind, ...]
    timeout_seconds: float
    max_text_chars: int
    max_snapshot_chars: int


@dataclass(frozen=True, slots=True)
class BrowserDriverResult:
    final_url: str
    screenshot: bytes | None
    visible_text: str | None
    aria_snapshot: str | None
    redacted_selectors: tuple[str, ...]
    browser_version: str
    response_bytes: int
    popup_detected: bool = False
    download_detected: bool = False
    file_chooser_detected: bool = False
    websocket_detected: bool = False


class BrowserRequestGate(Protocol):
    async def authorize(
        self,
        *,
        method: str,
        url: str,
        redirect_from: str | None = None,
    ) -> bool: ...


class BrowserAuthStateLoader(Protocol):
    async def load(self, auth_profile_ref: str) -> Mapping[str, object] | None: ...


class BrowserCaptureDriver(Protocol):
    async def capture(
        self,
        request: BrowserDriverRequest,
        *,
        gate: BrowserRequestGate,
        auth_state: Mapping[str, object] | None,
    ) -> BrowserDriverResult: ...


__all__ = [
    "BrowserAuthStateLoader",
    "BrowserCaptureDriver",
    "BrowserDriverRequest",
    "BrowserDriverResult",
    "BrowserRequestGate",
]
