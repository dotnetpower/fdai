import type { RuntimeDiagnosticsView } from "./settings-runtime.model";

export interface DiagnosticResult {
  readonly status: "available" | "unavailable";
  readonly checkedAt: string;
  readonly durationMs: number;
}

export async function observeDiagnostic(
  read: () => Promise<unknown>,
  accepts: (value: unknown) => boolean = () => true,
  clock: () => number = () => performance.now(),
  timestamp: () => string = () => new Date().toISOString(),
): Promise<DiagnosticResult> {
  const start = clock();
  let available = false;
  try { available = accepts(await read()); } catch { /* A failed read is unavailable, not a provider health diagnosis. */ }
  return {
    status: available ? "available" : "unavailable",
    checkedAt: timestamp(),
    durationMs: Math.max(0, Math.round(clock() - start)),
  };
}

export function diagnosticSummary(
  results: readonly (DiagnosticResult | null)[],
  checking: readonly boolean[],
) {
  return {
    available: results.filter((result, index) => !checking[index] && result?.status === "available").length,
    unavailable: results.filter((result, index) => !checking[index] && result?.status === "unavailable").length,
    checking: checking.filter(Boolean).length,
  };
}

export function diagnosticBooleanKind(key: string): "durable" | "configured" | "enabled" {
  if (key === "stateStore") return "durable";
  return ["primaryTransport", "auxiliaryTransport", "caseHistory"].includes(key)
    ? "configured" : "enabled";
}

export function diagnosticSupportSummary(
  liveness: DiagnosticResult | null,
  readPath: DiagnosticResult | null,
  runtime: RuntimeDiagnosticsView | null,
  runtimeObservedAt: string | null,
  runtimeStale = false,
): string {
  const safeResult = (result: DiagnosticResult | null) => result === null ? null : {
    status: result.status, checkedAt: result.checkedAt, durationMs: result.durationMs,
  };
  return JSON.stringify({
    operator_api_liveness: safeResult(liveness),
    kpi_read_path: safeResult(readPath),
    runtime_observed_at: runtimeObservedAt,
    runtime_stale: runtimeStale,
    runtime: runtime === null ? null : {
      environment: runtime.environment,
      state_store_durable: runtime.stateStoreDurable,
      pantheon_enabled: runtime.pantheonEnabled,
      workflow_observation_enabled: runtime.workflowObservationEnabled,
      primary_transport_configured: runtime.primaryTransportConfigured,
      auxiliary_transport_configured: runtime.auxiliaryTransportConfigured,
      case_history_configured: runtime.caseHistoryConfigured,
    },
  }, null, 2);
}
