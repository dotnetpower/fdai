from __future__ import annotations

from decimal import Decimal

import pytest

from fdai.core.metering import InMemoryMeteringSink, PricingTable, TokenUsage
from fdai.delivery.operator_api.routes.chat_backend_factory import (
    _DEFAULT_NARRATOR_TURN_TIMEOUT_SECONDS,
    _chat_metering,
    _narrator_turn_timeout_seconds,
    _resolved_model_keys,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    (
        (None, _DEFAULT_NARRATOR_TURN_TIMEOUT_SECONDS),
        ("invalid", _DEFAULT_NARRATOR_TURN_TIMEOUT_SECONDS),
        ("0", _DEFAULT_NARRATOR_TURN_TIMEOUT_SECONDS),
        ("301", _DEFAULT_NARRATOR_TURN_TIMEOUT_SECONDS),
        ("45", 45.0),
        ("1.5", 1.5),
    ),
)
def test_narrator_turn_timeout_is_bounded(raw: str | None, expected: float) -> None:
    env = {} if raw is None else {"FDAI_NARRATOR_TURN_TIMEOUT_SECONDS": raw}

    assert _narrator_turn_timeout_seconds(env) == expected


async def test_chat_metering_prices_explicit_resolved_family() -> None:
    sink = InMemoryMeteringSink()
    pricing = PricingTable.from_mapping(
        {
            "gpt-4o-mini": {
                "input_per_1k": "0.15",
                "output_per_1k": "0.60",
                "currency": "USD",
            }
        }
    )
    model_keys = _resolved_model_keys(
        {
            "capabilities": [
                {"name": "narrator-gpt-4o-mini", "family": "gpt-4o-mini"},
            ]
        }
    )

    emitter = _chat_metering(
        sink,
        "narrator-gpt-4o-mini",
        pricing=pricing,
        resolved_model_keys=model_keys,
    )
    assert emitter is not None
    await emitter.emit_safe(TokenUsage(prompt_tokens=1_000, completion_tokens=500))

    (record,) = await sink.invocations()
    assert record.model_key == "gpt-4o-mini"
    assert record.cost == Decimal("0.45")
    assert record.currency == "USD"


async def test_chat_metering_does_not_guess_missing_family() -> None:
    sink = InMemoryMeteringSink()
    pricing = PricingTable.from_mapping(
        {
            "gpt-4o-mini": {
                "input_per_1k": "0.15",
                "output_per_1k": "0.60",
            }
        }
    )

    emitter = _chat_metering(
        sink,
        "narrator-gpt-4o-mini",
        pricing=pricing,
        resolved_model_keys={},
    )
    assert emitter is not None
    await emitter.emit_safe(TokenUsage(prompt_tokens=1_000, completion_tokens=500))

    (record,) = await sink.invocations()
    assert record.model_key == "narrator-gpt-4o-mini"
    assert record.cost is None
    assert record.currency is None


def test_resolved_model_keys_reject_conflicting_families() -> None:
    model_keys = _resolved_model_keys(
        {
            "capabilities": [
                {"name": "narrator-shared", "family": "gpt-4o-mini"},
                {"name": "narrator-shared", "family": "gpt-5-mini"},
            ]
        }
    )

    assert model_keys == {}
