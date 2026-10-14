---
title: Azure GPU monitoring technical test
description: Offline evidence and an integration plan for GPU monitoring through FDAI.
---

## Scope and result

FDAI can consume GPU observations as governed Events, investigate findings and propose
recovery through its existing control loop. This evaluation validates the metric-to-Event
and local report boundary, not a deployed agent system.

> [!IMPORTANT]
> All observations are synthetic. No Azure resources, Datadog API, model, production
> event topic, notification channel or executor was invoked. Do not publish this replay
> data to a deployed FDAI installation. `external_effect_verified` is always `false`.

The baseline is upstream commit `f8a4208ef`, checked out on `gpu-monitoring`.
The 54-case replay covers A10, T4 and H100 labels, two source mappings and nine scenarios:
six healthy cases and 48 finding cases. The later synthetic observations clear the
monitored conditions in those 48 cases; no actual remediation or hardware recovery is proven.
The owning suite has 53 passing tests. These are software contract tests, not physical
certification of any GPU model.

## Repository structure and existing integration seams

| Location | Responsibility relevant to this test |
|----------|-------------------------------------|
| `services/core-control-plane/src/fdai/` | Governed control loop, detection, trust routing, risk gate, agents and delivery adapters |
| `services/operator-service/` | Authenticated operator API; not executor authority |
| `services/isolated-executor/` | Separated privileged execution service |
| `services/document-ingestion-api/`, `services/document-processing-worker/` | Document evidence processing |
| `services/system-knowledge-service/` | Independently packaged knowledge-service candidate |
| `packages/service-contracts/` | Shared cross-service contracts |
| `rule-catalog/`, `policies/` | Governed rules, workflows, ActionTypes and policy |
| `console/`, `cli/` | Operator interfaces |
| `infra/` | Local and Azure deployment infrastructure |
| `eval/gpu_monitoring/` | This offline evaluation only; no production composition binding |

Existing GPU signal vocabulary lives in
[signals.py](../../services/core-control-plane/src/fdai/core/detection/signals.py).
GPU chaos scenario files already exist under
[the collected GPU scenarios](../../rule-catalog/chaos-scenarios/collected/gpu/);
their existence does not prove a live detector or GPU monitoring integration.

The Azure push boundary already provides
[common-alert and diagnostic normalization](../../services/core-control-plane/src/fdai/delivery/azure/monitor_events.py)
and [the diagnostic stream bridge](../../services/core-control-plane/src/fdai/delivery/azure/diagnostic_event_ingest.py).
GPU guest metrics are not automatically available from VM platform `AllMetrics`.
An exporter or GPU-capable agent must collect them.

## Recommended architecture

Start with the observability platform already operated by the team. Azure Monitor is a
natural default for an Azure-only deployment; Datadog is appropriate when it already owns
on-call monitoring. Normalize both into the same logical GPU observation contract rather
than building two independent remediation paths.

```text
GPU VM / AKS GPU node
  -> DCGM exporter + Azure managed Prometheus OR Datadog GPU Monitoring
  -> scoped metric window + workload metrics + driver logs + change history
  -> Huginn: normalize and deduplicate Event
  -> Heimdall: grounded findings and independent effect observations
  -> Forseti: deterministic-first routing, quality/risk gates
  -> notification/report OR Var approval -> Thor execution
  -> effect verification / Vidar rollback -> Saga audit -> post-action report
```

This is an integration design, not the execution trace of the replay. No new pantheon
agent is needed. Agent cooperation stays on governed event-bus contracts. Bragi can render
the explanation but cannot diagnose authoritatively or authorize remediation.

### Azure Monitor path

* On AKS, use NVIDIA DCGM Exporter and Azure Monitor managed Prometheus. Reuse an existing
  GPU Operator exporter rather than installing a second one. The managed GPU node-pool
  variant is documented as preview; assess production support before choosing it.
* On GPU VMs, install a supported NVIDIA driver and a guest GPU collector. Choose and
  validate the supported Prometheus/remote-write or Azure Monitor Logs ingestion path
  for that environment. AKS `PodMonitor` instructions do not apply to standalone VMs.
* Preserve logical resource, node, GPU UUID and, when relevant, MIG instance identities.
  Do not aggregate different GPUs before diagnosis. MIG/driver/DCGM support can change
  metric availability; an unsupported metric is not zero.
* Prometheus alerts need their own documented integration. Do not assume they use the
  existing Azure Monitor Common Alert Schema normalizer without checking the actual
  notification payload. Where Common Alert Schema is used, reuse that normalizer.
* Authorize ingress, restrict targets and re-fetch a bounded metric window. An incoming
  alert is a trigger, not trustworthy root-cause evidence or an execution request.

### Datadog path

* Prefer current Datadog GPU Monitoring for new installations. It does not require DCGM.
  The older DCGM integration is now documented as legacy.
* At documentation review time, the native product required Linux, kernel 5.8+, NVIDIA
  driver 450.51+ and Agent 7.80+. The setup page warns against Agent 7.82.0. Verify
  current requirements and site availability before installation.
* Enable the Azure integration for cloud identity/cost context and collect workload
  queue, latency and process information for diagnosis.
* Confirm the installed integration's metric names, dimensions and units. The
  `example.gpu.*` names in this replay are synthetic aliases, not real Datadog metric names.
* A secured webhook/API adapter, alert deduplication, resolved-event handling and the
  deployed FDAI composition binding remain implementation work.

## Metric and decision rules

The default policy is illustrative: five-minute windows, maximum 60-second sample gaps,
120-second freshness, utilization 95%, memory pressure 95%, temperature 85 C and allocated
idle utilization at most 5%. Tune them by GPU/driver, workload SLO and business schedule.

| Evidence | Local finding | Interpretation and safe next step |
|----------|---------------|-----------------------------------|
| Sustained utilization >=95% and rising queue depth | `gpu_util_saturated` | Capacity-pressure hypothesis; check latency SLO/quota before a scaling proposal |
| Memory used / capacity >=95% | `alert_trigger`, memory pressure | Advisory, not OOM or a proven memory leak |
| Workload CUDA OOM counter increases | `gpu_vram_oom` | Observed OOM; investigate allocations, batch size and KV cache |
| Temperature >=85 C without throttle evidence | `alert_trigger`, high temperature | Advisory, not proof of thermal throttling |
| Explicit thermal-throttle observation | `gpu_temp_throttle` | Investigate clocks, power and host health |
| XID code changes from a known prior value to nonzero | `gpu_xid_event` | A newly observed code transition; corroborate driver logs |
| Uncorrectable ECC counter increases | `gpu_ecc_uncorrectable` | Hardware investigation; never drain/reset directly from the metric |
| Allocated GPU remains <=5% busy for the complete window | `gpu_util_zero_wasted` | Idle advisory; investigate schedules, CPU/storage/network bottlenecks |
| Empty, stale, sparse or incomplete baseline data | `insufficient_evidence` | No clean-health claim |

Direct fresh XID/ECC/OOM/throttle evidence can emit a finding before a five-minute
utilization window exists. The report retains the coverage gap. Historical sticky XID
codes and unchanged cumulative counters are not treated as new errors; this replay does
not implement timestamped driver-log event ingestion or persistent edge state.

CPU utilization, data-loader throughput, disk/network latency, inference p99, workload
queue, restart/OOM logs, driver version and recent deployment changes are required for
meaningful causal investigation. GPU telemetry alone yields hypotheses, not root causes.

## What the implementation validates

| File | Responsibility |
|------|----------------|
| [models.py](models.py) | Strict sample validation, neutral logical identity and bounded policy |
| [providers.py](providers.py) | Already aligned metric snapshots; percent, MiB and Celsius units |
| [pipeline.py](pipeline.py) | Window detection, evidence/policy digests and replay-stable FDAI Events |
| [reporting.py](reporting.py) | Alert-shaped advisory report and later-observation comparison |
| [demo.py](demo.py) | 54 synthetic scenarios and JSON evidence output |
| [tests/test_pipeline.py](tests/test_pipeline.py) | Threshold, input, replay, publication and follow-up checks |

The normalizer is not a raw Prometheus query-response parser or a Datadog webhook parser.
It accepts points already aligned by time, GPU and logical resource, with confirmed units.
Counter gauges may be integral numbers; booleans, fractional codes, non-finite values and
DCGM unsupported sentinels are rejected.

Events reuse FDAI's existing `Event` model and JSON Schema. New observations are always
`mode=shadow`, with no tier or execution decision assigned. Publication tests use a local
recording publisher through the publish-only EventBus-compatible seam, not Kafka/Event Hubs
or a running agent. Replay keys include identity, evidence and policy. Durable deduplication,
restarts, incident lifecycle and cross-provider duplicate suppression are not implemented.

Follow-up verification requires a fresh, complete, non-overlapping later window for the
same GPU/source identity and availability of the original finding's telemetry.
`recovered_in_replay` means only that the monitored replay conditions cleared.

## Running and verification

From the repository root, use Python 3.12+ and the repository's normal locked development
environment. No dependencies or lockfiles were changed by this evaluation.

```powershell
uv sync --frozen --extra dev
$env:PYTHONPATH = '.;services\core-control-plane\src;packages\service-contracts\src'
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = '1'
uv run --no-sync python -m pytest -c eval\gpu_monitoring\pytest.ini -q
uv run --no-sync python -m eval.gpu_monitoring.demo --output gpu-monitoring-results.json
```

Keep result files in an ignored local/session directory rather than committing live data.
The replay JSON contains observations, hypotheses, recommendations, digests, execution
status, required safety gates and follow-up reports.

Local evidence for this task:

* 53 owning tests passed and the 54-case demonstration executed.
* Strict mypy passed for the five implementation modules.
* Python 3.12.4, pytest 9.1.1, Pydantic 2.12.5 and jsonschema 4.26.0 were reused from the
  existing environment; mypy was 1.10.0.
* Full lockfile restoration was blocked by TLS handshake failures at
  `files.pythonhosted.org`. System certificates did not resolve it. Ruff could not be
  restored from the local cache. These checks are not pinned-lockfile CI parity.
* No whole-repository suite, GPU hardware test, Azure deployment or live notification was run.

## Production acceptance gates

1. Select an exact development subscription/resource scope and disposable VM/AKS workload.
   Confirm GPU SKU/driver/collector support, identity mapping, access and data residency.
2. Bind the collector and secured ingress adapter. Verify named metric units, labels,
   missing-series behavior, counter resets, collection lag and duplicate/recovery messages.
3. Register detectors/rules and accountable agent bindings in shadow mode. Verify actual
   EventBus delivery, incident lifecycle, correlation, audit and report notification.
4. Run controlled saturation, VRAM pressure and idle workloads. Use replay or approved
   simulation for destructive GPU faults. Measure detection latency and false positives
   against a baseline instead of inferring them from these synthetic tests.
5. For ambiguous RCA, bind scoped logs/topology/change evidence and governed T2 verification.
   Do not issue a live model call without explicit authorization and a data-transfer review.
6. Add only reviewed ActionTypes. Scaling, concurrency changes, restart/drain or resizing
   require current human authorization or valid standing authority, promotion, risk checks,
   stop conditions, tested rollback, bounded blast radius, dry-run, target lock, idempotency
   and two-phase audit. GPU reset, arbitrary shell commands and deletion are not implemented.
7. Verify effects independently after the change. Roll back or escalate failed/unknown
   outcomes. Deliver the notification and post-action report through FDAI's separately
   configured channel contracts, not directly from the detector.

## References

* [Azure DCGM integration](https://learn.microsoft.com/azure/azure-monitor/containers/prometheus-dcgm-integration)
* [AKS GPU monitoring](https://learn.microsoft.com/azure/aks/monitor-gpu-metrics)
* [GPU metrics and workload correlation](https://learn.microsoft.com/azure/aks/best-practices-ml-ops#monitor-gpu-utilization-and-training-throughput)
* [Datadog GPU Monitoring](https://docs.datadoghq.com/gpu_monitoring/)
* [Datadog setup and requirements](https://docs.datadoghq.com/gpu_monitoring/setup/)
* [Legacy Datadog DCGM integration](https://docs.datadoghq.com/integrations/dcgm/)
* [FDAI observability design](../../docs/roadmap/rules-and-detection/observability-and-detection.md)
* [FDAI notification contracts](../../docs/roadmap/interfaces/channels-and-notifications.md)
* [Korean technical-test guide](README-ko.md)
