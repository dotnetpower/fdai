"""Stable OpenTelemetry metrics and spans for product routing transitions."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final, Protocol

from fdai.shared.telemetry.metrics import get_meter
from fdai.shared.telemetry.tracing import get_tracer

_DOMAINS: Final = frozenset({"channel", "extension", "model", "scheduler", "security"})
_OUTCOMES: Final = frozenset(
    {"accepted", "rejected", "enabled", "disabled", "failed", "recovered", "selected"}
)
_MAX_ATTRIBUTE_CHARS: Final = 200
_LOGGER = logging.getLogger(__name__)
_DEFAULT_EMITTER: RoutingTransitionEmitter | None = None


@dataclass(frozen=True, slots=True)
class RoutingTransition:
    domain: str
    name: str
    outcome: str
    attributes: Mapping[str, str]

    def __post_init__(self) -> None:
        if self.domain not in _DOMAINS:
            raise ValueError("transition domain is not allowlisted")
        if self.outcome not in _OUTCOMES:
            raise ValueError("transition outcome is not allowlisted")
        if not self.name or len(self.name) > _MAX_ATTRIBUTE_CHARS:
            raise ValueError("transition name is empty or over the cap")
        if len(self.attributes) > 12:
            raise ValueError("transition attributes exceed the cap")
        for key, value in self.attributes.items():
            if not key or not value or len(key) > 64 or len(value) > _MAX_ATTRIBUTE_CHARS:
                raise ValueError("transition attribute is empty or over the cap")


class RoutingTransitionEmitter:
    """Emit one stable counter increment and one span without arbitrary fields."""

    def __init__(self, *, instrumentation_name: str = "fdai.transitions") -> None:
        self._counter = get_meter(instrumentation_name).create_counter(
            "fdai.transition.count",
            description=(
                "Count of FDAI channel, extension, model, scheduler, and security transitions."
            ),
        )
        self._tracer = get_tracer(instrumentation_name)

    def emit(self, transition: RoutingTransition) -> None:
        attributes = {
            "fdai.transition.domain": transition.domain,
            "fdai.transition.name": transition.name,
            "fdai.transition.outcome": transition.outcome,
            **{
                f"fdai.transition.{key}": value
                for key, value in sorted(transition.attributes.items())
            },
        }
        self._counter.add(1, attributes)
        with self._tracer.start_as_current_span("fdai.transition") as span:
            for key, value in attributes.items():
                span.set_attribute(key, value)


class RoutingTransitionSink(Protocol):
    def emit(self, transition: RoutingTransition) -> None: ...


class InMemoryRoutingTransitionSink:
    def __init__(self) -> None:
        self.transitions: list[RoutingTransition] = []

    def emit(self, transition: RoutingTransition) -> None:
        self.transitions.append(transition)


def default_transition_emitter() -> RoutingTransitionEmitter:
    global _DEFAULT_EMITTER
    if _DEFAULT_EMITTER is None:
        _DEFAULT_EMITTER = RoutingTransitionEmitter()
    return _DEFAULT_EMITTER


def emit_transition_safely(
    sink: RoutingTransitionSink | None,
    transition: RoutingTransition,
) -> None:
    if sink is None:
        return
    try:
        sink.emit(transition)
    except Exception:
        _LOGGER.error(
            "routing_transition_emit_failed",
            extra={"domain": transition.domain, "name": transition.name},
            exc_info=True,
        )


__all__ = [
    "InMemoryRoutingTransitionSink",
    "RoutingTransition",
    "RoutingTransitionEmitter",
    "RoutingTransitionSink",
    "default_transition_emitter",
    "emit_transition_safely",
]
