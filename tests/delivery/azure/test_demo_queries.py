"""Tests for the SRE demo five-metric capture KQL template catalog."""

from __future__ import annotations

from fdai.delivery.azure.demo_queries import (
    METRIC_APIM_BACKEND_LATENCY_MS,
    METRIC_APIM_HTTP_5XX_RATE,
    METRIC_BACKEND_FIRST_BYTE_MS,
    METRIC_HEALTHY_HOST_COUNT,
    METRIC_HOST_CPU_PERCENT,
    METRIC_HOST_MEMORY_AVAILABLE_PCT,
    METRIC_HTTP_429_RATE,
    METRIC_MYSQL_ACTIVE_CONNECTIONS,
    METRIC_MYSQL_CPU_PERCENT,
    METRIC_NODE_CPU_PERCENT,
    METRIC_POD_RESTART_COUNT,
    METRIC_POD_RESTARTS,
    METRIC_REQUEST_FAILURE_RATE,
    METRIC_REQUEST_SURGE_RATIO,
    METRIC_ROLLOUT_STALL_DURATION_SECONDS,
    METRIC_ROLLOUT_STALL_SECONDS,
    default_metric_queries,
    sre_demo_analyzer_queries,
    sre_demo_capture_queries,
)
from fdai.delivery.azure.metric_logs import MetricKqlTemplate

_EXPECTED = {
    METRIC_HOST_CPU_PERCENT,
    METRIC_HOST_MEMORY_AVAILABLE_PCT,
    METRIC_POD_RESTARTS,
    METRIC_REQUEST_FAILURE_RATE,
    METRIC_ROLLOUT_STALL_SECONDS,
}


def test_catalog_contains_five_demo_metrics() -> None:
    got = set(sre_demo_capture_queries().keys())
    assert got == _EXPECTED, f"extra={got - _EXPECTED}, missing={_EXPECTED - got}"


def test_every_template_is_metric_kql_template() -> None:
    for template in sre_demo_capture_queries().values():
        assert isinstance(template, MetricKqlTemplate)


def test_no_template_interpolates_untrusted_input() -> None:
    """Injection guard: no {}, %, or shell metachars in the KQL body."""
    for name, template in sre_demo_capture_queries().items():
        # KQL is static text; presence of '{' or '%' would indicate a
        # format string that could ever have carried caller input.
        assert "{" not in template.kql, f"{name} KQL uses '{{' formatting"
        assert "%" not in template.kql, f"{name} KQL uses '%' formatting"


def test_every_template_declares_value_and_labels() -> None:
    """The metric adapter requires value_column + non-empty label_columns."""
    for name, template in sre_demo_capture_queries().items():
        assert template.value_column, f"{name}: value_column missing"
        assert "resource_id" in template.label_columns, (
            f"{name}: label_columns must include 'resource_id' "
            f"(shared label the adapter filters on)"
        )


def test_pod_restarts_computes_delta_not_cumulative() -> None:
    """PodRestartCount is a cumulative counter; the template MUST emit
    the in-window delta (max - min), not the raw max snapshot value."""
    template = sre_demo_capture_queries()[METRIC_POD_RESTARTS]
    assert "rc_max - rc_min" in template.kql, (
        "k8s.pod.restarts KQL must compute a max-min delta so the series "
        "reflects new restarts in the timespan, not the pod's lifetime "
        "cumulative restart count"
    )
    # max_(...) alone would be the buggy cumulative snapshot shape.
    assert "summarize v = max(" not in template.kql, (
        "k8s.pod.restarts KQL must not emit the raw cumulative counter"
    )


def test_pod_restarts_groups_by_pod_uid_not_name() -> None:
    """StatefulSet pods keep their Name across a delete/recreate; grouping
    by Name conflates the two incarnations' restart counters. The immutable
    PodUid MUST be the group key so a recreated pod does not steal the
    prior pod's counter and surface a spurious delta."""
    template = sre_demo_capture_queries()[METRIC_POD_RESTARTS]
    assert "PodUid" in template.kql, (
        "k8s.pod.restarts KQL must include PodUid in the group key so "
        "StatefulSet name reuse cannot produce a spurious delta"
    )
    assert "pod_uid" in template.label_columns
    # The regression: grouping by Name alone.
    assert "by resource_id = tolower(ClusterId), pod_uid" in template.kql


def test_rollout_stall_preserves_event_time() -> None:
    """The rollout-stall template MUST NOT overwrite TimeGenerated with
    now() - that would poison rolling-window anomaly detection with a
    fake "just now" timestamp for events that happened minutes ago."""
    template = sre_demo_capture_queries()[METRIC_ROLLOUT_STALL_SECONDS]
    assert "TimeGenerated = now()" not in template.kql, (
        "rollout-stall KQL must project the event's own time, not now()"
    )
    assert "TimeGenerated = first_at" in template.kql, (
        "rollout-stall KQL must anchor its TimeGenerated to the earliest "
        "observed stall event so downstream analyzers see the actual "
        "onset time"
    )


def test_rollout_stall_labels_involved_object_not_deployment() -> None:
    """KubeEvents.Name is the involved-object name (pod / RS / deployment
    depending on Reason), not always a Deployment - the label MUST reflect
    that so the analyzer does not mis-group per-pod rows as per-deployment."""
    template = sre_demo_capture_queries()[METRIC_ROLLOUT_STALL_SECONDS]
    assert "involved_object" in template.label_columns
    assert "deployment" not in template.label_columns


def test_every_label_column_is_lowercase_snake_case() -> None:
    """Labels flow into audit and log lines; enforce grep-friendly shape."""
    import re

    label_re = re.compile(r"^[a-z][a-z0-9_]*$")
    for name, template in sre_demo_capture_queries().items():
        for label in template.label_columns:
            assert label_re.match(label), (
                f"{name}: label {label!r} must be lowercase snake_case "
                f"(matches {label_re.pattern!r})"
            )


def test_catalog_view_is_read_only() -> None:
    catalog = sre_demo_capture_queries()
    try:
        catalog["injected"] = _catalog_sentinel()  # type: ignore[index]
    except TypeError:
        return
    raise AssertionError("sre_demo_capture_queries() must be read-only")


# ---------------------------------------------------------------------------
# Analyzer query catalog - every metric name that
# ``fdai.core.investigation.analyzers.default_analyzers`` requests MUST
# resolve to a KQL template. Without this coverage the analyzer path
# fails-closed with ``MetricProviderError`` for every reference analyzer.
# ---------------------------------------------------------------------------


_EXPECTED_ANALYZER = {
    METRIC_NODE_CPU_PERCENT,
    METRIC_POD_RESTART_COUNT,
    METRIC_ROLLOUT_STALL_DURATION_SECONDS,
    METRIC_HTTP_429_RATE,
    METRIC_REQUEST_SURGE_RATIO,
    METRIC_BACKEND_FIRST_BYTE_MS,
    METRIC_HEALTHY_HOST_COUNT,
    METRIC_MYSQL_CPU_PERCENT,
    METRIC_MYSQL_ACTIVE_CONNECTIONS,
    METRIC_APIM_HTTP_5XX_RATE,
    METRIC_APIM_BACKEND_LATENCY_MS,
}


def test_analyzer_catalog_contains_every_analyzer_metric() -> None:
    got = set(sre_demo_analyzer_queries().keys())
    assert got == _EXPECTED_ANALYZER, (
        f"extra={got - _EXPECTED_ANALYZER}, missing={_EXPECTED_ANALYZER - got}"
    )


def test_analyzer_catalog_covers_the_reference_analyzers() -> None:
    """Ground-truth coverage: every ``metric=`` value the reference
    analyzers pass to the metric provider MUST resolve to a KQL
    template. A future analyzer that adds a new metric will fail this
    test until the KQL template ships too - which is exactly the
    contract we want to enforce."""
    from fdai.core.investigation.analyzer import Threshold, ThresholdAnalyzer
    from fdai.core.investigation.analyzers import default_analyzers

    class _NullProvider:
        async def query(self, *args: object, **kwargs: object) -> None:
            return None

    seen: set[str] = set()
    for analyzer in default_analyzers(_NullProvider()):  # type: ignore[arg-type]
        assert isinstance(analyzer, ThresholdAnalyzer)
        for threshold in analyzer._thresholds:  # type: ignore[attr-defined]
            assert isinstance(threshold, Threshold)
            seen.add(threshold.metric)
    catalog = set(sre_demo_analyzer_queries().keys())
    missing = seen - catalog
    assert not missing, (
        f"analyzer metrics without a KQL template: {sorted(missing)} - "
        "add each one to sre_demo_analyzer_queries() before shipping"
    )


def test_analyzer_templates_are_metric_kql_templates() -> None:
    for template in sre_demo_analyzer_queries().values():
        assert isinstance(template, MetricKqlTemplate)


def test_analyzer_templates_carry_resource_id_label() -> None:
    for name, template in sre_demo_analyzer_queries().items():
        assert template.value_column, f"{name}: value_column missing"
        assert "resource_id" in template.label_columns, (
            f"{name}: label_columns must include 'resource_id'"
        )


def test_analyzer_templates_do_not_interpolate_input() -> None:
    """Same injection guard as the demo capture set."""
    for name, template in sre_demo_analyzer_queries().items():
        assert "{" not in template.kql, f"{name} KQL uses '{{' formatting"
        assert "%" not in template.kql, f"{name} KQL uses '%' formatting"


def test_default_metric_queries_is_the_union() -> None:
    """``wire_azure_container`` picks this map by default; it MUST be the
    exact union of the two sub-catalogs so every reference scenario -
    demo capture AND analyzer - resolves to a KQL template with no
    fork-only override required."""
    default_keys = set(default_metric_queries().keys())
    capture_keys = set(sre_demo_capture_queries().keys())
    analyzer_keys = set(sre_demo_analyzer_queries().keys())
    assert default_keys == capture_keys | analyzer_keys, (
        f"default_metric_queries missing: "
        f"{(capture_keys | analyzer_keys) - default_keys}, "
        f"extras: {default_keys - (capture_keys | analyzer_keys)}"
    )


def test_capture_and_analyzer_catalogs_have_disjoint_keys() -> None:
    """The two sub-maps address different scenarios (demo capture vs
    reference-analyzer scenarios); a name collision would mean two
    templates for the same metric, which is a defect."""
    overlap = set(sre_demo_capture_queries().keys()) & set(sre_demo_analyzer_queries().keys())
    assert not overlap, f"capture/analyzer name collision: {sorted(overlap)}"


def test_default_metric_queries_view_is_read_only() -> None:
    catalog = default_metric_queries()
    try:
        catalog["injected"] = _catalog_sentinel()  # type: ignore[index]
    except TypeError:
        return
    raise AssertionError("default_metric_queries() must be read-only")


def _catalog_sentinel() -> MetricKqlTemplate:
    return MetricKqlTemplate(
        kql="X | project TimeGenerated, v = 0.0, resource_id = 'r'",
        value_column="v",
        label_columns=("resource_id",),
    )
