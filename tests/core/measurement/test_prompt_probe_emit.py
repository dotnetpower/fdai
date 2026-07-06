"""Unit tests for :mod:`aiopspilot.core.measurement.prompt_probe_emit`."""

from __future__ import annotations

import pytest

from aiopspilot.core.measurement.prompt_probe import (
    CitationScores,
    RecognitionResult,
    summarize_recognition,
)
from aiopspilot.core.measurement.prompt_probe_emit import (
    METRIC_ADHERENCE_PASS_RATE,
    METRIC_ADHERENCE_VIOLATION_COUNT,
    METRIC_CANARY_ECHO_RATE,
    METRIC_CITATION_F1_MEAN,
    METRIC_SAMPLE_COUNT,
    RowUnit,
    emit_kpi_rows,
)
from aiopspilot.core.measurement.prompt_probe_runner import RecognitionRunReport


def _report(*results: RecognitionResult) -> RecognitionRunReport:
    return RecognitionRunReport(
        samples=tuple(results),
        summary=summarize_recognition(list(results)),
    )


def _row_by_metric(rows: tuple, metric: str, **dims: str) -> object:
    """Locate one row by metric + dimension subset; raise if missing."""

    for row in rows:
        if row.metric != metric:
            continue
        if all(row.dimensions.get(k) == v for k, v in dims.items()):
            return row
    raise AssertionError(f"no row with metric={metric!r} and dims={dims!r}; got {rows!r}")


class TestEmitKpiRows:
    def test_empty_batch_still_emits_sample_count_zero(self) -> None:
        """A dashboard series that always publishes ``sample_count``
        MUST NOT silently disappear on an empty run - the caller
        needs to see ``0`` explicitly."""

        rows = emit_kpi_rows(_report())
        # Only the sample count row lands - no adherence, no citations,
        # no per-code / per-layer rows to emit.
        assert len(rows) == 1
        assert rows[0].metric == METRIC_SAMPLE_COUNT
        assert rows[0].value == 0.0
        assert rows[0].unit is RowUnit.COUNT

    def test_all_pass_emits_sample_count_and_pass_rate(self) -> None:
        report = _report(
            RecognitionResult(True, (), {}, None),
            RecognitionResult(True, (), {}, None),
        )
        rows = emit_kpi_rows(report)

        sample_row = _row_by_metric(rows, METRIC_SAMPLE_COUNT)
        adherence_row = _row_by_metric(rows, METRIC_ADHERENCE_PASS_RATE)
        assert sample_row.value == 2.0
        assert adherence_row.value == pytest.approx(1.0)
        assert adherence_row.unit is RowUnit.RATIO

    def test_violation_counts_are_one_row_per_code_with_stable_ordering(
        self,
    ) -> None:
        """Each violation code emits its own row; the same code
        aggregates counts across the batch; rows are sorted by code
        so a downstream renderer produces a stable dashboard order."""

        report = _report(
            RecognitionResult(
                False,
                ("missing-field:action_type",),
                {},
                None,
            ),
            RecognitionResult(
                False,
                (
                    "missing-field:action_type",
                    "wrong-type:params",
                ),
                {},
                None,
            ),
        )
        rows = emit_kpi_rows(report)

        codes_in_order = [
            row.dimensions["code"] for row in rows if row.metric == METRIC_ADHERENCE_VIOLATION_COUNT
        ]
        assert codes_in_order == sorted(codes_in_order)

        missing_row = _row_by_metric(
            rows, METRIC_ADHERENCE_VIOLATION_COUNT, code="missing-field:action_type"
        )
        wrong_type_row = _row_by_metric(
            rows, METRIC_ADHERENCE_VIOLATION_COUNT, code="wrong-type:params"
        )
        assert missing_row.value == 2.0
        assert wrong_type_row.value == 1.0

    def test_per_layer_canary_rows_use_measured_denominator(self) -> None:
        """The emitter MUST preserve the aggregate's measured
        denominator - a layer measured only in some samples MUST
        show its actual rate, not a diluted one."""

        report = _report(
            RecognitionResult(
                True,
                (),
                {"base": True, "tool-manifest": True},
                None,
            ),
            RecognitionResult(True, (), {"base": False}, None),
        )
        rows = emit_kpi_rows(report)
        base_row = _row_by_metric(rows, METRIC_CANARY_ECHO_RATE, layer_id="base")
        tool_row = _row_by_metric(rows, METRIC_CANARY_ECHO_RATE, layer_id="tool-manifest")
        # base: 1/2 samples echoed = 0.5
        assert base_row.value == pytest.approx(0.5)
        # tool-manifest measured in one sample only, echoed there -> 1.0
        assert tool_row.value == pytest.approx(1.0)

    def test_citation_f1_row_absent_when_no_sample_scored(self) -> None:
        """The dashboard reader would misread an emitted ``0.0`` on a
        batch that opted out of citation scoring as "we tried and
        failed". The emitter MUST skip the row instead."""

        report = _report(RecognitionResult(True, (), {}, None))
        rows = emit_kpi_rows(report)
        assert all(row.metric != METRIC_CITATION_F1_MEAN for row in rows)

    def test_citation_f1_row_present_when_at_least_one_sample_scored(self) -> None:
        report = _report(
            RecognitionResult(True, (), {}, CitationScores(0.8, 0.6, 0.7)),
        )
        rows = emit_kpi_rows(report)
        row = _row_by_metric(rows, METRIC_CITATION_F1_MEAN)
        assert row.value == pytest.approx(0.7)
        assert row.unit is RowUnit.RATIO

    def test_base_dimensions_are_merged_into_every_row(self) -> None:
        """Every emitted row MUST carry the caller-supplied base
        dimensions - a per-capability run publishing rows without
        the capability label would be indistinguishable from any
        other run."""

        report = _report(
            RecognitionResult(
                False,
                ("missing-field:x",),
                {"base": True},
                CitationScores(1.0, 1.0, 1.0),
            ),
        )
        rows = emit_kpi_rows(report, dimensions={"capability": "t2.reasoner.primary"})
        for row in rows:
            assert row.dimensions.get("capability") == "t2.reasoner.primary"

    def test_metric_specific_dimensions_do_not_leak_across_rows(self) -> None:
        """The ``code`` label MUST NOT leak into a canary echo row
        and vice versa - each row's dimension set is scoped to its
        own metric family."""

        report = _report(
            RecognitionResult(
                False,
                ("missing-field:x",),
                {"base": True},
                None,
            ),
        )
        rows = emit_kpi_rows(report)
        for row in rows:
            if row.metric == METRIC_CANARY_ECHO_RATE:
                assert "code" not in row.dimensions
            if row.metric == METRIC_ADHERENCE_VIOLATION_COUNT:
                assert "layer_id" not in row.dimensions
