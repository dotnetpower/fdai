import { MetricSeriesChart } from "../components/charts";
import { StatusPill, type PillKind } from "../components/ui";
import type { ConsoleDataMode } from "../console-data-mode";
import { formatConsoleTimestamp } from "../time-format";
import type {
  GpuActionEvidence,
  GpuDeviceView,
  GpuEvidenceState,
  GpuFinding,
  GpuObservation,
} from "./gpu-monitoring.model";
import { gpuMonitoringText } from "./i18n/gpu-monitoring";

export function GpuInventory({
  devices,
  selectedKey,
  onSelect,
}: {
  readonly devices: readonly GpuDeviceView[];
  readonly selectedKey: string;
  readonly onSelect: (key: string) => void;
}) {
  return (
    <aside
      id="gpu-inventory"
      class="gpu-monitoring-inventory"
      aria-label={gpuMonitoringText("inventory.label")}
    >
      <SectionHeader
        heading={gpuMonitoringText("inventory.title")}
        description={gpuMonitoringText("inventory.description")}
      />
      <div class="gpu-device-list">
        {devices.map((device) => (
          <button
            key={device.key}
            type="button"
            class="gpu-device-button"
            aria-current={device.key === selectedKey ? "true" : undefined}
            onClick={() => onSelect(device.key)}
          >
            <strong>{device.model}</strong>
            <span>{device.gpuId}</span>
            <span>{evidenceLabel(device.evidenceState)}</span>
          </button>
        ))}
      </div>
    </aside>
  );
}

export function GpuSelectedHeader({
  device,
  dataMode,
}: {
  readonly device: GpuDeviceView;
  readonly dataMode: ConsoleDataMode;
}) {
  return (
    <header class="gpu-selected-head">
      <div>
        <h3>{device.model}</h3>
        <p>{device.resourceRef}</p>
      </div>
      <div>
        <StatusPill
          kind={evidenceTone(device.evidenceState)}
          label={evidenceLabel(device.evidenceState)}
        />
        <p class="muted small">
          {dataMode === "sample"
            ? gpuMonitoringText("evidence.sampleAge")
            : gpuMonitoringText("evidence.age", { seconds: device.ageSeconds ?? 0 })}
        </p>
      </div>
    </header>
  );
}

export function GpuCharts({ device }: { readonly device: GpuDeviceView }) {
  const loadData = device.history.map((observation) => ({
    label: timeLabel(observation.observedAt),
    values: [observation.utilizationPct, memoryPercent(observation)],
    detail: formatConsoleTimestamp(observation.observedAt, observation.observedAt),
  }));
  const temperatureData = device.history.map((observation) => ({
    label: timeLabel(observation.observedAt),
    values: [observation.temperatureC],
    detail: formatConsoleTimestamp(observation.observedAt, observation.observedAt),
  }));
  const powerData = device.history.flatMap((observation) =>
    observation.powerW === null
      ? []
      : [{
        label: timeLabel(observation.observedAt),
        values: [observation.powerW],
        detail: formatConsoleTimestamp(observation.observedAt, observation.observedAt),
      }]
  );
  const latestPower = device.latest?.powerW ?? null;
  return (
    <section
      id="gpu-load"
      class="gpu-chart-grid"
      aria-label={gpuMonitoringText("charts.load")}
    >
      <MetricSeriesChart
        label={gpuMonitoringText("charts.load")}
        value={formatPercent(device.latest?.utilizationPct ?? 0)}
        detail={gpuMonitoringText("charts.loadDescription")}
        data={loadData}
        series={[
          { label: gpuMonitoringText("charts.utilization"), color: "blue", kind: "line" },
          { label: gpuMonitoringText("charts.memory"), color: "amber", kind: "area" },
        ]}
        formatValue={formatPercent}
        minValue={0}
        maxValue={100}
        showYAxis
        startEndOnly
        className="gpu-chart-wide"
      />
      <MetricSeriesChart
        label={gpuMonitoringText("charts.temperature")}
        value={formatTemperature(device.latest?.temperatureC ?? 0)}
        detail={gpuMonitoringText("charts.temperatureDescription")}
        data={temperatureData}
        series={[
          { label: gpuMonitoringText("charts.temperature"), color: "emerald", kind: "line" },
        ]}
        formatValue={formatTemperature}
        minValue={0}
        maxValue={100}
        showYAxis
        startEndOnly
      />
      <MetricSeriesChart
        label={gpuMonitoringText("charts.power")}
        value={latestPower === null ? "-" : `${latestPower.toFixed(1)} W`}
        detail={gpuMonitoringText("charts.powerDescription")}
        data={powerData}
        series={[
          { label: gpuMonitoringText("charts.power"), color: "violet", kind: "line" },
        ]}
        formatValue={(value) => `${value.toFixed(0)} W`}
        minValue={0}
        showYAxis
        startEndOnly
      />
    </section>
  );
}

export function GpuMetrics({ observation }: { readonly observation: GpuObservation }) {
  const rows = [
    [gpuMonitoringText("metrics.temperature"), formatTemperature(observation.temperatureC)],
    [
      gpuMonitoringText("metrics.power"),
      observation.powerW === null ? "-" : `${observation.powerW.toFixed(1)} W`,
    ],
    [gpuMonitoringText("metrics.ecc"), observation.eccUncorrectableTotal ?? "-"],
    [gpuMonitoringText("metrics.xid"), observation.xidCode ?? "-"],
    [
      gpuMonitoringText("metrics.memory"),
      `${formatMib(observation.memoryUsedMib)} / ${formatMib(observation.memoryTotalMib)}`,
    ],
    [
      gpuMonitoringText("metrics.observed"),
      formatConsoleTimestamp(observation.observedAt, observation.observedAt),
    ],
  ] as const;
  return (
    <section aria-labelledby="gpu-metrics-title">
      <SectionHeader
        id="gpu-metrics-title"
        heading={gpuMonitoringText("metrics.title")}
        description={gpuMonitoringText("metrics.description")}
      />
      <dl class="gpu-metric-list">
        {rows.map(([label, value]) => (
          <div key={label}><dt>{label}</dt><dd>{value}</dd></div>
        ))}
      </dl>
    </section>
  );
}

export function GpuFindings({ findings }: { readonly findings: readonly GpuFinding[] }) {
  return (
    <section id="gpu-findings" aria-labelledby="gpu-findings-title">
      <SectionHeader
        id="gpu-findings-title"
        heading={gpuMonitoringText("findings.title")}
        description={gpuMonitoringText("findings.description")}
      />
      {findings.length === 0 ? (
        <p class="muted">{gpuMonitoringText("findings.none")}</p>
      ) : (
        <ul class="gpu-findings-list">
          {findings.map((finding, index) => (
            <li key={`${finding.kind}-${finding.status}-${index}`}>
              <span>{gpuMonitoringText(`findings.${finding.kind}`)}</span>
              <StatusPill
                kind={finding.status === "open" ? severityTone(finding.severity) : "success"}
                label={gpuMonitoringText(`findings.${finding.status}`)}
              />
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

export function GpuPipeline({ observation }: { readonly observation: GpuObservation }) {
  const path = observation.agentPath.length > 0
    ? [
      ...observation.agentPath,
      gpuMonitoringText("pipeline.eventBus"),
      gpuMonitoringText("pipeline.notification"),
    ]
    : [];
  return (
    <section aria-labelledby="gpu-pipeline-title">
      <SectionHeader
        id="gpu-pipeline-title"
        heading={gpuMonitoringText("pipeline.title")}
        description={gpuMonitoringText("pipeline.description")}
      />
      {path.length === 0 ? (
        <p class="muted">{gpuMonitoringText("pipeline.empty")}</p>
      ) : (
        <ol class="gpu-pipeline">
          {path.map((item, index) => (
            <li key={`${item}-${index}`}>
              <span>{item}</span>
              {index < path.length - 1 ? (
                <span class="gpu-pipeline-arrow" aria-hidden="true">→</span>
              ) : (
                <StatusPill kind="success" label={gpuMonitoringText("pipeline.verified")} />
              )}
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}

export function GpuAction({ action }: { readonly action: GpuActionEvidence | null }) {
  return (
    <section aria-labelledby="gpu-action-title">
      <SectionHeader
        id="gpu-action-title"
        heading={gpuMonitoringText("action.title")}
        description={gpuMonitoringText("action.description")}
      />
      {action === null ? (
        <p class="muted">{gpuMonitoringText("action.none")}</p>
      ) : (
        <dl class="gpu-action-list">
          <div>
            <dt>{gpuMonitoringText("action.actionType")}</dt>
            <dd><code>{action.actionType}</code></dd>
          </div>
          <div>
            <dt>{gpuMonitoringText("action.outcome")}</dt>
            <dd>{gpuMonitoringText(`action.${action.outcome}`)}</dd>
          </div>
          <div>
            <dt>{gpuMonitoringText("action.effect")}</dt>
            <dd>
              {gpuMonitoringText(
                action.effectVerified ? "action.verified" : "action.notVerified",
              )}
            </dd>
          </div>
          <div>
            <dt>{gpuMonitoringText("action.rollback")}</dt>
            <dd>
              {gpuMonitoringText(
                action.rollbackTested ? "action.tested" : "action.notTested",
              )}
            </dd>
          </div>
          <div>
            <dt>{gpuMonitoringText("action.powerState")}</dt>
            <dd>{gpuMonitoringText(`action.${action.powerState}`)}</dd>
          </div>
        </dl>
      )}
    </section>
  );
}

export function GpuProvenance({
  device,
  correlationId,
  dataMode,
}: {
  readonly device: GpuDeviceView;
  readonly correlationId: string;
  readonly dataMode: ConsoleDataMode;
}) {
  return (
    <section aria-labelledby="gpu-provenance-title">
      <SectionHeader
        id="gpu-provenance-title"
        heading={gpuMonitoringText("technical.title")}
        description={gpuMonitoringText("technical.eventCount", {
          count: device.history.length,
        })}
      />
      <dl class="gpu-provenance-list">
        <div>
          <dt>{gpuMonitoringText("technical.resourceRef")}</dt>
          <dd><code>{device.resourceRef}</code></dd>
        </div>
        <div>
          <dt>{gpuMonitoringText("technical.gpuId")}</dt>
          <dd><code>{device.gpuId}</code></dd>
        </div>
        <div>
          <dt>{gpuMonitoringText("technical.correlation")}</dt>
          <dd><code>{correlationId}</code></dd>
        </div>
        <div>
          <dt>{gpuMonitoringText("evidence.origin")}</dt>
          <dd><code>{device.evidenceOrigin}</code></dd>
        </div>
        <div>
          <dt>{gpuMonitoringText("inventory.source")}</dt>
          <dd><code>{device.source}</code></dd>
        </div>
        <div>
          <dt>{gpuMonitoringText("evidence.collector")}</dt>
          <dd>
            {gpuMonitoringText(`evidence.${device.latest?.collectorStatus ?? "degraded"}`)}
          </dd>
        </div>
      </dl>
      {dataMode === "sample" ? (
        <p class="gpu-sample-boundary">{gpuMonitoringText("technical.sampleBoundary")}</p>
      ) : null}
    </section>
  );
}

export function memoryPercent(observation: GpuObservation): number {
  return observation.memoryTotalMib === 0 ? 0 : observation.memoryUsedMib / observation.memoryTotalMib * 100;
}

export function formatPercent(value: number): string { return `${value.toFixed(value >= 10 ? 0 : 1)}%`; }

function SectionHeader({
  id,
  heading,
  description,
}: {
  readonly id?: string;
  readonly heading: string;
  readonly description: string;
}) {
  return (
    <header class="gpu-monitoring-section-head">
      <h3 {...(id === undefined ? {} : { id })}>{heading}</h3>
      <p>{description}</p>
    </header>
  );
}

function formatTemperature(value: number): string { return `${value.toFixed(0)} °C`; }

function formatMib(value: number): string { return `${Math.round(value).toLocaleString()} MiB`; }

function timeLabel(timestamp: string): string {
  return new Intl.DateTimeFormat(undefined, {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(new Date(timestamp));
}

function evidenceLabel(state: GpuEvidenceState): string {
  return gpuMonitoringText(`evidence.${state}`);
}

function evidenceTone(state: GpuEvidenceState): PillKind {
  if (state === "fresh") return "success";
  if (state === "stale") return "warning";
  if (state === "conflicting") return "danger";
  return "neutral";
}

function severityTone(severity: GpuFinding["severity"]): PillKind {
  if (severity === "high") return "danger";
  if (severity === "medium") return "warning";
  return "info";
}
