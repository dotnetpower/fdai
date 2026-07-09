"""Live SSE stream - the fourth read-only surface on the console API.

The three existing GET routes (:mod:`fdai.delivery.read_api.main`) return
**snapshots** - audit page, KPI, HIL queue. This module adds a
**stream**: a Server-Sent Events (SSE) endpoint that fans out
control-plane stage transitions to any subscribed console (browser,
CLI). It is the read-only viewport onto autonomy: every event is a
stage transition emitted by a pipeline stage via the
:class:`~fdai.shared.providers.stage_publisher.StagePublisher` seam.

Contract
--------

- **Read-only.** ``GET`` only; there is no matching mutating verb. The
  read-only invariant (``app-shape.instructions.md`` § Operator console)
  holds identically to the other read-API routes.
- **Never shares the executor identity.** The stream is a consumer of
  the pipeline's own live output; nothing on this path calls the
  executor.
- **Opt-in.** :func:`~fdai.delivery.read_api.main.build_app` registers
  this route only when a :class:`LiveStreamConfig` is supplied. The
  upstream default is *off*; a fork opts in at composition.
- **Fan-out is the sink's job.** The route reads from an injected
  :class:`~fdai.shared.providers.sse.SseSink` via
  :meth:`SseSink.subscribe` and writes each event as one SSE frame.
  The sink handles late-join semantics + per-subscriber isolation.
- **Backpressure isolated per client.** A slow HTTP consumer stops
  reading; the async iterator returned by
  :meth:`SseSink.subscribe` naturally back-pressures via the underlying
  queue. A production sink (bounded queue) drops that subscriber's
  events; other subscribers are unaffected.

Auth (matters for a fork's production deployment)
-------------------------------------------------

The route uses the exact same ``_authorize`` gate the other routes use.
In ``dev_mode`` it is anonymous, so the mock console works out of the
box. In production, ``EventSource`` (the browser SSE client) *cannot*
set an ``Authorization`` header - a fork wires auth via one of:

- same-origin cookie session (recommended: Static Web App + read-API on
  one origin, cookies flow automatically),
- CORS-credentialed cookie (cross-origin, ``SameSite=None; Secure`` +
  ``Access-Control-Allow-Credentials``), or
- a ``fetch()``-based client on ``ReadableStream`` (bypasses
  ``EventSource``, allows a Bearer header).

The upstream code does not choose for the fork; the route only asks the
authenticator, and the fork wires the ingress accordingly. See
[user-rbac-and-identity.md](../../../../docs/roadmap/user-rbac-and-identity.md).

Producers (who fills the stream)
--------------------------------

- **Real path.** Pipeline stages
  (``event_ingest``, ``trust_router``, ``T0/T1/T2``, ``risk_gate``,
  ``executor``, ``audit``) receive an injected
  :class:`~fdai.shared.providers.stage_publisher.StagePublisher` and
  call :meth:`~fdai.shared.providers.stage_publisher.StagePublisher.emit`
  on every stage transition. In-process dev binds
  :class:`~fdai.shared.streaming.stage_publisher.SseSinkStagePublisher`;
  a multi-replica production binds
  :class:`~fdai.shared.streaming.stage_publisher.EventBusStagePublisher`
  and relies on the existing
  :class:`~fdai.shared.streaming.broadcaster.SseBroadcaster`.
- **Dev / demo path.** :class:`SyntheticLiveEmitter` publishes fake
  stage transitions at a configurable rate against the same
  :class:`SseSink`, so the local console shows an alive view without
  running the pipeline. Useful for design-review demos and offline
  screenshots. It is *not* a substitute for the real publisher path.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from starlette.requests import Request
from starlette.responses import Response, StreamingResponse
from starlette.routing import Route

from fdai.shared.providers.sse import SseEvent, SseSink
from fdai.shared.providers.stage_publisher import (
    StageEvent,
    StageName,
    StagePhase,
    StagePublisher,
)
from fdai.shared.streaming.stage_publisher import SseSinkStagePublisher

_LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LiveStreamConfig:
    """Composition-root configuration for the live SSE surface.

    A fork typically leaves ``sink`` and ``emitter_factory`` as
    ``None`` - the read-API creates an in-memory
    :class:`~fdai.shared.providers.testing.sse.InMemorySseSink` and
    starts :class:`SyntheticLiveEmitter` in that case, giving the local
    dev harness a live view immediately. Production sets ``sink`` to the
    shared sink the real
    :class:`~fdai.shared.providers.stage_publisher.StagePublisher`
    writes to and leaves ``emitter_factory`` unset.
    """

    path: str = "/live/stream"
    """URL path for the SSE route. MUST start with ``/``."""

    channel: str = "aw.pipeline.stages"
    """SSE channel name the route subscribes on. Every stage publisher
    that wants its events to reach the live console MUST publish onto
    this same channel."""

    keepalive_seconds: float = 15.0
    """Emit a ``: keepalive`` comment line no less than this often so
    proxies (Front Door, nginx) do not close an idle connection."""

    sink: SseSink | None = None
    """The fan-out sink. ``None`` means "create an in-memory sink in
    :func:`build_app`" - the dev-friendly default. A production
    composition supplies a shared sink so the pipeline publishers and
    the route agree on where events flow."""

    emitter_factory: Callable[[SseSink, str], LiveEmitter] | None = None  # noqa: F821 - defined below
    """Factory that binds an emitter to ``(sink, channel)``. ``None``
    means "use :class:`SyntheticLiveEmitter` with defaults" - the
    dev-friendly behaviour. A production composition passes ``None``
    to disable the emitter (real stage publishers own the sink) or
    provides a custom demo emitter."""

    def __post_init__(self) -> None:
        if not self.path.startswith("/"):
            raise ValueError(f"LiveStreamConfig.path MUST start with '/', got {self.path!r}")
        if not self.channel:
            raise ValueError("LiveStreamConfig.channel MUST be non-empty")
        if self.keepalive_seconds <= 0:
            raise ValueError("keepalive_seconds MUST be positive")


class LiveEmitter:
    """Protocol-shape base for a live-event source.

    Concrete emitters implement :meth:`start` and :meth:`stop`. The
    read-API's lifespan starts / stops the emitter alongside the app.
    """

    async def start(self) -> None:  # pragma: no cover - Protocol shape
        raise NotImplementedError

    async def stop(self) -> None:  # pragma: no cover - Protocol shape
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Synthetic emitter (dev + demo parity)
# ---------------------------------------------------------------------------


@dataclass
class SyntheticLiveEmitter(LiveEmitter):
    """Publishes synthetic stage transitions at a target rate.

    The tier and gate distributions match the mock in
    ``mocks/ui/live.html`` so the visual character is preserved when the
    console connects to the real endpoint.

    This emitter is intentionally *not* the production source - real
    stages emit through
    :class:`~fdai.shared.providers.stage_publisher.StagePublisher` and
    reach the same sink via
    :class:`~fdai.shared.streaming.stage_publisher.SseSinkStagePublisher`.
    Upstream ships this emitter so ``FDAI_READ_API_DEV_MODE=1`` shows a
    live cockpit without booting the whole pipeline.
    """

    sink: SseSink
    channel: str = "aw.pipeline.stages"
    events_per_second: float = 5.0
    """Baseline rate at which whole (route -> ... -> execute) sequences
    are produced. Each sequence emits several stage events (begin +
    done per stage), so wire traffic is a small multiple of this.

    Default lowered from 20.0 to 5.0 because a background tab
    left open for hours at 20/sec fanned enough React renders to
    OOM the browser on the Live cockpit before the reducer + view-
    context throttles landed. Even 5.0 needs the client-side batching
    in ``console/src/routes/live.tsx`` - keep it low."""

    tier_weights: Mapping[str, float] = field(
        default_factory=lambda: {"t0": 0.75, "t1": 0.18, "t2": 0.07}
    )
    """Deterministic-first target from the roadmap - T0 dominates.
    Sum should be 1.0."""

    gate_weights_by_tier: Mapping[str, Mapping[str, float]] = field(
        default_factory=lambda: {
            "t0": {"auto": 0.92, "hil": 0.03, "abstain": 0.01, "deny": 0.04},
            "t1": {"auto": 0.83, "hil": 0.10, "abstain": 0.04, "deny": 0.03},
            "t2": {"auto": 0.35, "hil": 0.42, "abstain": 0.18, "deny": 0.05},
        }
    )
    """Per-tier risk-gate outcome mix. T2 escalates far more often."""

    catalog: tuple[tuple[str, str, str, str], ...] = field(
        default_factory=lambda: (
            ("storage.public-blob.deny", "storage.public-blob.disable", "rg-webapp", "change"),
            ("database.pitr.required", "database.enable-pitr", "rg-billing", "resilience"),
            (
                "compute.autoscale.floor.min-2",
                "compute.autoscale.raise-floor",
                "rg-web-eu",
                "change",
            ),
            ("identity.cert.expiry.30d", "identity.cert.rotate", "rg-core", "change"),
            (
                "cost.rightsize.candidate",
                "cost.rightsize.downshift-cpu",
                "rg-batch",
                "cost",
            ),
            (
                "network.firewall.orphan-rule",
                "network.firewall.deny-orphan",
                "rg-net",
                "change",
            ),
            (
                "k8s.rbac.cluster-admin.narrow",
                "k8s.rbac.narrow-cluster-admin",
                "aks-prod",
                "change",
            ),
            (
                "network.dns.public-resolver.deny",
                "network.dns.pin-internal",
                "rg-net",
                "change",
            ),
            ("keyvault.access.grant-narrow", "keyvault.grant-narrow", "rg-ident", "change"),
            (
                "observability.log.retention",
                "observability.log.extend-retention",
                "rg-obs",
                "change",
            ),
            ("cost.orphan-disk.cleanup", "cost.disk.delete-orphan", "rg-legacy", "cost"),
            (
                "reliability.replica-lag.alert",
                "reliability.replica.failover",
                "rg-db-eu",
                "resilience",
            ),
            ("storage.tls.min-1_2", "storage.tls.enforce-min-1_2", "rg-media", "change"),
            ("compute.public-ip.deny", "compute.public-ip.remove", "rg-net", "change"),
            (
                "cost.reserved-instance.recommend",
                "cost.ri.propose-purchase",
                "rg-fleet",
                "cost",
            ),
            (
                "reliability.backup.stale",
                "reliability.backup.trigger",
                "rg-billing",
                "resilience",
            ),
        )
    )

    rng_seed: int | None = None
    """Optional seed for deterministic sequences in tests."""

    _task: asyncio.Task[None] | None = field(default=None, init=False, repr=False)
    _running: bool = field(default=False, init=False, repr=False)
    _counter: int = field(default=0, init=False, repr=False)
    _rng: random.Random = field(default_factory=random.Random, init=False, repr=False)
    _publisher: StagePublisher = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if self.events_per_second <= 0:
            raise ValueError("events_per_second MUST be positive")
        if abs(sum(self.tier_weights.values()) - 1.0) > 0.01:
            raise ValueError("tier_weights MUST sum to ~1.0")
        for tier, mix in self.gate_weights_by_tier.items():
            if abs(sum(mix.values()) - 1.0) > 0.01:
                raise ValueError(f"gate_weights_by_tier[{tier!r}] MUST sum to ~1.0")
        if not self.catalog:
            raise ValueError("catalog MUST NOT be empty")
        if self.rng_seed is not None:
            self._rng = random.Random(self.rng_seed)  # noqa: S311 - synthetic mock, not crypto
        # Same seam a real stage would use.
        self._publisher = SseSinkStagePublisher(self.sink, channel=self.channel)

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        loop = asyncio.get_running_loop()
        self._task = loop.create_task(self._run(), name="fdai.live.synthetic-emitter")

    async def stop(self) -> None:
        self._running = False
        task = self._task
        self._task = None
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass  # Expected on stop.
            except Exception:  # noqa: BLE001
                _LOGGER.debug("live_emitter_stop_exception", exc_info=True)

    async def _run(self) -> None:
        interval = 1.0 / self.events_per_second
        try:
            while self._running:
                await self._emit_one_sequence()
                await asyncio.sleep(interval)
        except asyncio.CancelledError:
            pass

    async def _emit_one_sequence(self) -> None:
        """Emit a small begin/done sequence that mimics one control-loop
        pass through the pipeline (route -> gate -> execute -> audit).

        This is what a real :class:`StagePublisher`-instrumented
        pipeline will emit once Phase 2 wiring lands; the shape stays
        identical so the FE code does not change when we swap in the
        real source.
        """
        self._counter += 1
        tier = self._pick_tier()
        rule, action_type, scope, vertical = self._rng.choice(self.catalog)
        outcome = self._pick_outcome(tier)
        event_id = f"evt-{self._counter:012d}"
        correlation_id = f"corr-{self._counter:012d}"

        base_detail: dict[str, Any] = {
            "tier": tier,
            "rule": rule,
            "action_type": action_type,
            "scope": scope,
            "vertical": vertical,
            "latency_ms": self._pick_latency_ms(tier),
        }

        # ingest done
        await self._publisher.emit(
            StageEvent(
                event_id=event_id,
                correlation_id=correlation_id,
                stage=StageName.INGEST,
                phase=StagePhase.DONE,
                detail=dict(base_detail),
            )
        )
        # route done
        await self._publisher.emit(
            StageEvent(
                event_id=event_id,
                correlation_id=correlation_id,
                stage=StageName.ROUTE,
                phase=StagePhase.DONE,
                detail={**base_detail, "routed_to": tier},
            )
        )
        # verify done (T1 / T2 only; T0 has no verifier step to log)
        if tier != "t0":
            await self._publisher.emit(
                StageEvent(
                    event_id=event_id,
                    correlation_id=correlation_id,
                    stage=StageName.VERIFY,
                    phase=StagePhase.DONE,
                    detail={
                        **base_detail,
                        "checks": ["schema", "policy", "what_if"],
                    },
                )
            )
        # gate done
        await self._publisher.emit(
            StageEvent(
                event_id=event_id,
                correlation_id=correlation_id,
                stage=StageName.GATE,
                phase=StagePhase.DONE,
                detail={**base_detail, "gate_decision": outcome},
            )
        )
        # execute done (only auto path executes; other outcomes stop here)
        if outcome == "auto":
            await self._publisher.emit(
                StageEvent(
                    event_id=event_id,
                    correlation_id=correlation_id,
                    stage=StageName.EXECUTE,
                    phase=StagePhase.DONE,
                    detail={**base_detail, "mode": "shadow"},
                )
            )
        # audit done - always
        await self._publisher.emit(
            StageEvent(
                event_id=event_id,
                correlation_id=correlation_id,
                stage=StageName.AUDIT,
                phase=StagePhase.DONE,
                detail={**base_detail, "gate_decision": outcome},
            )
        )

    def _pick_tier(self) -> str:
        r = self._rng.random()
        acc = 0.0
        for tier, w in self.tier_weights.items():
            acc += w
            if r < acc:
                return tier
        return next(iter(self.tier_weights))

    def _pick_outcome(self, tier: str) -> str:
        mix = self.gate_weights_by_tier[tier]
        r = self._rng.random()
        acc = 0.0
        for outcome, w in mix.items():
            acc += w
            if r < acc:
                return outcome
        return next(iter(mix))

    def _pick_latency_ms(self, tier: str) -> int:
        """Simulated end-to-end pipeline latency for a tier (dev cockpit only).

        Deterministic tiers resolve in milliseconds; T2 reasoning spends
        seconds. Values are synthetic - this emitter has no real cloud calls
        to time - so the sparkline hover shows a plausible ms figure. The real
        :class:`StagePublisher`-instrumented pipeline reports its own timing.
        """
        base = {"t0": 320.0, "t1": 750.0, "t2": 2100.0}.get(tier, 400.0)
        jitter = 0.75 + self._rng.random() * 0.5  # 75%..125%
        return int(round(base * jitter))


# ---------------------------------------------------------------------------
# Starlette route factory
# ---------------------------------------------------------------------------

_KEEPALIVE_COMMENT = b": keepalive\n\n"


def make_live_stream_route(
    *,
    sink: SseSink,
    channel: str,
    path: str,
    keepalive_seconds: float,
    authorize: Callable[[Request], Awaitable[str]],
) -> Route:
    """Return the ``GET`` SSE Route.

    ``authorize`` is the same coroutine
    :mod:`fdai.delivery.read_api.main` uses for its snapshot routes -
    dev-mode short-circuit, prod-mode reader-role token check. Failing
    auth surfaces via the app's exception handlers (401 / 403).
    """

    async def handler(request: Request) -> Response:
        oid = await authorize(request)
        _LOGGER.info("live_stream_open", extra={"actor": oid, "channel": channel})

        async def stream() -> AsyncIterator[bytes]:
            hello = _encode_sse_frame(
                {"event": "hello", "ts": _iso_ts_utc(), "channel": channel},
                kind="hello",
            )
            yield hello

            # Multiplex sink-events + keepalive comments onto a single
            # queue. The sink iterator is NEVER wrapped in
            # ``asyncio.wait_for`` because that would cancel the
            # underlying async-generator on timeout - triggering its
            # ``finally`` and detaching the subscriber (subtle: an
            # async generator whose ``__anext__`` coroutine gets cancelled
            # runs its ``finally`` and next ``__anext__`` raises
            # ``StopAsyncIteration``). Instead, two background tasks push
            # onto the queue and the outer loop only reads.
            out_queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=1024)
            stop = asyncio.Event()

            async def event_pump() -> None:
                try:
                    async for event in sink.subscribe(channel):
                        if stop.is_set():
                            break
                        try:
                            out_queue.put_nowait(_encode_sse_event(event))
                        except asyncio.QueueFull:
                            # Slow client fell behind; drop this frame
                            # rather than block. Reconnect via
                            # ``Last-Event-ID`` will resume on servers
                            # that support replay (upstream today has
                            # audit-log as its replay source).
                            pass
                except asyncio.CancelledError:
                    raise

            async def keepalive_pump() -> None:
                try:
                    while not stop.is_set():
                        await asyncio.sleep(keepalive_seconds)
                        if stop.is_set():
                            break
                        try:
                            out_queue.put_nowait(_KEEPALIVE_COMMENT)
                        except asyncio.QueueFull:
                            pass
                except asyncio.CancelledError:
                    raise

            event_task = asyncio.create_task(event_pump(), name="fdai.live.event-pump")
            keepalive_task = asyncio.create_task(keepalive_pump(), name="fdai.live.keepalive")

            try:
                while True:
                    # ``wait_for`` on ``out_queue.get()`` is safe: the queue is a
                    # normal ``asyncio.Queue`` (no generator ``finally``), so
                    # cancellation on timeout costs nothing.
                    try:
                        chunk = await asyncio.wait_for(out_queue.get(), timeout=1.0)
                    except TimeoutError:
                        # No event and no keepalive yet - fall through
                        # to the disconnect check so a lingering socket
                        # is reaped promptly.
                        chunk = None
                    if chunk is not None:
                        yield chunk
                    if await request.is_disconnected():
                        break
            finally:
                stop.set()
                event_task.cancel()
                keepalive_task.cancel()
                await asyncio.gather(event_task, keepalive_task, return_exceptions=True)
                _LOGGER.info("live_stream_close", extra={"actor": oid, "channel": channel})

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-transform",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )

    return Route(path, handler, methods=["GET"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _encode_sse_frame(payload: Mapping[str, Any], *, kind: str = "control") -> bytes:
    """Encode one dict as a full SSE frame (used for the boot hello)."""
    body = json.dumps(payload, separators=(",", ":"))
    return f"event: {kind}\ndata: {body}\n\n".encode()


def _encode_sse_event(event: SseEvent) -> bytes:
    """Encode one :class:`SseEvent` in the wire format the FE consumes."""
    parts: list[str] = []
    if event.id:
        parts.append(f"id: {event.id}")
    parts.append(f"event: {event.event}")
    parts.append(f"data: {event.data}")
    if event.retry_ms is not None:
        parts.append(f"retry: {event.retry_ms}")
    return ("\n".join(parts) + "\n\n").encode()


def _iso_ts_utc() -> str:
    # Millisecond-precision ISO-8601 with a trailing Z, matching the audit
    # table + the tick timestamp on the live console.
    now = datetime.now(UTC)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


__all__ = [
    "LiveEmitter",
    "LiveStreamConfig",
    "SyntheticLiveEmitter",
    "make_live_stream_route",
]
