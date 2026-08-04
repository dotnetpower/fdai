"""Latency-based routing across configured chat backends."""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from collections.abc import AsyncIterator, Mapping
from typing import Any, Final

from fdai.delivery.operator_api.routes.chat_backend_azure import AzureAdChatBackend
from fdai.delivery.operator_api.routes.chat_backend_common import (
    ChatBackend,
    ChatBackendUnavailableError,
    ChatContentPolicyError,
)

_LOG = logging.getLogger(__name__)


_ROUTER_WINDOW_SIZE: Final[int] = 8


_ROUTER_WARMUP_SAMPLES: Final[int] = 2


_ROUTER_FAILURE_PENALTY_MS: Final[int] = 30_000

_VISION_PROBE_CONTEXT: Final[dict[str, Any]] = {
    "_attachments": [
        {
            "name": "vision-readiness.png",
            "media_type": "image/png",
            "data_url": (
                "data:image/png;base64,"
                "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
            ),
            "byte_size": 68,
        }
    ]
}


class LatencyRoutedChatBackend:
    """Wrap N :class:`ChatBackend`s and route each request to the fastest.

    Selection policy:

    - **Warm-up**: any candidate with fewer than :data:`_ROUTER_WARMUP_SAMPLES`
      recorded samples is picked first (tie-broken by name so tests stay
      deterministic). This guarantees every candidate is measured on real
      traffic before it can be de-selected.
    - **Steady state**: pick the candidate with the lowest p50 latency in
      its rolling window; ties broken by name.

    On any exception the router records a large penalty sample so a
    broken candidate rotates out on the next request. The router itself
    re-raises - the route handler already maps exceptions to the right
    HTTP status.

    Every reply is enriched with a ``router`` block::

        {
          "chose": "gpt-5.4-mini",
          "reason": "lowest-p50" | "warmup",
          "candidates": [
            {"deployment": "gpt-5.4-mini", "p50_ms": 820, "samples": 5},
            ...
          ]
        }

    The FE deck reads this to render "auto-routing between 3 mini models
    · fastest: gpt-5.4-mini · p50 820ms" in the badge tooltip.
    """

    def __init__(
        self,
        *,
        candidates: list[tuple[str, ChatBackend]],
        turn_timeout_seconds: float = 30.0,
        vision_capable: bool = False,
    ) -> None:
        if not candidates:
            raise ValueError("LatencyRoutedChatBackend requires >= 1 candidate")
        names = [n for n, _ in candidates]
        if len(set(names)) != len(names):
            raise ValueError("LatencyRoutedChatBackend candidate names MUST be unique")
        if turn_timeout_seconds <= 0:
            raise ValueError("turn_timeout_seconds MUST be > 0")
        self._candidates: list[tuple[str, ChatBackend]] = list(candidates)
        self._turn_timeout_seconds = turn_timeout_seconds
        self._vision_capable = vision_capable
        self._vision_backend: ChatBackend | None = None
        self._samples: dict[str, deque[int]] = {
            name: deque(maxlen=_ROUTER_WINDOW_SIZE) for name, _ in candidates
        }
        self._ttft_samples: dict[str, deque[int]] = {
            name: deque(maxlen=_ROUTER_WINDOW_SIZE) for name, _ in candidates
        }
        self._success_counts: dict[str, int] = {name: 0 for name, _ in candidates}
        # Concurrency fairness: N async turns arriving simultaneously during
        # warm-up would all read the same "coldest" candidate from _pick()
        # and stampede one backend. Counting outstanding picks per name lets
        # _pick() treat "in flight" as pseudo-samples so concurrent warm-up
        # turns spread across all candidates.
        self._in_flight: dict[str, int] = {name: 0 for name, _ in candidates}

    # ------------------------------------------------------------------ public
    def stats(self) -> list[dict[str, Any]]:
        """Snapshot of per-candidate rolling latency stats (JSON-safe).

        Each entry carries the raw rolling window (``history_ms``) plus
        precomputed p50 / p95 so the FE can render a sparkline without
        re-doing the maths per repaint.
        """
        result: list[dict[str, Any]] = []
        for name, _ in self._candidates:
            samples = self._samples[name]
            result.append(
                {
                    "deployment": name,
                    # The percentile helpers use infinity internally so an
                    # unmeasured candidate sorts last. JSON has no infinity;
                    # the public health and stream contracts use null.
                    "p50_ms": _p50(samples) if samples else None,
                    "p95_ms": _p95(samples) if samples else None,
                    "samples": len(samples),
                    "history_ms": list(samples),
                    "ttft_p50_ms": (
                        _p50(self._ttft_samples[name]) if self._ttft_samples[name] else None
                    ),
                    "ttft_p95_ms": (
                        _p95(self._ttft_samples[name]) if self._ttft_samples[name] else None
                    ),
                    "ttft_samples": len(self._ttft_samples[name]),
                    "ttft_history_ms": list(self._ttft_samples[name]),
                }
            )
        return result

    def candidate_names(self) -> tuple[str, ...]:
        """Return the preference-safe narrator deployment allowlist."""
        return tuple(name for name, _ in self._candidates)

    def bind_vision_backend(self, backend: ChatBackend) -> None:
        """Bind the independently resolved multimodal backend once at startup."""
        if self._vision_capable:
            raise ValueError("a vision pool cannot bind another vision backend")
        if self._vision_backend is not None:
            raise ValueError("vision backend is already bound")
        if backend is self or (
            isinstance(backend, LatencyRoutedChatBackend) and backend._routes_to(self)
        ):
            raise ValueError("vision backend binding MUST NOT create a routing cycle")
        self._vision_backend = backend

    def vision_backend(self) -> ChatBackend | None:
        """Return the multimodal backend for public health metadata."""
        return self._vision_backend

    def current_pick_name(self) -> str:
        """Which candidate would serve the NEXT request (peek, no state change)."""
        name, _ = self._pick()
        return name

    def has_available_candidate(self) -> bool:
        """Return whether routing has a successful or not-yet-probed candidate."""
        if any(count > 0 for count in self._success_counts.values()):
            return True
        return not all(
            len(self._samples[name]) >= _ROUTER_WARMUP_SAMPLES for name, _ in self._candidates
        )

    def endpoints(self) -> list[str]:
        """Endpoint hosts (best-effort - only Azure-AD backends expose one)."""
        out: list[str] = []
        for _, be in self._candidates:
            if isinstance(be, AzureAdChatBackend):
                out.append(be._endpoint)  # noqa: SLF001 - deliberate peek
        return out

    async def benchmark(
        self,
        *,
        prompt: str = "ping",
        rounds: int | None = None,
        view_context: dict[str, Any] | None = None,
    ) -> str:
        """Measure every candidate up front so the fastest pick is known
        before the first operator turn.

        Fires ``rounds`` minimal requests at each candidate concurrently and
        records real latency into the same rolling window :meth:`answer`
        uses, so a subsequent ``GET /chat/health`` reports the measured
        fastest. ``rounds`` defaults to :data:`_ROUTER_WARMUP_SAMPLES` so
        every candidate clears warm-up and the returned pick reflects p50
        ranking rather than the deterministic warm-up order. Best-effort: a
        candidate that errors gets the standard failure penalty and rotates
        out, exactly as in steady state. Returns the deployment name the
        router would now pick.
        """
        import asyncio

        effective_rounds = _ROUTER_WARMUP_SAMPLES if rounds is None else max(1, rounds)

        async def _probe(name: str, backend: ChatBackend) -> None:
            started = time.monotonic()
            try:
                await backend.answer(
                    prompt=prompt,
                    view_context=dict(view_context or {}),
                    history=[],
                )
            except Exception as exc:  # noqa: BLE001 - best-effort probe
                self._samples[name].append(_ROUTER_FAILURE_PENALTY_MS)
                _LOG.warning(
                    "router.benchmark_candidate_failed",
                    extra={"candidate": name, "error_type": type(exc).__name__},
                )
                return
            self._samples[name].append(int((time.monotonic() - started) * 1000))
            self._success_counts[name] += 1

        for _ in range(effective_rounds):
            await asyncio.gather(*(_probe(name, be) for name, be in self._candidates))
        if isinstance(self._vision_backend, LatencyRoutedChatBackend):
            await self._vision_backend.benchmark(
                prompt="Describe the attached readiness pixel.",
                rounds=effective_rounds,
                view_context=_VISION_PROBE_CONTEXT,
            )
        return self.current_pick_name()

    async def aclose(self) -> None:
        """Close every candidate's ``httpx.AsyncClient`` (best-effort).

        Idempotent: safe to call multiple times or on a router whose
        backends never opened a client. Never raises - a stuck close
        on one client MUST NOT prevent siblings from cleaning up.
        """
        for _, backend in self._candidates:
            client = getattr(backend, "_http", None)
            aclose = getattr(client, "aclose", None)
            if aclose is None:
                continue
            try:
                await aclose()
            except Exception as exc:  # pragma: no cover - defensive path
                _LOG.warning("router.aclose: candidate client failed to close: %s", exc)
        close_vision = getattr(self._vision_backend, "aclose", None)
        if close_vision is not None:
            await close_vision()

    # ------------------------------------------------------------------ Protocol
    async def answer(
        self,
        *,
        prompt: str,
        view_context: dict[str, Any],
        history: list[dict[str, str]],
        preferred_model: str | None = None,
    ) -> dict[str, Any]:
        if _has_vision_context(view_context) and not self._vision_capable:
            if self._vision_backend is None:
                raise ChatBackendUnavailableError("vision model pool unavailable")
            if isinstance(self._vision_backend, LatencyRoutedChatBackend):
                return await self._vision_backend.answer(
                    prompt=prompt,
                    view_context=view_context,
                    history=history,
                    preferred_model=preferred_model,
                )
            return await self._vision_backend.answer(
                prompt=prompt,
                view_context=view_context,
                history=history,
            )
        attempted: set[str] = set()
        last_error: Exception | None = None
        deadline = time.monotonic() + self._turn_timeout_seconds
        while len(attempted) < len(self._candidates):
            name, backend = self._pick(exclude=attempted, preferred_model=preferred_model)
            self._in_flight[name] += 1
            started = time.monotonic()
            try:
                async with asyncio.timeout(self._attempt_budget(deadline, attempted)):
                    reply = await backend.answer(
                        prompt=prompt, view_context=view_context, history=history
                    )
                answer = reply.get("answer")
                if not isinstance(answer, str) or not answer.strip():
                    raise ChatBackendUnavailableError(
                        f"chat candidate {name!r} returned an empty answer"
                    )
            except Exception as exc:
                if isinstance(exc, ChatContentPolicyError):
                    raise
                if isinstance(exc, TimeoutError):
                    exc = TimeoutError("chat turn deadline exceeded")
                self._samples[name].append(_ROUTER_FAILURE_PENALTY_MS)
                attempted.add(name)
                last_error = exc
                _LOG.warning(
                    "router.candidate_failed",
                    extra={"candidate": name, "error_type": type(exc).__name__},
                )
                continue
            finally:
                self._in_flight[name] = max(0, self._in_flight[name] - 1)

            latency = int((time.monotonic() - started) * 1000)
            self._samples[name].append(latency)
            self._success_counts[name] += 1
            reason = (
                "failover"
                if attempted
                else (
                    "user-preferred"
                    if preferred_model == name
                    else (
                        "warmup"
                        if len(self._samples[name]) <= _ROUTER_WARMUP_SAMPLES
                        else "lowest-p50"
                    )
                )
            )
            out: dict[str, Any] = dict(reply)
            out["model"] = name
            out["router"] = {
                "chose": name,
                "reason": reason,
                "candidates": self.stats(),
            }
            return out

        self._log_all_penalised_if_saturated()
        if last_error is not None:
            raise last_error
        raise RuntimeError("chat router exhausted candidates")

    async def complete_structured(
        self,
        *,
        system_prompt: str,
        user_content: str | list[dict[str, object]],
        schema_name: str,
        schema: Mapping[str, object],
        max_tokens: int,
    ) -> Mapping[str, object]:
        """Route one strict structured completion with bounded failover."""

        if _has_image_content(user_content) and not self._vision_capable:
            if self._vision_backend is None:
                raise ChatBackendUnavailableError("vision model pool unavailable")
            complete = getattr(self._vision_backend, "complete_structured", None)
            if complete is None:
                raise ChatBackendUnavailableError(
                    "vision model pool does not support structured completion"
                )
            result = await complete(
                system_prompt=system_prompt,
                user_content=user_content,
                schema_name=schema_name,
                schema=schema,
                max_tokens=max_tokens,
            )
            if not isinstance(result, Mapping):
                raise ChatBackendUnavailableError(
                    "vision model pool returned invalid structured output"
                )
            return result

        attempted: set[str] = set()
        last_error: Exception | None = None
        deadline = time.monotonic() + self._turn_timeout_seconds
        while len(attempted) < len(self._candidates):
            name, backend = self._pick(exclude=attempted)
            self._in_flight[name] += 1
            started = time.monotonic()
            try:
                complete = getattr(backend, "complete_structured", None)
                if complete is None:
                    raise ChatBackendUnavailableError(
                        f"chat candidate {name!r} does not support structured completion"
                    )
                async with asyncio.timeout(self._attempt_budget(deadline, attempted)):
                    result = await complete(
                        system_prompt=system_prompt,
                        user_content=user_content,
                        schema_name=schema_name,
                        schema=schema,
                        max_tokens=max_tokens,
                    )
                if not isinstance(result, Mapping):
                    raise ChatBackendUnavailableError(
                        f"chat candidate {name!r} returned an invalid structured completion"
                    )
            except Exception as exc:
                if isinstance(exc, ChatContentPolicyError):
                    raise
                self._samples[name].append(_ROUTER_FAILURE_PENALTY_MS)
                attempted.add(name)
                last_error = exc
                _LOG.warning(
                    "router.structured_candidate_failed",
                    extra={"candidate": name, "error_type": type(exc).__name__},
                )
                continue
            finally:
                self._in_flight[name] = max(0, self._in_flight[name] - 1)
            self._samples[name].append(int((time.monotonic() - started) * 1000))
            self._success_counts[name] += 1
            return {str(key): value for key, value in result.items()}
        self._log_all_penalised_if_saturated()
        if last_error is not None:
            raise last_error
        raise RuntimeError("chat router exhausted candidates")

    async def answer_stream(
        self,
        *,
        prompt: str,
        view_context: dict[str, Any],
        history: list[dict[str, str]],
        preferred_model: str | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Stream from the fastest candidate, recording its latency.

        Delegates to the picked candidate's ``answer_stream`` when it
        supports streaming, else falls back to a single-shot ``answer``
        emitted as one token. The terminal ``done`` event is enriched with
        the router snapshot so the FE badge stays consistent.
        """
        if _has_vision_context(view_context) and not self._vision_capable:
            if self._vision_backend is None:
                raise ChatBackendUnavailableError("vision model pool unavailable")
            stream = getattr(self._vision_backend, "answer_stream", None)
            if stream is None:
                reply = await self._vision_backend.answer(
                    prompt=prompt,
                    view_context=view_context,
                    history=history,
                )
                yield {"type": "token", "delta": str(reply.get("answer", ""))}
                yield {"type": "done", **reply}
                return
            kwargs: dict[str, Any] = {
                "prompt": prompt,
                "view_context": view_context,
                "history": history,
            }
            if isinstance(self._vision_backend, LatencyRoutedChatBackend):
                kwargs["preferred_model"] = preferred_model
            async for event in stream(**kwargs):
                yield event
            return

        attempted: set[str] = set()
        last_error: Exception | None = None
        deadline = time.monotonic() + self._turn_timeout_seconds
        while len(attempted) < len(self._candidates):
            name, backend = self._pick(exclude=attempted, preferred_model=preferred_model)
            self._in_flight[name] += 1
            started = time.monotonic()
            emitted_content = False
            try:
                async with asyncio.timeout(self._attempt_budget(deadline, attempted)):
                    stream = getattr(backend, "answer_stream", None)
                    if stream is not None:
                        async for event in stream(
                            prompt=prompt, view_context=view_context, history=history
                        ):
                            if event.get("type") == "token" and event.get("delta"):
                                if not emitted_content:
                                    self._ttft_samples[name].append(
                                        int((time.monotonic() - started) * 1000)
                                    )
                                emitted_content = True
                            if event.get("type") == "done":
                                answer = event.get("answer")
                                if not emitted_content and (
                                    not isinstance(answer, str) or not answer.strip()
                                ):
                                    raise ChatBackendUnavailableError(
                                        f"chat candidate {name!r} returned an empty stream"
                                    )
                                event = dict(event)
                                event["model"] = name
                                event["router"] = {
                                    "chose": name,
                                    "reason": "failover"
                                    if attempted
                                    else (
                                        "user-preferred"
                                        if preferred_model == name
                                        else (
                                            "warmup"
                                            if len(self._samples[name]) < _ROUTER_WARMUP_SAMPLES
                                            else "lowest-p50"
                                        )
                                    ),
                                    "candidates": self.stats(),
                                }
                            yield event
                    else:
                        reply = await backend.answer(
                            prompt=prompt, view_context=view_context, history=history
                        )
                        answer = reply.get("answer", "")
                        if not isinstance(answer, str) or not answer.strip():
                            raise ChatBackendUnavailableError(
                                f"chat candidate {name!r} returned an empty answer"
                            )
                        if answer:
                            self._ttft_samples[name].append(
                                int((time.monotonic() - started) * 1000)
                            )
                            emitted_content = True
                            yield {"type": "token", "delta": answer}
                        yield {
                            "type": "done",
                            "answer": answer,
                            "model": name,
                            "router": {
                                "chose": name,
                                "reason": (
                                    "failover"
                                    if attempted
                                    else (
                                        "user-preferred"
                                        if preferred_model == name
                                        else "lowest-p50"
                                    )
                                ),
                                "candidates": self.stats(),
                            },
                        }
            except Exception as exc:
                if isinstance(exc, ChatContentPolicyError):
                    raise
                if isinstance(exc, TimeoutError):
                    exc = TimeoutError("chat turn deadline exceeded")
                self._samples[name].append(_ROUTER_FAILURE_PENALTY_MS)
                _LOG.warning(
                    "router.stream_candidate_failed",
                    extra={"candidate": name, "error_type": type(exc).__name__},
                )
                if emitted_content:
                    raise
                attempted.add(name)
                last_error = exc
                continue
            finally:
                self._in_flight[name] = max(0, self._in_flight[name] - 1)

            self._samples[name].append(int((time.monotonic() - started) * 1000))
            self._success_counts[name] += 1
            return

        self._log_all_penalised_if_saturated()
        if last_error is not None:
            raise last_error
        raise RuntimeError("chat router exhausted candidates")

    def _attempt_budget(self, deadline: float, attempted: set[str]) -> float:
        remaining = deadline - time.monotonic()
        candidates_remaining = len(self._candidates) - len(attempted)
        if remaining <= 0 or candidates_remaining <= 0:
            raise TimeoutError("chat turn deadline exceeded")
        return remaining / candidates_remaining

    # ------------------------------------------------------------------ internal
    def _effective_sample_count(self, name: str) -> int:
        """Samples + in-flight picks - used by warm-up fairness."""
        return len(self._samples[name]) + self._in_flight[name]

    def _routes_to(
        self,
        target: LatencyRoutedChatBackend,
        seen: set[int] | None = None,
    ) -> bool:
        if self is target:
            return True
        visited = set() if seen is None else seen
        if id(self) in visited:
            return False
        visited.add(id(self))
        return isinstance(
            self._vision_backend, LatencyRoutedChatBackend
        ) and self._vision_backend._routes_to(target, visited)

    def _pick(
        self,
        *,
        exclude: set[str] | None = None,
        preferred_model: str | None = None,
    ) -> tuple[str, ChatBackend]:
        excluded = exclude or set()
        available = [(name, backend) for name, backend in self._candidates if name not in excluded]
        if not available:
            raise RuntimeError("chat router has no available candidate")
        if preferred_model is not None:
            preferred = next(
                (candidate for candidate in available if candidate[0] == preferred_model),
                None,
            )
            if preferred is not None:
                return preferred
        # Warm-up: pick the candidate with the fewest samples first, then
        # by name so the pick is deterministic for tests + audit. In-flight
        # picks count as samples so N concurrent warm-up turns spread
        # across candidates instead of stampeding the first one.
        cold = [
            (name, be)
            for name, be in available
            if self._effective_sample_count(name) < _ROUTER_WARMUP_SAMPLES
        ]
        if cold:
            cold.sort(key=lambda x: (self._effective_sample_count(x[0]), x[0]))
            return cold[0]
        # Steady state: min p50 (in-flight breaks ties among equal p50s so
        # a burst of requests does not all land on the same candidate),
        # then by name.
        return min(
            available,
            key=lambda x: (
                _p50(self._samples[x[0]]),
                self._in_flight[x[0]],
                x[0],
            ),
        )

    def _log_all_penalised_if_saturated(self) -> None:
        """Emit an alert-worthy line when every candidate has a penalty on its window.

        Kept separate from the per-call warning so operators see a
        single distinct signal ("all upstreams down") instead of N
        duplicated per-candidate warnings.
        """
        all_penalised = all(
            samples and max(samples) >= _ROUTER_FAILURE_PENALTY_MS
            for samples in self._samples.values()
        )
        if all_penalised:
            _LOG.error(
                "router.all_candidates_penalised",
                extra={"candidates": [name for name, _ in self._candidates]},
            )


def _has_vision_context(view_context: Mapping[str, Any]) -> bool:
    attachments = view_context.get("_attachments")
    return isinstance(attachments, list) and bool(attachments)


def _has_image_content(content: object) -> bool:
    return isinstance(content, list) and any(
        isinstance(part, Mapping) and part.get("type") == "image_url" for part in content
    )


def _p50(samples: deque[int]) -> float:
    """Median of a small deque; ``inf`` for empty so warm-up sorts last."""
    if not samples:
        return float("inf")
    xs = sorted(samples)
    n = len(xs)
    return float(xs[n // 2]) if n % 2 == 1 else (xs[n // 2 - 1] + xs[n // 2]) / 2


def _p95(samples: deque[int]) -> float:
    """95th-percentile of the rolling window; ``inf`` when empty.

    With the default 8-sample window p95 sits at the max element (index
    7 by nearest-rank on N=8: ceil(0.95*8) - 1 = 7). Kept as its own
    helper so a future window resize does not silently change semantics.
    """
    if not samples:
        return float("inf")
    xs = sorted(samples)
    n = len(xs)
    # Nearest-rank method (RFC-style).
    rank = max(0, min(n - 1, int(-(-95 * n // 100)) - 1))
    return float(xs[rank])
