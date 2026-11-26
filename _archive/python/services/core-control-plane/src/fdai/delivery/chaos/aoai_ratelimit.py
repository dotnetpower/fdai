"""Azure OpenAI rate-limit injector + probe for the enforce harness (S9).

Induces HTTP 429 (rate-limit) responses on a low-TPM Azure OpenAI chat
deployment by driving concurrent completion traffic past the per-minute
token budget, then observes the 429 by sampling the endpoint. Same
discipline as :mod:`fdai.delivery.chaos.live_injectors`: never imported by
``core/``.

The request function is **injected** (``request_fn`` returns an HTTP status
code) so the module needs no SDK and stays fully mockable. A stdlib
``urllib`` factory (:func:`build_aoai_request_fn`) is provided for real use;
credentials and endpoint are supplied by the caller (customer-agnostic).
"""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from typing import Final

_RATE_LIMIT_STATUS: Final[int] = 429

# request_fn returns the HTTP status code of one chat-completion call.
RequestFn = Callable[[], int]


def build_aoai_request_fn(
    *,
    endpoint: str,
    deployment: str,
    token_provider: Callable[[], str],
    prompt: str,
    max_tokens: int = 400,
    api_version: str = "2024-10-21",
    timeout_seconds: float = 60.0,
) -> RequestFn:
    """Build a stdlib-only request function that returns the HTTP status code.

    ``token_provider`` is called per request so a short-lived AAD token can be
    refreshed. Any transport failure is mapped to status ``-1`` (never raises)
    so a load worker keeps looping.
    """

    url = (
        f"{endpoint.rstrip('/')}/openai/deployments/{deployment}"
        f"/chat/completions?api-version={api_version}"
    )
    body = json.dumps(
        {"messages": [{"role": "user", "content": prompt}], "max_tokens": max_tokens}
    ).encode()

    def _request() -> int:
        req = urllib.request.Request(  # noqa: S310 - fixed https AOAI endpoint, not user input
            url,
            data=body,
            headers={
                "Authorization": f"Bearer {token_provider()}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:  # noqa: S310
                return int(resp.status)
        except urllib.error.HTTPError as exc:
            return int(exc.code)
        except Exception:  # noqa: BLE001 - transport failure maps to a sentinel, never raises
            return -1

    return _request


class AoaiRateLimitInjector:
    """Drive Azure OpenAI traffic past its TPM budget to induce 429s.

    ``inject`` starts ``concurrency`` worker threads that fire completion
    requests in a loop until ``stop`` sets the shared event (rollback = drop
    the load; the deployment's TPM budget refills on its own).
    """

    fault_type = "rate_limit"

    def __init__(
        self,
        *,
        request_fn: RequestFn,
        concurrency: int = 20,
        join_timeout_seconds: float = 10.0,
    ) -> None:
        if concurrency < 1:
            raise ValueError("concurrency MUST be >= 1")
        self._request = request_fn
        self._default_concurrency = concurrency
        self._join_timeout = join_timeout_seconds
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []

    def _worker(self) -> None:
        while not self._stop.is_set():
            self._request()

    async def inject(self, *, target: str, params: Mapping[str, str]) -> None:
        concurrency = int(params.get("concurrency", self._default_concurrency))
        self._stop.clear()
        self._threads = [
            threading.Thread(target=self._worker, name=f"aoai-load-{i}", daemon=True)
            for i in range(concurrency)
        ]
        for thread in self._threads:
            thread.start()

    async def stop(self, *, target: str) -> None:
        self._stop.set()
        deadline = time.monotonic() + self._join_timeout
        for thread in self._threads:
            thread.join(timeout=max(0.0, deadline - time.monotonic()))
        self._threads = []


class AoaiRateLimitProbe:
    """Observe rate_limit: a sampled burst hit HTTP 429."""

    def __init__(self, *, request_fn: RequestFn, samples: int = 5) -> None:
        if samples < 1:
            raise ValueError("samples MUST be >= 1")
        self._request = request_fn
        self._samples = samples

    async def observed(self, *, signal: str, targets: Sequence[str]) -> bool:
        with ThreadPoolExecutor(max_workers=self._samples) as pool:
            statuses = list(pool.map(lambda _: self._request(), range(self._samples)))
        return any(status == _RATE_LIMIT_STATUS for status in statuses)


__all__ = ["AoaiRateLimitInjector", "AoaiRateLimitProbe", "build_aoai_request_fn"]
