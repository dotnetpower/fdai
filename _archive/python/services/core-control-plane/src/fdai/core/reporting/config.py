"""Runtime configuration for :class:`~fdai.core.reporting.engine.ReportEngine`.

Kept as a separate module (rather than a nested dataclass in ``engine.py``)
so the config surface is discoverable from the package `__init__` and can
be extended by a fork without editing the engine.

Every field is optional; ``ReportEngineConfig()`` matches the historical
behavior (no timeout, unlimited concurrency, no per-report widget cap).
"""

from __future__ import annotations

from dataclasses import dataclass

# Absolute maximum any config may specify - defense in depth.
_HARD_WIDGET_CEILING = 200
_HARD_CONCURRENCY_CEILING = 32
_HARD_TIMEOUT_SECONDS = 120.0


@dataclass(frozen=True, slots=True)
class ReportEngineConfig:
    """Runtime knobs for the render loop.

    All fields are safe defaults - a call ``ReportEngine(...)`` without a
    config preserves the legacy sync-in-declaration-order behavior.
    """

    per_widget_timeout_seconds: float | None = None
    """When set, wraps each datasource call in :func:`asyncio.wait_for`.
    Timeouts render the widget with an ``error`` payload instead of
    hanging the whole report. Bounded by :data:`_HARD_TIMEOUT_SECONDS`."""

    max_concurrent_widgets: int | None = None
    """When set, runs widgets in parallel with a bounded semaphore. The
    widget-declaration order is preserved in the rendered payload; only
    the *execution* is fanned out. ``None`` keeps sequential execution.
    Bounded by :data:`_HARD_CONCURRENCY_CEILING`."""

    max_widgets_per_report: int = _HARD_WIDGET_CEILING
    """Hard cap on the number of widgets any report may render
    (including group-widget children). A spec that exceeds it renders
    with a single ``error`` sentinel widget at the top level."""

    max_error_message_chars: int = 512
    """Cap on the length of :attr:`RenderedWidget.error` strings so a
    long traceback cannot inflate the JSON response body."""

    def __post_init__(self) -> None:
        if self.per_widget_timeout_seconds is not None:
            timeout = float(self.per_widget_timeout_seconds)
            if timeout <= 0:
                raise ValueError("per_widget_timeout_seconds MUST be > 0")
            if timeout > _HARD_TIMEOUT_SECONDS:
                raise ValueError(f"per_widget_timeout_seconds MUST be <= {_HARD_TIMEOUT_SECONDS}")
        if self.max_concurrent_widgets is not None:
            concurrency = int(self.max_concurrent_widgets)
            if concurrency <= 0:
                raise ValueError("max_concurrent_widgets MUST be > 0")
            if concurrency > _HARD_CONCURRENCY_CEILING:
                raise ValueError(f"max_concurrent_widgets MUST be <= {_HARD_CONCURRENCY_CEILING}")
        if not (1 <= self.max_widgets_per_report <= _HARD_WIDGET_CEILING):
            raise ValueError(f"max_widgets_per_report MUST be in [1, {_HARD_WIDGET_CEILING}]")
        if self.max_error_message_chars < 32:
            raise ValueError("max_error_message_chars MUST be >= 32")


__all__ = ["ReportEngineConfig"]
