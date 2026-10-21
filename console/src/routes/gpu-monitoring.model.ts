import type { LiveStageEvent } from "../hooks/use-live-stream";

export type GpuEvidenceState = "fresh" | "stale" | "missing" | "conflicting";
export type GpuFindingStatus = "open" | "cleared";

export interface GpuFinding {
  readonly kind:
    | "memory_pressure"
    | "sustained_saturation_backlog"
    | "high_temperature"
    | "new_ecc_error"
    | "new_xid_code"
    | "observed_cuda_oom"
    | "observed_thermal_throttle"
    | "allocated_idle_window";
  readonly severity: "low" | "medium" | "high";
  readonly status: GpuFindingStatus;
}

export interface GpuActionEvidence {
  readonly actionType: "ops.deallocate-vm" | "ops.start-vm";
  readonly outcome: "succeeded" | "failed" | "unknown";
  readonly effectVerified: boolean;
  readonly rollbackTested: boolean;
  readonly powerState: "running" | "deallocated" | "unknown";
}

export interface GpuObservation {
  readonly eventId: string;
  readonly correlationId: string;
  readonly resourceRef: string;
  readonly gpuId: string;
  readonly model: string;
  readonly observedAt: string;
  readonly source: "azure_monitor" | "datadog" | "azure_vm_run_command";
  readonly evidenceOrigin: "synthetic_replay" | "authenticated_live_observation";
  readonly utilizationPct: number;
  readonly memoryUsedMib: number;
  readonly memoryTotalMib: number;
  readonly temperatureC: number;
  readonly powerW: number | null;
  readonly eccUncorrectableTotal: number | null;
  readonly xidCode: number | null;
  readonly collectorStatus: "ready" | "degraded";
  readonly evidenceState: Exclude<GpuEvidenceState, "missing" | "stale">;
  readonly finding: GpuFinding | null;
  readonly action: GpuActionEvidence | null;
  readonly agentPath: readonly string[];
}

export interface GpuDeviceView {
  readonly key: string;
  readonly gpuId: string;
  readonly model: string;
  readonly resourceRef: string;
  readonly source: GpuObservation["source"];
  readonly evidenceOrigin: GpuObservation["evidenceOrigin"];
  readonly evidenceState: GpuEvidenceState;
  readonly ageSeconds: number | null;
  readonly latest: GpuObservation | null;
  readonly history: readonly GpuObservation[];
  readonly findings: readonly GpuFinding[];
  readonly action: GpuActionEvidence | null;
}

const GPU_HISTORY_LIMIT = 120;
const GPU_FLEET_LIMIT = 500;
const GPU_FRESHNESS_MS = 120_000;
const FUTURE_SKEW_MS = 15_000;
const SOURCES = new Set<GpuObservation["source"]>([
  "azure_monitor",
  "datadog",
  "azure_vm_run_command",
]);
const ORIGINS = new Set<GpuObservation["evidenceOrigin"]>([
  "synthetic_replay",
  "authenticated_live_observation",
]);
const FINDING_KINDS = new Set<GpuFinding["kind"]>([
  "memory_pressure",
  "sustained_saturation_backlog",
  "high_temperature",
  "new_ecc_error",
  "new_xid_code",
  "observed_cuda_oom",
  "observed_thermal_throttle",
  "allocated_idle_window",
]);

export function decodeGpuObservation(event: LiveStageEvent): GpuObservation | null {
  const detail = event.detail;
  if (detail?.kind !== "gpu_observation") return null;
  const resourceRef = boundedString(detail.resource_ref);
  const gpuId = boundedString(detail.gpu_id);
  const model = boundedString(detail.model);
  const observedAt = timestamp(detail.observed_at);
  const source = detail.source;
  const evidenceOrigin = detail.evidence_origin;
  const utilizationPct = finiteNumber(detail.utilization_pct, 0, 100);
  const memoryUsedMib = finiteNumber(detail.memory_used_mib, 0);
  const memoryTotalMib = finiteNumber(detail.memory_total_mib, Number.MIN_VALUE);
  const temperatureC = finiteNumber(detail.temperature_c, 0);
  if (
    resourceRef === null ||
    gpuId === null ||
    model === null ||
    observedAt === null ||
    typeof source !== "string" ||
    !SOURCES.has(source as GpuObservation["source"]) ||
    typeof evidenceOrigin !== "string" ||
    !ORIGINS.has(evidenceOrigin as GpuObservation["evidenceOrigin"]) ||
    utilizationPct === null ||
    memoryUsedMib === null ||
    memoryTotalMib === null ||
    memoryUsedMib > memoryTotalMib ||
    temperatureC === null
  ) {
    return null;
  }
  const powerW = optionalNumber(detail.power_w, 0);
  const eccUncorrectableTotal = optionalInteger(detail.ecc_uncorrectable_total);
  const xidCode = optionalInteger(detail.xid_code);
  if (
    powerW === undefined ||
    eccUncorrectableTotal === undefined ||
    xidCode === undefined
  ) {
    return null;
  }
  const collectorStatus = detail.collector_status;
  if (collectorStatus !== "ready" && collectorStatus !== "degraded") return null;
  const finding = decodeFinding(detail.finding);
  const action = decodeAction(detail.action);
  const agentPath = decodeAgentPath(detail.agent_path);
  if (finding === undefined || action === undefined || agentPath === null) return null;
  return {
    eventId: event.event_id,
    correlationId: event.correlation_id,
    resourceRef,
    gpuId,
    model,
    observedAt,
    source: source as GpuObservation["source"],
    evidenceOrigin: evidenceOrigin as GpuObservation["evidenceOrigin"],
    utilizationPct,
    memoryUsedMib,
    memoryTotalMib,
    temperatureC,
    powerW,
    eccUncorrectableTotal,
    xidCode,
    collectorStatus,
    evidenceState: "fresh",
    finding,
    action,
    agentPath,
  };
}

export function mergeGpuObservation(
  current: readonly GpuObservation[],
  incoming: GpuObservation,
): readonly GpuObservation[] {
  const sampleKey = observationKey(incoming);
  const existing = current.find((item) => observationKey(item) === sampleKey);
  const next = existing === undefined
    ? [...current, incoming]
    : equivalentObservation(existing, incoming)
      ? [...current]
      : current.map((item) =>
        observationKey(item) === sampleKey
          ? { ...incoming, evidenceState: "conflicting" as const }
          : item
      );
  next.sort((left, right) => Date.parse(left.observedAt) - Date.parse(right.observedAt));
  return next.slice(-GPU_FLEET_LIMIT);
}

export function gpuDeviceViews(
  observations: readonly GpuObservation[],
  now = Date.now(),
): readonly GpuDeviceView[] {
  const grouped = new Map<string, GpuObservation[]>();
  for (const observation of observations) {
    const key = deviceKey(observation);
    grouped.set(key, [...(grouped.get(key) ?? []), observation]);
  }
  return [...grouped.entries()]
    .map(([key, values]) => {
      const history = [...values]
        .sort((left, right) => Date.parse(left.observedAt) - Date.parse(right.observedAt))
        .slice(-GPU_HISTORY_LIMIT);
      const latest = history.at(-1) ?? null;
      const observedAt = latest === null ? Number.NaN : Date.parse(latest.observedAt);
      const ageMilliseconds = now - observedAt;
      const evidenceState: GpuEvidenceState =
        latest === null
          ? "missing"
          : history.some((item) => item.evidenceState === "conflicting") ||
              ageMilliseconds < -FUTURE_SKEW_MS
            ? "conflicting"
            : ageMilliseconds > GPU_FRESHNESS_MS
              ? "stale"
              : "fresh";
      return {
        key,
        gpuId: latest?.gpuId ?? key,
        model: latest?.model ?? "Unknown GPU",
        resourceRef: latest?.resourceRef ?? "",
        source: latest?.source ?? "azure_monitor",
        evidenceOrigin: latest?.evidenceOrigin ?? "synthetic_replay",
        evidenceState,
        ageSeconds: Number.isFinite(ageMilliseconds)
          ? Math.max(0, Math.floor(ageMilliseconds / 1_000))
          : null,
        latest,
        history,
        findings: history.flatMap((item) => item.finding === null ? [] : [item.finding]),
        action: [...history].reverse().find((item) => item.action !== null)?.action ?? null,
      };
    })
    .sort((left, right) => left.resourceRef.localeCompare(right.resourceRef) ||
      left.gpuId.localeCompare(right.gpuId));
}

export function gpuSampleObservations(now = Date.now()): readonly GpuObservation[] {
  const points = [
    { offset: -70_000, utilization: 0, memory: 23, temperature: 32, power: 63.06 },
    { offset: -55_000, utilization: 0, memory: 768, temperature: 33, power: 90.17 },
    { offset: -50_000, utilization: 100, memory: 93_910, temperature: 35, power: 133.54 },
    { offset: -45_000, utilization: 17, memory: 804, temperature: 35, power: 91.37 },
    { offset: -30_000, utilization: 0, memory: 133, temperature: 34, power: 63.65 },
    { offset: -15_000, utilization: 0, memory: 133, temperature: 34, power: 63.54 },
    { offset: -5_000, utilization: 0, memory: 133, temperature: 33, power: 63.37 },
  ] as const;
  return points.map((point, index) => ({
    eventId: `gpu-sample-${index + 1}`,
    correlationId: "gpu-live-validation",
    resourceRef: "resource:compute/vm/gpu-validation",
    gpuId: "gpu-h100-validation-0",
    model: "NVIDIA H100 NVL",
    observedAt: new Date(now + point.offset).toISOString(),
    source: "azure_vm_run_command",
    evidenceOrigin: "authenticated_live_observation",
    utilizationPct: point.utilization,
    memoryUsedMib: point.memory,
    memoryTotalMib: 95_830,
    temperatureC: point.temperature,
    powerW: point.power,
    eccUncorrectableTotal: 0,
    xidCode: 0,
    collectorStatus: "ready",
    evidenceState: "fresh",
    finding: index === 2
      ? { kind: "memory_pressure", severity: "medium", status: "open" }
      : index === points.length - 1
        ? { kind: "memory_pressure", severity: "medium", status: "cleared" }
        : null,
    action: index === points.length - 1
      ? {
        actionType: "ops.deallocate-vm",
        outcome: "succeeded",
        effectVerified: true,
        rollbackTested: true,
        powerState: "deallocated",
      }
      : null,
    agentPath: ["Huginn", "Heimdall"],
  }));
}

function observationKey(observation: GpuObservation): string {
  return `${deviceKey(observation)}:${observation.observedAt}`;
}

function deviceKey(observation: GpuObservation): string {
  return `${observation.resourceRef}:${observation.gpuId}:${observation.source}`;
}

function equivalentObservation(left: GpuObservation, right: GpuObservation): boolean {
  return JSON.stringify(observationEvidence(left)) === JSON.stringify(observationEvidence(right));
}

function observationEvidence(observation: GpuObservation): object {
  const {
    eventId: _eventId,
    correlationId: _correlationId,
    evidenceState: _evidenceState,
    ...evidence
  } = observation;
  return evidence;
}

function boundedString(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 && value.length <= 512
    ? value
    : null;
}

function timestamp(value: unknown): string | null {
  return typeof value === "string" && Number.isFinite(Date.parse(value))
    ? value
    : null;
}

function finiteNumber(value: unknown, minimum: number, maximum = Number.MAX_VALUE): number | null {
  return typeof value === "number" &&
      Number.isFinite(value) &&
      value >= minimum &&
      value <= maximum
    ? value
    : null;
}

function optionalNumber(
  value: unknown,
  minimum: number,
): number | null | undefined {
  return value === null || value === undefined
    ? null
    : finiteNumber(value, minimum) ?? undefined;
}

function optionalInteger(value: unknown): number | null | undefined {
  return value === null || value === undefined
    ? null
    : Number.isInteger(value) && typeof value === "number" && value >= 0
      ? value
      : undefined;
}

function decodeFinding(value: unknown): GpuFinding | null | undefined {
  if (value === null || value === undefined) return null;
  if (typeof value !== "object" || Array.isArray(value)) return undefined;
  const finding = value as Record<string, unknown>;
  if (
    typeof finding.kind !== "string" ||
    !FINDING_KINDS.has(finding.kind as GpuFinding["kind"]) ||
    (finding.severity !== "low" &&
      finding.severity !== "medium" &&
      finding.severity !== "high") ||
    (finding.status !== "open" && finding.status !== "cleared")
  ) {
    return undefined;
  }
  return finding as unknown as GpuFinding;
}

function decodeAction(value: unknown): GpuActionEvidence | null | undefined {
  if (value === null || value === undefined) return null;
  if (typeof value !== "object" || Array.isArray(value)) return undefined;
  const action = value as Record<string, unknown>;
  if (
    (action.action_type !== "ops.deallocate-vm" &&
      action.action_type !== "ops.start-vm") ||
    (action.outcome !== "succeeded" &&
      action.outcome !== "failed" &&
      action.outcome !== "unknown") ||
    typeof action.effect_verified !== "boolean" ||
    typeof action.rollback_tested !== "boolean" ||
    (action.power_state !== "running" &&
      action.power_state !== "deallocated" &&
      action.power_state !== "unknown")
  ) {
    return undefined;
  }
  return {
    actionType: action.action_type,
    outcome: action.outcome,
    effectVerified: action.effect_verified,
    rollbackTested: action.rollback_tested,
    powerState: action.power_state,
  };
}

function decodeAgentPath(value: unknown): readonly string[] | null {
  if (value === null || value === undefined) return [];
  return Array.isArray(value) &&
      value.length <= 15 &&
      value.every((item) => typeof item === "string" && item.length > 0 && item.length <= 64)
    ? value
    : null;
}
