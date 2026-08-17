from __future__ import annotations

import pytest
from fdai.delivery.analyzer_tick_cli import (
    INGRESS_TOPIC_ENV,
    TOPIC_ENV,
    TRACE_WINDOW_ENV,
    resolve_finding_topic,
    resolve_trace_window_seconds,
)


def test_findings_default_to_the_raw_ingress_topic() -> None:
    assert resolve_finding_topic({INGRESS_TOPIC_ENV: "aw.change.events"}) == "aw.change.events"


def test_explicit_analyzer_topic_overrides_the_ingress_topic() -> None:
    environ = {TOPIC_ENV: "aw.custom.events", INGRESS_TOPIC_ENV: "aw.change.events"}

    assert resolve_finding_topic(environ) == "aw.custom.events"


def test_missing_ingress_topic_is_a_configuration_error() -> None:
    with pytest.raises(RuntimeError):
        resolve_finding_topic({TOPIC_ENV: "   "})


def test_trace_window_defaults_to_the_analyzer_window() -> None:
    assert resolve_trace_window_seconds({}, 300) == 300


def test_trace_window_can_be_shortened_independently() -> None:
    assert resolve_trace_window_seconds({TRACE_WINDOW_ENV: "60"}, 300) == 60


def test_non_positive_trace_window_fails_closed() -> None:
    with pytest.raises(ValueError):
        resolve_trace_window_seconds({TRACE_WINDOW_ENV: "0"}, 300)
