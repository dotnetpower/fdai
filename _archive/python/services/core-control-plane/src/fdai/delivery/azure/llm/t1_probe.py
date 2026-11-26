"""Supervised synthetic mini probes; never send operator conversation content."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

import httpx
from azure.core.exceptions import ClientAuthenticationError

from fdai.delivery.azure.llm.adaptive_answer import AdaptiveModelTarget
from fdai.delivery.azure.llm.completion_body import completion_body_params
from fdai.delivery.azure.llm.t1_latency import T1_ROUTING_STATE_KEY, T1MiniRouting
from fdai.shared.providers.state_store import StateStore
from fdai.shared.providers.workload_identity import WorkloadIdentity

_LOGGER = logging.getLogger(__name__)
_PROJECTION_TIMEOUT_SECONDS = 5.0
_MAX_RESPONSE_BYTES = 32768
_MAX_SSE_LINE_CHARS = 16384
T1CapacityBenchmarkStatus = Literal[
    "completed",
    "unavailable",
    "rate_limited",
    "provider_unavailable",
    "provider_status",
    "deadline",
    "transport_or_identity",
    "invalid_probe_response",
]


@dataclass(frozen=True, slots=True)
class T1CapacityBenchmarkReceipt:
    """Sanitized fixed-request measurements that never alter model capacity."""

    deployment: str | None
    status: T1CapacityBenchmarkStatus
    samples_requested: int
    samples_completed: int
    concurrency: int
    ttft_ms: tuple[float, ...]
    total_latency_ms: tuple[float, ...]
    capacity_changed: bool = field(default=False, init=False)
    execution_authority: bool = field(default=False, init=False)


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
                        failure: str | None = None
                        stop_cycle = False
                        duration = 0.0
                        try:
                            async with asyncio.timeout(8):
                                ttft_ms, duration = await self._probe(target)
                        except httpx.HTTPStatusError as exc:
                            failure = "provider_status"
                            stop_cycle = exc.response.status_code in {429, 503}
                        except (TimeoutError, httpx.TimeoutException):
                            failure, stop_cycle = "deadline", True
                        except (httpx.RequestError, ClientAuthenticationError):
                            failure, stop_cycle = "transport_or_identity", True
                        except (ValueError, KeyError, TypeError, IndexError):
                            failure = "invalid_probe_response"
                        self.routing.record(
                            target.target.deployment,
                            duration if failure is None else None,
                            ttft_ms=ttft_ms if failure is None else None,
                        )
                        log_extra: dict[str, object] = {"status": failure or "measured"}
                        if failure is None:
                            log_extra["duration_ms"] = round(duration)
                        _LOGGER.log(
                            logging.INFO if failure is None else logging.WARNING,
                            "t1_mini_probe_completed",
                            extra=log_extra,
                        )
                        if stop_cycle:
                            break
                    await self._publish()
            except TimeoutError:
                _LOGGER.warning("t1_mini_probe_cycle_deadline")

    async def benchmark_capacity(
        self,
        *,
        samples: int = 4,
        concurrency: int = 1,
    ) -> T1CapacityBenchmarkReceipt:
        """Measure one selected mini with the exact probe request and no retries."""
        if type(samples) is not int or not 1 <= samples <= 16:
            raise ValueError("benchmark samples MUST be in [1, 16]")
        if type(concurrency) is not int or not 1 <= concurrency <= min(4, samples):
            raise ValueError("benchmark concurrency MUST be in [1, min(4, samples)]")
        if self._lock.locked():
            raise RuntimeError("T1 mini probe is already running")
        async with self._lock:
            selected_config = self.routing.selected_config() if self.routing.enabled else None
            if selected_config is None:
                return T1CapacityBenchmarkReceipt(
                    deployment=None,
                    status="unavailable",
                    samples_requested=samples,
                    samples_completed=0,
                    concurrency=concurrency,
                    ttft_ms=(),
                    total_latency_ms=(),
                )
            selected = selected_config.primary
            ttfts: list[float] = []
            totals: list[float] = []
            status: T1CapacityBenchmarkStatus = "completed"
            try:
                async with asyncio.timeout(35):
                    for start in range(0, samples, concurrency):
                        wave_size = min(concurrency, samples - start)
                        wave = await asyncio.gather(
                            *(self._benchmark_sample(selected) for _ in range(wave_size)),
                            return_exceptions=True,
                        )
                        should_stop = False
                        for result in wave:
                            if isinstance(result, asyncio.CancelledError):
                                raise result
                            if isinstance(result, BaseException):
                                status = _benchmark_failure_status(result)
                                should_stop = True
                                continue
                            ttft_ms, total_ms = result
                            ttfts.append(ttft_ms)
                            totals.append(total_ms)
                        if should_stop:
                            break
            except TimeoutError:
                status = "deadline"
            return T1CapacityBenchmarkReceipt(
                deployment=selected.target.deployment,
                status=status,
                samples_requested=samples,
                samples_completed=len(totals),
                concurrency=concurrency,
                ttft_ms=tuple(ttfts),
                total_latency_ms=tuple(totals),
            )

    async def _benchmark_sample(self, selected: AdaptiveModelTarget) -> tuple[float, float]:
        async with asyncio.timeout(8):
            return await self._probe(selected)

    async def _publish(self) -> None:
        async with asyncio.timeout(_PROJECTION_TIMEOUT_SECONDS):
            await self._store.write_state(T1_ROUTING_STATE_KEY, self.routing.snapshot())

    async def _probe(self, selected: AdaptiveModelTarget) -> tuple[float, float]:
        request = selected.target.operation("chat/completions")
        body: dict[str, object] = {
            "messages": [
                {"role": "system", "content": "Reply with exactly OK. Do not explain."},
                {"role": "user", "content": "OK"},
            ],
            "stream": True,
            **completion_body_params(selected.family, temperature=0.0, max_tokens=256),
        }
        if selected.family.casefold() in {"gpt-5-mini", "gpt-5.4-mini"}:
            body["reasoning_effort"] = "low"
        if request.model_body_field is not None:
            body["model"] = request.model_body_field
        token = await self._identity.get_token(selected.target.auth_audience)
        started_at = self._clock()
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
            answer: list[str] = []
            response_bytes = 0
            ttft_ms: float | None = None
            stopped = False
            done = False
            pending = bytearray()

            def consume_line(raw_line: bytes) -> None:
                nonlocal done, stopped, ttft_ms
                if len(raw_line) > _MAX_SSE_LINE_CHARS:
                    raise ValueError("mini probe SSE line exceeds byte budget")
                try:
                    line = raw_line.removesuffix(b"\r").decode("utf-8")
                except UnicodeDecodeError as exc:
                    raise ValueError("mini probe SSE line MUST be UTF-8") from exc
                if not line.startswith("data:"):
                    return
                raw = line.removeprefix("data:").strip()
                if raw == "[DONE]":
                    done = True
                    return
                if not raw:
                    return
                payload = json.loads(raw)
                if not isinstance(payload, dict):
                    raise ValueError("mini probe SSE payload MUST be an object")
                choices = payload.get("choices")
                if choices == [] and any(
                    isinstance(payload.get(key), list)
                    for key in ("prompt_filter_results", "prompt_annotations")
                ):
                    return
                if (
                    not isinstance(choices, list)
                    or len(choices) != 1
                    or not isinstance(choices[0], dict)
                ):
                    raise ValueError("mini probe SSE choices are malformed")
                choice = choices[0]
                finish_reason = choice.get("finish_reason")
                if finish_reason is not None:
                    if finish_reason != "stop":
                        raise ValueError("mini probe did not finish normally")
                    stopped = True
                delta = choice.get("delta")
                if (
                    delta is None
                    and finish_reason is None
                    and isinstance(choice.get("content_filter_results"), dict)
                ):
                    return
                if not isinstance(delta, dict):
                    raise ValueError("mini probe SSE delta is malformed")
                content = delta.get("content")
                if content is None:
                    return
                if not isinstance(content, str):
                    raise ValueError("mini probe SSE content MUST be text")
                if content:
                    if ttft_ms is None:
                        ttft_ms = max(0.0, (self._clock() - started_at) * 1000)
                    answer.append(content)

            async for chunk in response.aiter_bytes():
                response_bytes += len(chunk)
                if response_bytes > _MAX_RESPONSE_BYTES:
                    raise ValueError("mini probe response exceeds byte budget")
                pending.extend(chunk)
                while (line_end := pending.find(b"\n")) >= 0:
                    consume_line(bytes(pending[:line_end]))
                    del pending[: line_end + 1]
                    if done:
                        break
                if done:
                    break
                if len(pending) > _MAX_SSE_LINE_CHARS:
                    raise ValueError("mini probe SSE line exceeds byte budget")
            if pending and not done:
                consume_line(bytes(pending))
        if ttft_ms is None or not stopped or not done or "".join(answer).strip() != "OK":
            raise ValueError("mini probe did not return the expected complete response")
        return ttft_ms, max(0.0, (self._clock() - started_at) * 1000)


def _benchmark_failure_status(
    exc: BaseException,
) -> T1CapacityBenchmarkStatus:
    if isinstance(exc, httpx.HTTPStatusError):
        if exc.response.status_code == 429:
            return "rate_limited"
        if exc.response.status_code == 503:
            return "provider_unavailable"
        return "provider_status"
    if isinstance(exc, (TimeoutError, httpx.TimeoutException)):
        return "deadline"
    if isinstance(exc, (httpx.RequestError, ClientAuthenticationError)):
        return "transport_or_identity"
    if isinstance(exc, (ValueError, KeyError, TypeError, IndexError)):
        return "invalid_probe_response"
    raise exc


__all__ = ["T1CapacityBenchmarkReceipt", "T1MiniProbe"]
