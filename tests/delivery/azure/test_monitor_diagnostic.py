"""Tests for the Azure Monitor Diagnostic AllMetrics stream normalizer."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

import pytest

from fdai.delivery.azure.monitor_diagnostic import (
    DiagnosticNormalizerOptions,
    iter_records_from_batch,
    normalize_diagnostic_records,
)
from fdai.shared.contracts.models import Mode

_ARM_ID = (
    "/SUBSCRIPTIONS/00000000-0000-0000-0000-000000000000"
    "/resourceGroups/EXAMPLE-RG/providers/Microsoft.DBforMySQL"
    "/flexibleServers/EXAMPLE-MYSQL"
)


def _record(
    *,
    metric: str = "cpu_percent",
    average: float | None = 82.5,
    timestamp: str = "2026-07-13T00:00:00Z",
    time_grain: str = "PT1M",
    resource_id: str = _ARM_ID,
) -> dict:
    row: dict = {
        "resourceId": resource_id,
        "metricName": metric,
        "timeGrain": time_grain,
        "count": 60,
        "total": 4950.0,
        "minimum": 40.0,
        "maximum": 92.3,
        "timeStamp": timestamp,
    }
    if average is not None:
        row["average"] = average
    return row


def _wrap(records: list[dict]) -> dict:
    return {"records": records}


def _opts(**overrides: object) -> DiagnosticNormalizerOptions:
    base: dict = {"metric_whitelist": frozenset({"cpu_percent"})}
    base.update(overrides)
    return DiagnosticNormalizerOptions(**base)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Options validation
# ---------------------------------------------------------------------------


def test_options_reject_unknown_aggregation() -> None:
    with pytest.raises(ValueError, match="aggregation MUST be one of"):
        DiagnosticNormalizerOptions(
            metric_whitelist=frozenset({"cpu_percent"}),
            aggregation="p95",
        )


def test_options_reject_empty_correlation_prefix() -> None:
    with pytest.raises(ValueError, match="correlation_id_prefix MUST be"):
        DiagnosticNormalizerOptions(
            metric_whitelist=frozenset({"x"}),
            correlation_id_prefix="",
        )


# ---------------------------------------------------------------------------
# Envelope shape
# ---------------------------------------------------------------------------


def test_records_wrapper_envelope() -> None:
    events = normalize_diagnostic_records(_wrap([_record()]), options=_opts())
    assert len(events) == 1
    assert events[0].event_type == "azure.metric_sample"


def test_bare_list_envelope() -> None:
    events = normalize_diagnostic_records([_record(), _record()], options=_opts())
    assert len(events) == 2


def test_single_record_envelope() -> None:
    events = normalize_diagnostic_records(_record(), options=_opts())
    assert len(events) == 1


def test_rejects_non_object_envelope() -> None:
    with pytest.raises(ValueError, match="MUST be a JSON object or array"):
        normalize_diagnostic_records("not-an-object", options=_opts())


def test_rejects_object_without_records_and_without_metric_name() -> None:
    with pytest.raises(ValueError, match="single record"):
        normalize_diagnostic_records({"unrelated": "shape"}, options=_opts())


def test_records_field_must_be_a_list() -> None:
    with pytest.raises(ValueError, match="'records' MUST be a list"):
        normalize_diagnostic_records({"records": {}}, options=_opts())


# ---------------------------------------------------------------------------
# Whitelist enforcement
# ---------------------------------------------------------------------------


def test_empty_whitelist_returns_no_events_and_warns(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Fail-closed: without an explicit whitelist we would emit the
    firehose. Return () and log a warning so the operator sees it."""
    with caplog.at_level(logging.WARNING, logger="fdai.delivery.azure.monitor_diagnostic"):
        events = normalize_diagnostic_records(
            _wrap([_record()]),
            options=DiagnosticNormalizerOptions(
                metric_whitelist=frozenset(),
            ),
        )
    assert events == ()
    assert any(r.message == "diagnostic_stream_no_whitelist" for r in caplog.records), (
        "no-whitelist warning was not emitted"
    )


def test_records_outside_whitelist_are_silently_skipped() -> None:
    events = normalize_diagnostic_records(
        _wrap([_record(metric="cpu_percent"), _record(metric="memory_percent")]),
        options=_opts(),
    )
    assert len(events) == 1
    assert events[0].payload["azure_metric_sample"]["azure_metric_name"] == "cpu_percent"


# ---------------------------------------------------------------------------
# Field mapping
# ---------------------------------------------------------------------------


def test_arm_id_is_lowercased_on_the_event() -> None:
    event = normalize_diagnostic_records(_wrap([_record()]), options=_opts())[0]
    assert event.resource_ref == _ARM_ID.lower()


def test_selected_aggregation_column_becomes_the_value() -> None:
    event = normalize_diagnostic_records(
        _wrap([_record()]),
        options=_opts(aggregation="maximum"),
    )[0]
    assert event.payload["azure_metric_sample"]["value"] == 92.3
    assert event.payload["azure_metric_sample"]["aggregation"] == "maximum"


def test_missing_selected_aggregation_column_skips_record() -> None:
    events = normalize_diagnostic_records(
        _wrap([_record(average=None)]),
        options=_opts(),  # default aggregation="average"
    )
    assert events == ()


def test_metric_name_map_renames_native_to_csp_neutral() -> None:
    event = normalize_diagnostic_records(
        _wrap([_record(metric="Percentage CPU")]),
        options=_opts(
            metric_whitelist=frozenset({"Percentage CPU"}),
            metric_name_map={"Percentage CPU": "cpu_percent"},
        ),
    )[0]
    ctx = event.payload["azure_metric_sample"]
    assert ctx["azure_metric_name"] == "Percentage CPU"
    assert ctx["metric_name"] == "cpu_percent"


def test_correlation_id_folds_per_series() -> None:
    """Every sample of the same (resource, metric) shares one correlation."""
    a = normalize_diagnostic_records(_wrap([_record()]), options=_opts())[0]
    b = normalize_diagnostic_records(
        _wrap([_record(timestamp="2026-07-13T00:01:00Z", average=79.0)]),
        options=_opts(),
    )[0]
    assert a.correlation_id == b.correlation_id
    # But the idempotency key is per-sample (fold under `timeStamp`).
    assert a.idempotency_key != b.idempotency_key


def test_default_mode_is_shadow() -> None:
    """Safety invariant: streaming samples never auto-enforce."""
    event = normalize_diagnostic_records(_wrap([_record()]), options=_opts())[0]
    assert event.mode is Mode.SHADOW


def test_enforce_mode_flows_when_options_override() -> None:
    event = normalize_diagnostic_records(
        _wrap([_record()]),
        options=_opts(default_mode=Mode.ENFORCE),
    )[0]
    assert event.mode is Mode.ENFORCE


def test_detected_at_matches_record_timestamp() -> None:
    event = normalize_diagnostic_records(_wrap([_record()]), options=_opts())[0]
    assert event.detected_at == datetime(2026, 7, 13, 0, 0, 0, tzinfo=UTC)


def test_raw_record_is_preserved_for_audit() -> None:
    record = _record()
    event = normalize_diagnostic_records(_wrap([record]), options=_opts())[0]
    assert event.payload["raw"] == record


# ---------------------------------------------------------------------------
# Per-record failure isolation
# ---------------------------------------------------------------------------


def test_malformed_record_does_not_kill_the_batch(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """One bad record produces a warning; the good ones still land."""
    bad = _record()
    bad["metricName"] = 42  # not a string
    good = _record(timestamp="2026-07-13T00:01:00Z", average=45.0)
    with caplog.at_level(logging.WARNING, logger="fdai.delivery.azure.monitor_diagnostic"):
        events = normalize_diagnostic_records(_wrap([bad, good]), options=_opts())
    assert len(events) == 1
    assert any(r.message == "diagnostic_stream_skipped_record" for r in caplog.records)


def test_iter_records_from_batch_drains_multiple_envelopes() -> None:
    batch = [
        _wrap([_record()]),
        [_record(timestamp="2026-07-13T00:01:00Z")],
        _record(timestamp="2026-07-13T00:02:00Z"),
        "not-an-envelope",  # dropped by the outer per-envelope try/except
    ]
    got = list(iter_records_from_batch(batch))
    assert len(got) == 3
