"""LiveBlastProbe Protocol + NoOpBlastProbe fake - invariant tests (M1.1).

The probe is a ceiling-lowering Axis-E signal; a fake that returns
``no_opinion`` by default keeps the static ceiling in charge until a
live adapter lands. Tests here prove the Protocol shape, the four
verdict cases, the timeout / error surface, and the assertion helpers
the RiskGate tests rely on.
"""

from __future__ import annotations

import pytest
from fdai.shared.providers.blast_probe import (
    BlastProbeConfigError,
    BlastProbeError,
    BlastProbeTimeoutError,
    LiveBlastProbe,
    ProbeQuery,
    ProbeResult,
    ProbeVerdict,
)
from fdai.shared.providers.testing import NoOpBlastProbe
from fdai.shared.providers.testing.blast_probe import (
    NoOpBlastProbe as _AlsoImportable,
)


def _query(**overrides: object) -> ProbeQuery:
    base = {
        "probe_id": "vm_traffic_last_5m",
        "target_ref": "res-1",
        "deadline_seconds": 5.0,
    }
    base.update(overrides)
    return ProbeQuery(**base)  # type: ignore[arg-type]


class TestProbeQueryValidation:
    def test_probe_id_must_be_non_empty(self) -> None:
        with pytest.raises(ValueError, match="probe_id"):
            _query(probe_id="")

    def test_target_ref_must_be_non_empty(self) -> None:
        with pytest.raises(ValueError, match="target_ref"):
            _query(target_ref="")

    def test_deadline_must_be_positive(self) -> None:
        with pytest.raises(ValueError, match="deadline_seconds"):
            _query(deadline_seconds=0.0)
        with pytest.raises(ValueError, match="deadline_seconds"):
            _query(deadline_seconds=-1.0)

    def test_query_is_frozen(self) -> None:
        q = _query()
        with pytest.raises((AttributeError, TypeError)):
            q.probe_id = "other"  # type: ignore[misc]


class TestProtocolConformance:
    def test_no_op_probe_satisfies_protocol(self) -> None:
        probe: LiveBlastProbe = NoOpBlastProbe()
        assert isinstance(probe, LiveBlastProbe)

    def test_top_level_re_export_is_the_same_class(self) -> None:
        assert NoOpBlastProbe is _AlsoImportable


class TestErrorHierarchy:
    def test_timeout_is_a_blast_probe_error(self) -> None:
        exc = BlastProbeTimeoutError("deadline exceeded")
        assert isinstance(exc, BlastProbeError)
        assert exc.kind == "timeout"

    def test_config_is_a_blast_probe_error(self) -> None:
        exc = BlastProbeConfigError("unknown aggregation")
        assert isinstance(exc, BlastProbeError)
        assert exc.kind == "config"

    def test_blast_probe_error_is_a_runtime_error(self) -> None:
        exc = BlastProbeTimeoutError("t")
        assert isinstance(exc, RuntimeError)


class TestNoOpBlastProbeDefault:
    @pytest.mark.asyncio
    async def test_default_is_no_opinion(self) -> None:
        probe = NoOpBlastProbe()
        result = await probe.measure(_query())
        assert result.verdict is ProbeVerdict.NO_OPINION
        assert "NoOpBlastProbe" in result.reason
        assert result.degraded is False

    @pytest.mark.asyncio
    async def test_queries_are_recorded(self) -> None:
        probe = NoOpBlastProbe()
        await probe.measure(_query(probe_id="a", target_ref="t1"))
        await probe.measure(_query(probe_id="b", target_ref="t2"))
        assert len(probe.queries) == 2
        assert probe.queries[0].probe_id == "a"
        assert probe.queries[1].target_ref == "t2"

    @pytest.mark.asyncio
    async def test_queries_snapshot_is_immutable_view(self) -> None:
        probe = NoOpBlastProbe()
        await probe.measure(_query())
        snapshot = probe.queries
        await probe.measure(_query(target_ref="another"))
        assert len(snapshot) == 1  # not affected by later call


class TestForcedVerdict:
    @pytest.mark.asyncio
    async def test_force_quiet(self) -> None:
        probe = NoOpBlastProbe()
        probe.force_verdict(ProbeVerdict.QUIET)
        result = await probe.measure(_query())
        assert result.verdict is ProbeVerdict.QUIET

    @pytest.mark.asyncio
    async def test_force_active_with_reason_and_metrics(self) -> None:
        probe = NoOpBlastProbe()
        probe.force_verdict(
            ProbeVerdict.ACTIVE,
            reason="p95 latency > threshold",
            metrics={"p95_ms": 420.0},
        )
        result = await probe.measure(_query())
        assert result.verdict is ProbeVerdict.ACTIVE
        assert result.reason == "p95 latency > threshold"
        assert result.metrics == {"p95_ms": 420.0}

    @pytest.mark.asyncio
    async def test_force_overloaded_with_degraded_flag(self) -> None:
        probe = NoOpBlastProbe()
        probe.force_verdict(ProbeVerdict.OVERLOADED, degraded=True, reason="partial data")
        result = await probe.measure(_query())
        assert result.verdict is ProbeVerdict.OVERLOADED
        assert result.degraded is True

    @pytest.mark.asyncio
    async def test_force_is_one_shot(self) -> None:
        probe = NoOpBlastProbe()
        probe.force_verdict(ProbeVerdict.QUIET)
        first = await probe.measure(_query())
        second = await probe.measure(_query())
        assert first.verdict is ProbeVerdict.QUIET
        assert second.verdict is ProbeVerdict.NO_OPINION


class TestFailureInjection:
    @pytest.mark.asyncio
    async def test_next_timeout_raises_once(self) -> None:
        probe = NoOpBlastProbe()
        probe.next_timeout()
        with pytest.raises(BlastProbeTimeoutError):
            await probe.measure(_query())
        # Next call is clean.
        result = await probe.measure(_query())
        assert result.verdict is ProbeVerdict.NO_OPINION

    @pytest.mark.asyncio
    async def test_next_error_raises_once(self) -> None:
        probe = NoOpBlastProbe()
        probe.next_error(RuntimeError("boom"))
        with pytest.raises(RuntimeError, match="boom"):
            await probe.measure(_query())
        # Next call is clean.
        result = await probe.measure(_query())
        assert result.verdict is ProbeVerdict.NO_OPINION

    @pytest.mark.asyncio
    async def test_error_still_records_the_query(self) -> None:
        # The failure-injection hooks should NOT hide the query from the
        # audit-trace helper - the RiskGate needs to know a probe call
        # was attempted even on error.
        probe = NoOpBlastProbe()
        probe.next_error(RuntimeError("boom"))
        with pytest.raises(RuntimeError):
            await probe.measure(_query(probe_id="attempted"))
        assert probe.queries[0].probe_id == "attempted"


class TestProbeResultShape:
    def test_default_metrics_is_empty_mapping(self) -> None:
        result = ProbeResult(verdict=ProbeVerdict.QUIET)
        assert result.metrics == {}
        assert result.reason == ""
        assert result.degraded is False

    def test_result_is_frozen(self) -> None:
        result = ProbeResult(verdict=ProbeVerdict.QUIET)
        with pytest.raises((AttributeError, TypeError)):
            result.verdict = ProbeVerdict.ACTIVE  # type: ignore[misc]
