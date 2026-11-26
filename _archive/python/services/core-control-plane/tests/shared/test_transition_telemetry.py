"""Stable bounded transition telemetry tests."""

from __future__ import annotations

import pytest
from fdai.shared.telemetry.setup import _otlp_config
from fdai.shared.telemetry.transitions import RoutingTransition


def test_transition_schema_accepts_stable_product_domains() -> None:
    transition = RoutingTransition(
        domain="scheduler",
        name="dispatch.published",
        outcome="accepted",
        attributes={"schedule_kind": "interval", "mode": "shadow"},
    )
    assert transition.attributes["mode"] == "shadow"


@pytest.mark.parametrize(
    "kwargs",
    (
        {"domain": "unknown"},
        {"outcome": "maybe"},
        {"attributes": {"detail": "x" * 201}},
    ),
)
def test_transition_schema_rejects_unbounded_or_unknown_values(kwargs: dict[str, object]) -> None:
    values: dict[str, object] = {
        "domain": "security",
        "name": "pairing.rejected",
        "outcome": "rejected",
        "attributes": {"reason_code": "expired"},
    }
    values.update(kwargs)
    with pytest.raises(ValueError):
        RoutingTransition(**values)  # type: ignore[arg-type]


def test_otlp_endpoint_security_policy() -> None:
    assert _otlp_config("") == (None, False)
    assert _otlp_config("http://127.0.0.1:4317") == (
        "http://127.0.0.1:4317",
        True,
    )
    assert _otlp_config("https://collector.example.com:4317") == (
        "https://collector.example.com:4317",
        False,
    )
    with pytest.raises(ValueError, match="HTTPS"):
        _otlp_config("http://collector.example.com:4317")
    with pytest.raises(ValueError, match="credential-free"):
        _otlp_config("https://user:secret@collector.example.com:4317")
