"""Public compatibility surface for the live read API stream.

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
[user-rbac-and-identity.md](../../../../docs/roadmap/interfaces/user-rbac-and-identity.md).

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

from fdai.delivery.read_api.streaming.contracts import (
    LiveEmitter,
    LiveStageProducer,
    LiveStreamConfig,
)
from fdai.delivery.read_api.streaming.live_route import make_live_stream_route
from fdai.delivery.read_api.streaming.sse_protocol import (
    _MAX_SSE_DATA_CHARS,
    _MAX_SSE_FIELD_CHARS,
)
from fdai.delivery.read_api.streaming.sse_protocol import (
    encode_sse_event as _encode_sse_event,
)
from fdai.delivery.read_api.streaming.sse_protocol import (
    encode_sse_frame as _encode_sse_frame,
)
from fdai.delivery.read_api.streaming.sse_protocol import (
    iso_ts_utc as _iso_ts_utc,
)
from fdai.delivery.read_api.streaming.synthetic_emitter import SyntheticLiveEmitter

__all__ = [
    "LiveEmitter",
    "LiveStageProducer",
    "LiveStreamConfig",
    "SyntheticLiveEmitter",
    "_MAX_SSE_DATA_CHARS",
    "_MAX_SSE_FIELD_CHARS",
    "_encode_sse_event",
    "_encode_sse_frame",
    "_iso_ts_utc",
    "make_live_stream_route",
]
