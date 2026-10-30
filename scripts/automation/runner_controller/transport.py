"""Bounded, single-attempt HTTP transport with credential-safe failures."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from http.client import HTTPException
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

MAX_RESPONSE_BYTES = 4 * 1024 * 1024
TIMEOUT_SECONDS = 20
DEFAULT_ACCEPTED = (200, 201, 202, 204)

_ERRORS = {
    "request_failed": "Provider request failed",
    "http_status": "Provider returned an unexpected HTTP status",
    "invalid_request": "Provider request configuration is invalid",
    "invalid_response": "Provider response is invalid",
    "response_limit": "Provider response exceeds the size limit",
    "pagination_limit": "Provider pagination could not be completed",
    "scope": "Provider resource is outside the configured scope",
    "identity": "Managed identity configuration or token is invalid",
}


class ProviderError(RuntimeError):
    """Expose only fixed messages and an optional HTTP status, never provider text."""

    def __init__(self, reason: str = "request_failed", status: int | None = None) -> None:
        self.status = status
        super().__init__(_ERRORS.get(reason, _ERRORS["request_failed"]))


@dataclass(frozen=True)
class HttpResponse:
    status: int
    data: Any
    headers: Mapping[str, str]


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(
        self,
        req: Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        return None


def _reject_constant(value: str) -> Any:
    raise ValueError("Invalid JSON constant")


class Transport:
    """Use urllib without retries, redirects, ambient proxies, or auth handlers."""

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        body: Any = None,
        accepted: tuple[int, ...] = DEFAULT_ACCEPTED,
    ) -> HttpResponse:
        try:
            target = urlsplit(url)
            if (
                target.scheme not in {"http", "https"}
                or not target.hostname
                or target.username is not None
                or target.password is not None
                or target.fragment
                or any(ord(char) < 33 or ord(char) == 127 for char in url)
                or method not in {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"}
            ):
                raise ProviderError("invalid_request")
            request_headers = dict(headers or {})
            encoded = None
            if body is not None:
                encoded = json.dumps(body, allow_nan=False).encode("utf-8")
                request_headers.setdefault("Content-Type", "application/json")
            # Only HTTP(S) reaches urllib; provider clients enforce their own host scope.
            request = Request(  # noqa: S310
                url, data=encoded, headers=request_headers, method=method
            )
            opener = build_opener(ProxyHandler({}), _NoRedirect())
            with opener.open(request, timeout=TIMEOUT_SECONDS) as response:
                status = response.status
                if status not in accepted or (300 <= status < 400 and status != 304):
                    raise ProviderError("http_status", status)
                if status == 304:
                    return HttpResponse(status, None, dict(response.headers.items()))
                payload = response.read(MAX_RESPONSE_BYTES + 1)
                if len(payload) > MAX_RESPONSE_BYTES:
                    raise ProviderError("response_limit", status)
                if status in {202, 204} and not payload:
                    data = None
                else:
                    try:
                        data = json.loads(payload.decode("utf-8"), parse_constant=_reject_constant)
                    except (ValueError, UnicodeError, RecursionError):
                        raise ProviderError("invalid_response", status) from None
                return HttpResponse(status, data, dict(response.headers.items()))
        except HTTPError as error:
            status = error.code
            response_headers = dict(error.headers.items()) if error.headers else {}
            error.close()
            if status in accepted and (status == 304 or not 300 <= status < 400):
                return HttpResponse(status, None, response_headers)
            raise ProviderError("http_status", status) from None
        except (URLError, OSError, HTTPException, ValueError, TypeError, RecursionError):
            raise ProviderError("request_failed") from None
