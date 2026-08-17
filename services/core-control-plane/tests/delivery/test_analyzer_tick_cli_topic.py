from __future__ import annotations

import pytest
from fdai.delivery.analyzer_tick_cli import (
    INGRESS_TOPIC_ENV,
    TOPIC_ENV,
    resolve_finding_topic,
)


def test_findings_default_to_the_raw_ingress_topic() -> None:
    assert resolve_finding_topic({INGRESS_TOPIC_ENV: "aw.change.events"}) == "aw.change.events"


def test_explicit_analyzer_topic_overrides_the_ingress_topic() -> None:
    environ = {TOPIC_ENV: "aw.custom.events", INGRESS_TOPIC_ENV: "aw.change.events"}

    assert resolve_finding_topic(environ) == "aw.custom.events"


def test_missing_ingress_topic_is_a_configuration_error() -> None:
    with pytest.raises(RuntimeError):
        resolve_finding_topic({TOPIC_ENV: "   "})
