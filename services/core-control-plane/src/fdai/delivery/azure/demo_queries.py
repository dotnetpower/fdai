"""Reference KQL query templates for the SRE demo five-metric capture.

The SRE demo pack (see
``docs/internals/sre-demo-scenarios-08-fdai-coverage.md`` C.5 and C.11)
captures **five metrics** at each incident so the coverage matrix and the
harness agree on what the demo asserts VALIDATED against:

- ``host.cpu.percent``            - VM guest-OS CPU (scenario S5).
- ``host.memory.available_pct``   - VM guest-OS free memory (scenario S6, C4).
- ``k8s.pod.restarts``            - AKS pod restart count (scenarios S1, C2).
- ``http.server.request.failure_rate`` - request failure rate (scenario S4).
- ``k8s.deployment.rollout_stall_seconds`` - stall seconds past the
  progress deadline (scenario S12).

Every template is **author-controlled configuration**, never derived from
untrusted input. Untrusted labels (``resource_id``, ``deployment``, ...)
stay out of the KQL body and are filtered in memory by
:class:`~fdai.delivery.azure.metric_logs.AzureMonitorLogsMetricProvider`
- this matches the metric adapter's KQL-injection contract.

These templates are the CSP-neutral **catalog** the metric adapter is
initialized with at the composition root. A fork MAY override a template
(different table, different KDL predicate) but MUST keep the returned
``value_column``, ``timestamp_column``, and ``label_columns`` shape.

Label case-normalization contract
---------------------------------

Every template lowercases the identifier columns it emits
(``resource_id = tolower(_ResourceId)``, ``resource_id = tolower(ClusterId)``).
The metric adapter's in-memory label filter is a **case-sensitive raw
string equality** (see :func:`fdai.shared.providers.metric._labels_match`),
so callers passing ``MetricQuery(labels={"resource_id": "..."})`` MUST
supply the ``resource_id`` value in lowercase to match. This is the same
contract Azure Resource Manager already uses (resource ids are
case-insensitive by convention; lowercase is canonical).

Semantic notes per template
---------------------------

- ``host.cpu.percent`` - avg guest-OS CPU % per 1-minute bin per
  resource. Requires the VM Insights extension.
- ``host.memory.available_pct`` - **available** memory %, so a **LOW**
  value means memory pressure. Wire this to
  :attr:`fdai.core.investigation.analyzer.Comparison.LTE` in the
  threshold analyzer; a ``GTE`` binding would alert on healthy hosts.
- ``k8s.pod.restarts`` - the **delta** of PodRestartCount within the
  timespan per pod (grouped by ``PodUid`` so a StatefulSet pod that
  keeps its ``Name`` across a recreation does not conflate the two
  incarnations' restart counters).
- ``http.server.request.failure_rate`` - failed / total AppRequests per
  1-minute bin per resource.
- ``k8s.deployment.rollout_stall_seconds`` - the **observed span** of
  stall-signal KubeEvents in the timespan
  (``max(TimeGenerated) - min(TimeGenerated)``), NOT the total time the
  rollout has been stuck. If the stall started before the query
  timespan, ``v`` is a **lower bound** of the true stall duration - a
  fork tuning a threshold around this metric should account for that.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

from fdai.delivery.azure.metric_logs import MetricKqlTemplate

# CSP-neutral metric names shared with the analyzer / detector layer.
METRIC_HOST_CPU_PERCENT = "host.cpu.percent"
METRIC_HOST_MEMORY_AVAILABLE_PCT = "host.memory.available_pct"
METRIC_POD_RESTARTS = "k8s.pod.restarts"
METRIC_REQUEST_FAILURE_RATE = "http.server.request.failure_rate"
METRIC_ROLLOUT_STALL_SECONDS = "k8s.deployment.rollout_stall_seconds"


_HOST_CPU_PERCENT = MetricKqlTemplate(
    kql=(
        "InsightsMetrics "
        "| where Namespace == 'Processor' and Name == 'UtilizationPercentage' "
        "| summarize v = avg(Val) by "
        "  bin(TimeGenerated, 1m), resource_id = tolower(_ResourceId)"
    ),
    value_column="v",
    label_columns=("resource_id",),
)

_HOST_MEMORY_AVAILABLE_PCT = MetricKqlTemplate(
    kql=(
        "InsightsMetrics "
        "| where Namespace == 'Memory' and Name == 'AvailableMemoryPercentage' "
        "| summarize v = avg(Val) by "
        "  bin(TimeGenerated, 1m), resource_id = tolower(_ResourceId)"
    ),
    value_column="v",
    label_columns=("resource_id",),
)

_POD_RESTARTS = MetricKqlTemplate(
    # PodRestartCount is a cumulative counter per pod. Grouping by
    # ``PodUid`` (the immutable object UID) rather than ``Name`` defends
    # against StatefulSet pods that keep their name across a
    # delete/recreate - two different incarnations would otherwise share
    # a group and the delta 'max - min' would surface as a spurious
    # restart (e.g. old pod at rc=3 + new pod at rc=0 -> min=0, max=3,
    # v=3, "3 restarts" when the true answer is zero). The label set
    # still exposes pod / namespace for the operator.
    kql=(
        "KubePodInventory "
        "| where isnotempty(PodRestartCount) and isnotempty(PodUid) "
        "| extend rc = toint(PodRestartCount) "
        "| summarize "
        "    rc_max = max(rc), rc_min = min(rc), "
        "    at = max(TimeGenerated), "
        "    pod = any(Name), namespace = any(Namespace) "
        "  by resource_id = tolower(ClusterId), pod_uid = tostring(PodUid) "
        "| extend v = todouble(rc_max - rc_min) "
        "| project TimeGenerated = at, v, resource_id, pod, namespace, pod_uid"
    ),
    value_column="v",
    label_columns=("resource_id", "pod", "namespace", "pod_uid"),
)

_REQUEST_FAILURE_RATE = MetricKqlTemplate(
    kql=(
        "AppRequests "
        "| summarize "
        "  failures = countif(Success == false), total = count() "
        "  by bin(TimeGenerated, 1m), resource_id = tolower(_ResourceId) "
        "| extend v = iif(total == 0, 0.0, todouble(failures) / total) "
        "| project TimeGenerated, v, resource_id"
    ),
    value_column="v",
    label_columns=("resource_id",),
)

_ROLLOUT_STALL_SECONDS = MetricKqlTemplate(
    # Emits one row per (cluster, involved object) with:
    #   - TimeGenerated = the earliest stall-signal event's own time
    #     (NOT now() - that would poison rolling-window anomaly
    #     detection with a fake "just now" timestamp),
    #   - v = seconds elapsed from that earliest event to the max event
    #     observed in the timespan (i.e. the *observed span* of the
    #     stall in this query window). See module docstring - this is a
    #     LOWER BOUND on the true stall duration, not the exact age.
    # The involved-object name is a pod / replica-set / deployment
    # depending on which event fired, so the label is ``involved_object``.
    kql=(
        "KubeEvents "
        "| where Reason in ('FailedCreate','ProgressDeadlineExceeded',"
        "'ImagePullBackOff','ErrImagePull') "
        "| summarize "
        "    first_at = min(TimeGenerated), last_at = max(TimeGenerated) "
        "  by resource_id = tolower(ClusterId), involved_object = Name "
        "| extend v = todouble(datetime_diff('second', last_at, first_at)) "
        "| project TimeGenerated = first_at, v, resource_id, involved_object"
    ),
    value_column="v",
    label_columns=("resource_id", "involved_object"),
)


_DEMO_CAPTURE: Mapping[str, MetricKqlTemplate] = MappingProxyType(
    {
        METRIC_HOST_CPU_PERCENT: _HOST_CPU_PERCENT,
        METRIC_HOST_MEMORY_AVAILABLE_PCT: _HOST_MEMORY_AVAILABLE_PCT,
        METRIC_POD_RESTARTS: _POD_RESTARTS,
        METRIC_REQUEST_FAILURE_RATE: _REQUEST_FAILURE_RATE,
        METRIC_ROLLOUT_STALL_SECONDS: _ROLLOUT_STALL_SECONDS,
    }
)


def sre_demo_capture_queries() -> Mapping[str, MetricKqlTemplate]:
    """Return the five-metric-capture template map for a demo baseline.

    A fork wires this into
    :class:`~fdai.delivery.azure.metric_logs.AzureMonitorLogsConfig` at the
    composition root::

        AzureMonitorLogsConfig(
            workspace_id=...,
            queries=sre_demo_capture_queries(),
        )

    The returned mapping is a read-only view; a fork that needs to add or
    override templates copies into its own dict first.
    """
    return _DEMO_CAPTURE


# --------------------------------------------------------------------------
# Analyzer query templates - one per metric name requested by
# ``fdai.core.investigation.analyzers.default_analyzers``. These fill the
# gap between the five-metric SRE demo capture set above (OTel-shaped
# names) and the CSP-neutral snake_case names the reference analyzers
# actually pass to the metric provider. Without them the analyzer path
# would fail-closed with :class:`MetricProviderError` for every default
# analyzer because none of the metric names above collide with them.
#
# Every template assumes the resource's diagnostic settings route the
# metric or log into the shared Log Analytics workspace - the standard
# Azure "AllMetrics" -> ``AzureMetrics`` fan-out, or Container Insights
# for AKS, plus resource-specific log tables (``AzureDiagnostics``,
# ``ApiManagementGatewayLogs``). A fork whose deploy differs (different
# diagnostic setting, different table) MUST override the template.
# --------------------------------------------------------------------------

# CSP-neutral metric names shared with the analyzer layer. These MUST
# match the ``metric=`` values in
# ``fdai.core.investigation.analyzers`` exactly - the metric adapter
# fails-closed on a lookup miss, so a rename here without a matching
# analyzer edit is a defect.
METRIC_NODE_CPU_PERCENT = "node_cpu_percent"
METRIC_POD_RESTART_COUNT = "pod_restart_count"
METRIC_ROLLOUT_STALL_DURATION_SECONDS = "rollout_stall_duration_seconds"
METRIC_HTTP_429_RATE = "http_429_rate"
METRIC_REQUEST_SURGE_RATIO = "request_surge_ratio"
METRIC_BACKEND_FIRST_BYTE_MS = "backend_first_byte_response_time_ms"
METRIC_HEALTHY_HOST_COUNT = "healthy_host_count"
METRIC_MYSQL_CPU_PERCENT = "cpu_percent"
METRIC_MYSQL_ACTIVE_CONNECTIONS = "active_connections"
METRIC_APIM_HTTP_5XX_RATE = "http_5xx_rate"
METRIC_APIM_BACKEND_LATENCY_MS = "backend_latency_ms"


_NODE_CPU_PERCENT = MetricKqlTemplate(
    # AKS node CPU % via Container Insights' ``InsightsMetrics`` table
    # (``container.azm.ms/nodes`` namespace). Emits one row per (cluster,
    # node) with a 1-minute average utilization; the analyzer's
    # ``GTE 80.0`` threshold fires on any node above the bound.
    #
    # ``resource_id`` is the cluster ARM id (lowercased for the
    # case-sensitive in-memory label filter); ``node`` is the offending
    # node name so the RCA layer can drill down without a second query.
    kql=(
        "InsightsMetrics "
        "| where Namespace == 'container.azm.ms/nodes' "
        "and Name == 'cpuUsagePercentage' "
        "| extend node = tostring(parse_json(Tags).['host.name']) "
        "| summarize v = avg(Val) by "
        "  bin(TimeGenerated, 1m), "
        "  resource_id = tolower(_ResourceId), "
        "  node = coalesce(node, 'unknown')"
    ),
    value_column="v",
    label_columns=("resource_id", "node"),
)

_HTTP_429_RATE = MetricKqlTemplate(
    # Azure OpenAI 429 (rate-limit) rate = 429 responses / total, per
    # minute per resource. Reads AOAI's diagnostic logs routed to the
    # workspace (``RequestResponse`` category). Empty totals map to a
    # zero rate rather than a division error, so a quiet endpoint never
    # emits a spurious anomaly.
    kql=(
        "AzureDiagnostics "
        "| where ResourceProvider == 'MICROSOFT.COGNITIVESERVICES' "
        "| where Category == 'RequestResponse' "
        "| extend status_code = toint(coalesce("
        "    tostring(column_ifexists('ResultStatusCode', '')), "
        "    tostring(column_ifexists('httpStatusCode_d', real(null))), "
        "    tostring(column_ifexists('httpStatus_d', real(null))), "
        "    column_ifexists('status_s', ''), "
        "    column_ifexists('code_s', ''))) "
        "| summarize "
        "    total = count(), "
        "    throttled = countif(status_code == 429) "
        "  by bin(TimeGenerated, 1m), resource_id = tolower(ResourceId) "
        "| extend v = iif(total == 0, 0.0, todouble(throttled) / total) "
        "| project TimeGenerated, v, resource_id"
    ),
    value_column="v",
    label_columns=("resource_id",),
)

_REQUEST_SURGE_RATIO = MetricKqlTemplate(
    # Azure OpenAI request-volume surge = current-minute count / baseline
    # (mean count of the preceding 15 minutes). The analyzer's
    # ``GTE 10.0`` threshold matches "traffic 10x baseline". A cold-start
    # window (no baseline) collapses to a ratio of 1.0 so a fresh
    # deployment does not fire the anomaly.
    kql=(
        "AzureDiagnostics "
        "| where ResourceProvider == 'MICROSOFT.COGNITIVESERVICES' "
        "| where Category == 'RequestResponse' "
        "| summarize per_min = count() "
        "  by bin(TimeGenerated, 1m), resource_id = tolower(ResourceId) "
        "| order by resource_id asc, TimeGenerated asc "
        "| extend baseline = "
        "    todouble(prev(per_min, 1)) "
        "    + todouble(prev(per_min, 2)) "
        "    + todouble(prev(per_min, 3)) "
        "    + todouble(prev(per_min, 4)) "
        "    + todouble(prev(per_min, 5)) "
        "| extend baseline = iif(baseline <= 0, 5.0, baseline / 5.0) "
        "| extend v = todouble(per_min) / baseline "
        "| project TimeGenerated, v, resource_id"
    ),
    value_column="v",
    label_columns=("resource_id",),
)

_BACKEND_FIRST_BYTE_MS = MetricKqlTemplate(
    # Application Gateway backend first-byte response time. AGW's
    # ``AzureDiagnostics`` (``ApplicationGatewayAccessLog`` category)
    # exposes ``timeTaken_d`` per request; averaging per minute yields a
    # bounded series the analyzer's ``GTE 2000.0 ms`` threshold reads.
    kql=(
        "AzureDiagnostics "
        "| where ResourceType == 'APPLICATIONGATEWAYS' "
        "| where Category == 'ApplicationGatewayAccessLog' "
        "| summarize v = avg(timeTaken_d * 1000.0) "
        "  by bin(TimeGenerated, 1m), resource_id = tolower(ResourceId) "
        "| project TimeGenerated, v, resource_id"
    ),
    value_column="v",
    label_columns=("resource_id",),
)

_HEALTHY_HOST_COUNT = MetricKqlTemplate(
    # Application Gateway backend healthy-host count via ``AzureMetrics``
    # (requires the AGW diagnostic setting's ``AllMetrics`` toggle). Min
    # aggregation matches the analyzer's ``LTE 1.0`` critical bound:
    # even a brief dip below 1 host is worth surfacing.
    kql=(
        "AzureMetrics "
        "| where ResourceProvider == 'MICROSOFT.NETWORK' "
        "and Resource contains 'APPLICATIONGATEWAYS' "
        "| where MetricName == 'HealthyHostCount' "
        "| summarize v = min(Minimum) "
        "  by bin(TimeGenerated, 1m), resource_id = tolower(ResourceId) "
        "| project TimeGenerated, v, resource_id"
    ),
    value_column="v",
    label_columns=("resource_id",),
)

_MYSQL_CPU_PERCENT = MetricKqlTemplate(
    # MySQL Flexible Server CPU % from ``AzureMetrics``. Standard 1-min
    # granularity is more than enough for the ``GTE 90.0`` saturation
    # threshold the analyzer sets for slow-query investigation.
    kql=(
        "AzureMetrics "
        "| where ResourceProvider == 'MICROSOFT.DBFORMYSQL' "
        "| where MetricName == 'cpu_percent' "
        "| summarize v = avg(Average) "
        "  by bin(TimeGenerated, 1m), resource_id = tolower(ResourceId) "
        "| project TimeGenerated, v, resource_id"
    ),
    value_column="v",
    label_columns=("resource_id",),
)

_MYSQL_ACTIVE_CONNECTIONS = MetricKqlTemplate(
    kql=(
        "AzureMetrics "
        "| where ResourceProvider == 'MICROSOFT.DBFORMYSQL' "
        "| where MetricName == 'active_connections' "
        "| summarize v = max(Maximum) "
        "  by bin(TimeGenerated, 1m), resource_id = tolower(ResourceId) "
        "| project TimeGenerated, v, resource_id"
    ),
    value_column="v",
    label_columns=("resource_id",),
)

_APIM_HTTP_5XX_RATE = MetricKqlTemplate(
    # API Management 5xx rate from ``ApiManagementGatewayLogs``. Failed /
    # total per minute per resource; zero-total minutes yield 0.0 rather
    # than a division error. Matches the analyzer's ``GTE 0.05`` bound.
    kql=(
        "ApiManagementGatewayLogs "
        "| summarize "
        "    total = count(), "
        "    fivexx = countif(toint(ResponseCode) >= 500) "
        "  by bin(TimeGenerated, 1m), resource_id = tolower(_ResourceId) "
        "| extend v = iif(total == 0, 0.0, todouble(fivexx) / total) "
        "| project TimeGenerated, v, resource_id"
    ),
    value_column="v",
    label_columns=("resource_id",),
)

_APIM_BACKEND_LATENCY_MS = MetricKqlTemplate(
    # API Management backend response time (ms) from
    # ``ApiManagementGatewayLogs``. Averaging per minute per resource
    # gives a stable series for the ``GTE 1000.0`` threshold.
    kql=(
        "ApiManagementGatewayLogs "
        "| where isnotempty(BackendTime) "
        "| summarize v = avg(todouble(BackendTime)) "
        "  by bin(TimeGenerated, 1m), resource_id = tolower(_ResourceId) "
        "| project TimeGenerated, v, resource_id"
    ),
    value_column="v",
    label_columns=("resource_id",),
)


_ANALYZER_QUERIES: Mapping[str, MetricKqlTemplate] = MappingProxyType(
    {
        METRIC_NODE_CPU_PERCENT: _NODE_CPU_PERCENT,
        METRIC_POD_RESTART_COUNT: _POD_RESTARTS,
        METRIC_ROLLOUT_STALL_DURATION_SECONDS: _ROLLOUT_STALL_SECONDS,
        METRIC_HTTP_429_RATE: _HTTP_429_RATE,
        METRIC_REQUEST_SURGE_RATIO: _REQUEST_SURGE_RATIO,
        METRIC_BACKEND_FIRST_BYTE_MS: _BACKEND_FIRST_BYTE_MS,
        METRIC_HEALTHY_HOST_COUNT: _HEALTHY_HOST_COUNT,
        METRIC_MYSQL_CPU_PERCENT: _MYSQL_CPU_PERCENT,
        METRIC_MYSQL_ACTIVE_CONNECTIONS: _MYSQL_ACTIVE_CONNECTIONS,
        METRIC_APIM_HTTP_5XX_RATE: _APIM_HTTP_5XX_RATE,
        METRIC_APIM_BACKEND_LATENCY_MS: _APIM_BACKEND_LATENCY_MS,
    }
)


def sre_demo_analyzer_queries() -> Mapping[str, MetricKqlTemplate]:
    """Return the KQL templates for every metric requested by
    :func:`fdai.core.investigation.analyzers.default_analyzers`.

    Keyed by the exact snake_case metric names the analyzers pass to
    :class:`~fdai.shared.providers.metric.MetricProvider`, so binding
    this map into
    :class:`~fdai.delivery.azure.metric_logs.AzureMonitorLogsConfig`
    lights up the App Gateway / MySQL / Azure OpenAI / AKS / APIM
    threshold analyzers end-to-end. A fork's diagnostic layout differs
    from the assumed ``AzureMetrics`` / ``AzureDiagnostics`` /
    ``ApiManagementGatewayLogs`` / Container Insights schema? Copy the
    map, override the templates whose tables differ, and pass the
    result via ``AzureWireOverrides.monitor_queries``.
    """
    return _ANALYZER_QUERIES


def default_metric_queries() -> Mapping[str, MetricKqlTemplate]:
    """Union of :func:`sre_demo_capture_queries` +
    :func:`sre_demo_analyzer_queries`.

    This is the map ``wire_azure_container`` picks when a fork does not
    supply ``AzureWireOverrides.monitor_queries``, so **every** shipped
    detection scenario resolves to a KQL template out of the box - the
    five-metric SRE demo capture set AND the nine analyzer-referenced
    metrics. The two sub-maps have disjoint keys (OTel dotted names vs
    snake_case), so the union is unambiguous; a metric shipped in both
    would be a defect and MUST be reconciled here.
    """
    merged: dict[str, MetricKqlTemplate] = {}
    for key, template in _DEMO_CAPTURE.items():
        merged[key] = template
    for key, template in _ANALYZER_QUERIES.items():
        if key in merged:  # pragma: no cover - defended by
            # ``services/core-control-plane/tests/delivery/azure/test_demo_queries.py``.
            raise RuntimeError(
                f"metric name {key!r} collides between the demo capture "
                "and analyzer maps - reconcile the two before shipping"
            )
        merged[key] = template
    return MappingProxyType(merged)


__all__ = [
    "METRIC_APIM_BACKEND_LATENCY_MS",
    "METRIC_APIM_HTTP_5XX_RATE",
    "METRIC_BACKEND_FIRST_BYTE_MS",
    "METRIC_HEALTHY_HOST_COUNT",
    "METRIC_HOST_CPU_PERCENT",
    "METRIC_HOST_MEMORY_AVAILABLE_PCT",
    "METRIC_HTTP_429_RATE",
    "METRIC_MYSQL_ACTIVE_CONNECTIONS",
    "METRIC_MYSQL_CPU_PERCENT",
    "METRIC_NODE_CPU_PERCENT",
    "METRIC_POD_RESTART_COUNT",
    "METRIC_POD_RESTARTS",
    "METRIC_REQUEST_FAILURE_RATE",
    "METRIC_REQUEST_SURGE_RATIO",
    "METRIC_ROLLOUT_STALL_SECONDS",
    "METRIC_ROLLOUT_STALL_DURATION_SECONDS",
    "default_metric_queries",
    "sre_demo_analyzer_queries",
    "sre_demo_capture_queries",
]
