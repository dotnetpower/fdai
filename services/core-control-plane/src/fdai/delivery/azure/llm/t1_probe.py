"""Supervised synthetic mini probes; never send operator conversation content."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Callable

import httpx
from azure.core.exceptions import ClientAuthenticationError

from fdai.delivery.azure.llm.adaptive_answer import AdaptiveModelTarget
from fdai.delivery.azure.llm.completion_body import completion_body_params
from fdai.delivery.azure.llm.t1_latency import T1_ROUTING_STATE_KEY, T1MiniRouting
from fdai.shared.providers.state_store import StateStore
from fdai.shared.providers.workload_identity import WorkloadIdentity

_LOGGER = logging.getLogger(__name__)
_PROJECTION_TIMEOUT_SECONDS = 5.0


class T1MiniProbe:
    """Own one non-overlapping, cancellable probe cycle and its health projection.

    Each cycle makes at most four tiny requests, one per configured mini, with
    8-second call and 35-second cycle limits. Rate limits, provider unavailability
    and timeouts end the cycle without retrying the request or using T2.
    """

    def __init__(
        self,
        *,
        routing: T1MiniRouting,
        identity: WorkloadIdentity,
        http_client: httpx.AsyncClient,
        state_store: StateStore,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.routing = routing
        self._identity = identity
        self._http = http_client
        self._store = state_store
        self._clock = clock
        self._lock = asyncio.Lock()

    async def run(self, stop: asyncio.Event) -> None:
        """Publish initial configuration, then refresh until runtime shutdown."""
        await self._publish()
        while not stop.is_set():
            await self.refresh()
            try:
                await asyncio.wait_for(stop.wait(), timeout=self.routing.interval_seconds)
            except TimeoutError:
                continue

    async def refresh(self) -> None:
        """Measure one bounded cycle; overlapping refreshes do not queue retries."""
        if self._lock.locked():
            _LOGGER.info("t1_mini_probe_already_running")
            return
        async with self._lock:
            if not self.routing.enabled:
                await self._publish()
                return
            try:
                async with asyncio.timeout(35):
                    for target in self.routing.candidates:
                        started = self._clock()
                        failure: str | None = None
                        stop_cycle = False
                        try:
                            async with asyncio.timeout(8):
                                await self._probe(target)
                        except httpx.HTTPStatusError as exc:
                            failure = "provider_status"
                            stop_cycle = exc.response.status_code in {429, 503}
                        except (TimeoutError, httpx.TimeoutException):
                            failure, stop_cycle = "deadline", True
                        except (httpx.RequestError, ClientAuthenticationError):
                            failure, stop_cycle = "transport_or_identity", True
                        except (ValueError, KeyError, TypeError, IndexError):
                            failure = "invalid_probe_response"
                        duration = max(0.0, (self._clock() - started) * 1000)
                        self.routing.record(
                            target.target.deployment, duration if failure is None else None
                        )
                        _LOGGER.log(
                            logging.INFO if failure is None else logging.WARNING,
                            "t1_mini_probe_completed",
                            extra={"status": failure or "measured", "duration_ms": round(duration)},
                        )
                        if stop_cycle:
                            break
                    await self._publish()
            except TimeoutError:
                _LOGGER.warning("t1_mini_probe_cycle_deadline")

    async def _publish(self) -> None:
        async with asyncio.timeout(_PROJECTION_TIMEOUT_SECONDS):
            await self._store.write_state(T1_ROUTING_STATE_KEY, self.routing.snapshot())

    async def _probe(self, selected: AdaptiveModelTarget) -> None:
        request = selected.target.operation("chat/completions")
        body: dict[str, object] = {
            "messages": [
                {"role": "system", "content": "Reply with exactly OK. Do not explain."},
                {"role": "user", "content": "OK"},
            ],
            **completion_body_params(selected.family, temperature=0.0, max_tokens=256),
        }
        if selected.family.casefold() in {"gpt-5-mini", "gpt-5.4-mini"}:
            body["reasoning_effort"] = "low"
        if request.model_body_field is not None:
            body["model"] = request.model_body_field
        token = await self._identity.get_token(selected.target.auth_audience)
        async with self._http.stream(
            "POST",
            request.url,
            params=request.params,
            headers={"Authorization": f"Bearer {token.token}"},
            json=body,
            timeout=8,
            follow_redirects=False,
        ) as response:
            response.raise_for_status()
            raw = bytearray()
            async for chunk in response.aiter_bytes():
                if len(raw) + len(chunk) > 32768:
                    raise ValueError("mini probe response exceeds byte budget")
                raw.extend(chunk)
        choice = json.loads(raw)["choices"][0]
        if choice["finish_reason"] != "stop" or choice["message"]["content"].strip() != "OK":
            raise ValueError("mini probe did not return the expected complete response")
