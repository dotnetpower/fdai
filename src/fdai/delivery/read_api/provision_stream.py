"""Provisioning progress SSE surface - the ``provision.*`` read-only stream.

This is the in-product (surface **B**) half of the "Genesis" provisioning
experience (``mocks/ui-webgl/provision-genesis.html``). The cinematic
narration is pure *presentation*; **when** it advances and ends is driven by
a stream of ``provision.*`` events. This module exposes that stream as a
read-only Server-Sent Events (SSE) endpoint, reusing the exact fan-out
plumbing the live cockpit uses (:mod:`fdai.delivery.read_api.live_stream`).

Contract
--------

- **Read-only.** ``GET`` only; there is no matching mutating verb. The
  console renders provisioning progress, it never *executes* provisioning
  (``app-shape.instructions.md`` § Operator console - the console is a
  read surface, the executor holds the only privileged identity).
- **Same auth gate.** The route uses the identical ``authorize`` coroutine
  the snapshot routes use (dev-mode anonymous, prod reader-role token).
- **Opt-in.** :func:`~fdai.delivery.read_api.main.build_app` registers this
  route only when a :class:`ProvisionStreamConfig` is supplied. Upstream
  default is *off*.

Wire format (why ``event="message"``)
--------------------------------------

The Genesis client subscribes with a bare ``EventSource`` and reads
``es.onmessage`` - which fires only for the default (unnamed / ``message``)
SSE event type. So every :class:`ProvisionEvent` is encoded with
``event="message"`` and the *semantic* type lives inside the JSON payload as
``{"type": "provision.done", ...}``. The generic route
(:func:`~fdai.delivery.read_api.live_stream.make_live_stream_route`) already
emits a named ``event: hello`` boot frame and ``: keepalive`` comments; the
client's ``onmessage`` ignores both, exactly as intended.

Producers
---------

- **Bootstrap (surface A).** The local ``azd up`` wrapper parses
  ``terraform apply -json`` via
  :mod:`fdai.delivery.provisioning.terraform_bridge` and publishes the
  resulting :class:`ProvisionEvent` s onto this sink. The console does not
  exist yet at Day-1, so that path serves Genesis locally.
- **In-product (surface B).** A re-provision triggered from inside the
  running control plane rides the event bus; a relay publishes
  :class:`ProvisionEvent` s onto the same sink and this route fans them out
  to the console.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

from starlette.requests import Request
from starlette.routing import Route

from fdai.delivery.read_api.live_stream import make_live_stream_route
from fdai.shared.providers.sse import SseEvent, SseSink

# The channel provisioning publishers fan out on. A relay / bridge MUST
# publish onto this same channel for its events to reach the console.
DEFAULT_CHANNEL = "fdai.provision.events"
DEFAULT_ROUTE_PATH = "/provision/stream"

# The SSE `event:` name. Kept as the default ("message") so the Genesis
# client's bare `EventSource.onmessage` receives every provision event; the
# semantic type is carried inside the JSON payload's `type` field.
_SSE_EVENT_NAME = "message"


class ProvisionPhase(StrEnum):
    """The lifecycle phases a provisioning source can report.

    The wire ``type`` is ``"provision." + value`` (e.g. ``provision.done``),
    matching the contract documented in the Genesis mock.
    """

    PROGRESS = "progress"
    """A resource finished; ``fraction`` (0..1) is how much is up."""

    WAITING = "waiting"
    """A resource is retrying / slow - an honest hold, not a failure."""

    RESUMED = "resumed"
    """A previously-waiting resource recovered."""

    DONE = "done"
    """Every resource is up; ``console_url`` (if known) is where to go."""

    FAILED = "failed"
    """A resource failed terminally; ``node`` / ``reason`` explain it."""


def _iso_now() -> str:
    now = datetime.now(UTC)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


@dataclass(frozen=True, slots=True)
class ProvisionEvent:
    """One provisioning progress signal.

    Immutable value object. Fields beyond ``phase`` are phase-specific and
    default to ``None``; :meth:`to_sse_event` omits ``None`` fields from the
    JSON payload so the wire stays compact and the client only sees what a
    phase actually carries.
    """

    phase: ProvisionPhase
    fraction: float | None = None
    node: str | None = None
    reason: str | None = None
    console_url: str | None = None
    correlation_id: str | None = None
    ts: str | None = None

    def __post_init__(self) -> None:
        if self.fraction is not None and not (0.0 <= self.fraction <= 1.0):
            raise ValueError(f"fraction MUST be in [0, 1], got {self.fraction!r}")
        if self.phase in (ProvisionPhase.WAITING, ProvisionPhase.FAILED) and not self.node:
            raise ValueError(f"{self.phase.value} events MUST carry a node")

    @property
    def wire_type(self) -> str:
        """The ``type`` string on the wire, e.g. ``provision.done``."""
        return f"provision.{self.phase.value}"

    def to_payload(self) -> dict[str, Any]:
        """Return the JSON-serialisable payload (``None`` fields omitted)."""
        payload: dict[str, Any] = {"type": self.wire_type, "ts": self.ts or _iso_now()}
        if self.fraction is not None:
            payload["fraction"] = self.fraction
        if self.node is not None:
            payload["node"] = self.node
        if self.reason is not None:
            payload["reason"] = self.reason
        if self.console_url is not None:
            payload["console_url"] = self.console_url
        return payload

    def to_sse_event(self) -> SseEvent:
        """Encode as an :class:`SseEvent` the generic route can serialise.

        ``event`` is ``"message"`` so a bare ``EventSource.onmessage``
        receives it; the semantic type is inside ``data`` as ``type``.
        """
        return SseEvent(
            id=self.correlation_id,
            event=_SSE_EVENT_NAME,
            data=json.dumps(self.to_payload(), separators=(",", ":")),
        )


@runtime_checkable
class ProvisionPublisher(Protocol):
    """Publish a :class:`ProvisionEvent` to every stream subscriber."""

    async def emit(self, event: ProvisionEvent) -> None: ...


@dataclass(frozen=True, slots=True)
class SseProvisionPublisher:
    """Concrete :class:`ProvisionPublisher` backed by an :class:`SseSink`.

    A bootstrap bridge or an in-product relay constructs this bound to the
    same sink the :class:`ProvisionStreamConfig` route reads from, then
    calls :meth:`emit` for each progress signal.
    """

    sink: SseSink
    channel: str = DEFAULT_CHANNEL

    async def emit(self, event: ProvisionEvent) -> None:
        await self.sink.publish(self.channel, event.to_sse_event())


@dataclass(frozen=True, slots=True)
class ProvisionStreamConfig:
    """Composition-root configuration for the provisioning SSE surface.

    A composition supplies ``sink`` (the shared fan-out point the producer
    writes to). Leaving ``sink`` as ``None`` makes :func:`build_app` create
    an in-memory sink - the endpoint then simply waits (the honest ambient
    state) until a producer is wired, which is exactly what the Genesis
    client renders while nothing is happening.
    """

    path: str = DEFAULT_ROUTE_PATH
    channel: str = DEFAULT_CHANNEL
    keepalive_seconds: float = 15.0
    sink: SseSink | None = None

    def __post_init__(self) -> None:
        if not self.path.startswith("/"):
            raise ValueError(f"ProvisionStreamConfig.path MUST start with '/', got {self.path!r}")
        if not self.channel:
            raise ValueError("ProvisionStreamConfig.channel MUST be non-empty")
        if self.keepalive_seconds <= 0:
            raise ValueError("keepalive_seconds MUST be positive")


def make_provision_stream_route(
    *,
    sink: SseSink,
    channel: str,
    path: str,
    keepalive_seconds: float,
    authorize: Callable[[Request], Awaitable[str]],
) -> Route:
    """Return the ``GET`` provisioning SSE Route.

    Delegates to the generic live-stream plumbing - the fan-out loop,
    keepalive, and disconnect handling are identical; only the channel and
    path differ. ``authorize`` is the same coroutine the snapshot routes use.
    """
    return make_live_stream_route(
        sink=sink,
        channel=channel,
        path=path,
        keepalive_seconds=keepalive_seconds,
        authorize=authorize,
    )


__all__ = [
    "DEFAULT_CHANNEL",
    "DEFAULT_ROUTE_PATH",
    "ProvisionEvent",
    "ProvisionPhase",
    "ProvisionPublisher",
    "ProvisionStreamConfig",
    "SseProvisionPublisher",
    "make_provision_stream_route",
]
