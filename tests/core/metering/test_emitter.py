"""Tests for :class:`fdai.core.metering.emitter.MeteringEmitter`."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from fdai.core.metering.emitter import MeteringEmitter
from fdai.core.metering.pricing import PricingTable
from fdai.core.metering.records import InvocationMode, LlmInvocation
from fdai.core.metering.sink import InMemoryMeteringSink
from fdai.core.metering.usage import TokenUsage
from fdai.shared.telemetry.correlation import with_correlation

_FIXED = datetime(2026, 7, 10, 8, 30, tzinfo=UTC)
_USAGE = TokenUsage(prompt_tokens=1000, completion_tokens=500)


def _emitter(sink: InMemoryMeteringSink, *, pricing: PricingTable | None = None) -> MeteringEmitter:
    return MeteringEmitter(
        sink=sink,
        capability_id="t2.reasoner.primary",
        model_key="gpt-4o",
        tier="T2",
        pricing=pricing,
        mode=InvocationMode.ENFORCE,
        clock=lambda: _FIXED,
    )


async def test_emit_with_explicit_correlation_records_unpriced() -> None:
    sink = InMemoryMeteringSink()
    await _emitter(sink).emit_safe(_USAGE, correlation_id="evt-9")
    (record,) = await sink.invocations()
    assert record.correlation_id == "evt-9"
    assert record.occurred_at == _FIXED
    assert record.usage == _USAGE
    assert record.cost is None


async def test_emit_computes_cost_with_pricing() -> None:
    sink = InMemoryMeteringSink()
    pricing = PricingTable.from_mapping(
        {"gpt-4o": {"input_per_1k": "2.50", "output_per_1k": "10.00", "currency": "USD"}}
    )
    await _emitter(sink, pricing=pricing).emit_safe(_USAGE, correlation_id="evt-1")
    (record,) = await sink.invocations()
    # 1000/1000*2.50 + 500/1000*10.00 = 2.50 + 5.00 = 7.50
    assert record.cost == Decimal("7.50")
    # H3: the invocation carries the price's currency so a rollup never
    # mixes units silently.
    assert record.currency == "USD"


async def test_emit_unpriced_key_records_unknown_cost() -> None:
    # H10: a pricing table without the model_key records usage with an
    # unknown (null) cost rather than guessing.
    sink = InMemoryMeteringSink()
    pricing = PricingTable.from_mapping(
        {"other-model": {"input_per_1k": "1.0", "output_per_1k": "1.0"}}
    )
    await _emitter(sink, pricing=pricing).emit_safe(_USAGE, correlation_id="evt-1")
    (record,) = await sink.invocations()
    assert record.cost is None
    assert record.currency is None


async def test_emit_reads_correlation_from_context() -> None:
    sink = InMemoryMeteringSink()
    with with_correlation("ctx-evt"):
        await _emitter(sink).emit_safe(_USAGE)
    (record,) = await sink.invocations()
    assert record.correlation_id == "ctx-evt"


async def test_emit_without_correlation_uses_fallback_bucket() -> None:
    sink = InMemoryMeteringSink()
    await _emitter(sink).emit_safe(_USAGE)
    (record,) = await sink.invocations()
    # H4: no correlation is filed under the explicit "uncorrelated" bucket
    # so daily/monthly totals stay whole instead of silently dropping spend.
    assert record.correlation_id == "uncorrelated"


async def test_emit_safe_swallows_sink_failure() -> None:
    class _FailingSink:
        async def record(self, invocation: LlmInvocation) -> None:
            raise RuntimeError("backend down")

    emitter = MeteringEmitter(
        sink=_FailingSink(),
        capability_id="t2.reasoner.primary",
        model_key="gpt-4o",
        tier="T2",
        clock=lambda: _FIXED,
    )
    # MUST NOT raise into the caller's hot path.
    await emitter.emit_safe(_USAGE, correlation_id="evt-1")


@pytest.mark.parametrize(
    ("field", "value"),
    [("capability_id", ""), ("model_key", ""), ("tier", "")],
)
def test_ctor_rejects_empty_binding_fields(field: str, value: str) -> None:
    kwargs: dict[str, object] = {
        "sink": InMemoryMeteringSink(),
        "capability_id": "c",
        "model_key": "m",
        "tier": "T2",
    }
    kwargs[field] = value
    with pytest.raises(ValueError, match=field):
        MeteringEmitter(**kwargs)  # type: ignore[arg-type]
