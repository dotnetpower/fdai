import { describe, expect, test } from "vitest";

import type { LiveStageEvent } from "../hooks/use-live-stream";
import { gpuLiveStreamHref } from "./gpu-monitoring";
import {
  decodeGpuObservation,
  gpuDeviceViews,
  gpuSampleObservations,
  mergeGpuObservation,
} from "./gpu-monitoring.model";

const NOW = Date.parse("2026-10-21T08:00:00Z");

function event(overrides: Record<string, unknown> = {}): LiveStageEvent {
  return {
    event_id: "gpu-event-1",
    correlation_id: "gpu-validation",
    stage: "verify",
    phase: "done",
    ts: "2026-10-21T08:00:00Z",
    detail: {
      kind: "gpu_observation",
      resource_ref: "resource:compute/vm/gpu-validation",
      gpu_id: "gpu-0",
      model: "NVIDIA H100 NVL",
      observed_at: "2026-10-21T07:59:55Z",
      source: "azure_vm_run_command",
      evidence_origin: "authenticated_live_observation",
      utilization_pct: 100,
      memory_used_mib: 93_910,
      memory_total_mib: 95_830,
      temperature_c: 35,
      power_w: 133.54,
      ecc_uncorrectable_total: 0,
      xid_code: 0,
      collector_status: "ready",
      finding: {
        kind: "memory_pressure",
        severity: "medium",
        status: "open",
      },
      action: null,
      agent_path: ["Huginn", "Heimdall"],
      ...overrides,
    },
  };
}

describe("GPU monitoring model", () => {
  test("decodes bounded authenticated live observations", () => {
    const decoded = decodeGpuObservation(event());

    expect(decoded).toMatchObject({
      model: "NVIDIA H100 NVL",
      utilizationPct: 100,
      evidenceOrigin: "authenticated_live_observation",
      finding: { kind: "memory_pressure", status: "open" },
      agentPath: ["Huginn", "Heimdall"],
    });
  });

  test("rejects invalid ranges and capacity conflicts", () => {
    expect(decodeGpuObservation(event({ utilization_pct: 101 }))).toBeNull();
    expect(decodeGpuObservation(event({
      memory_used_mib: 96_000,
      memory_total_mib: 95_830,
    }))).toBeNull();
    expect(decodeGpuObservation(event({ ecc_uncorrectable_total: 0.5 }))).toBeNull();
  });

  test("marks conflicting samples instead of silently replacing evidence", () => {
    const first = decodeGpuObservation(event())!;
    const changed = decodeGpuObservation(event({ utilization_pct: 20 }))!;
    const observations = mergeGpuObservation([first], changed);

    expect(observations).toHaveLength(1);
    expect(observations[0]!.evidenceState).toBe("conflicting");
    expect(gpuDeviceViews(observations, NOW)[0]!.evidenceState).toBe("conflicting");
  });

  test("deduplicates equivalent measurements with a different delivery envelope", () => {
    const first = decodeGpuObservation(event())!;
    const replayed = decodeGpuObservation({
      ...event(),
      event_id: "gpu-event-replayed",
      correlation_id: "gpu-validation-replayed",
    })!;

    const observations = mergeGpuObservation([first], replayed);

    expect(observations).toEqual([first]);
    expect(gpuDeviceViews(observations, NOW)[0]!.evidenceState).toBe("fresh");
  });

  test("classifies fresh, stale, and future evidence", () => {
    const fresh = decodeGpuObservation(event())!;
    expect(gpuDeviceViews([fresh], NOW)[0]!.evidenceState).toBe("fresh");
    expect(gpuDeviceViews([fresh], NOW + 121_000)[0]!.evidenceState).toBe("stale");
    expect(gpuDeviceViews([fresh], NOW - 30_000)[0]!.evidenceState).toBe("conflicting");
  });

  test("keeps sample history bounded and retains verified action evidence", () => {
    const observations = gpuSampleObservations(NOW);
    const view = gpuDeviceViews(observations, NOW)[0]!;

    expect(view.history).toHaveLength(7);
    expect(view.history.some((item) => item.utilizationPct === 100)).toBe(true);
    expect(view.findings.map((finding) => finding.status)).toEqual(["open", "cleared"]);
    expect(view.action).toMatchObject({
      actionType: "ops.deallocate-vm",
      outcome: "succeeded",
      effectVerified: true,
      rollbackTested: true,
      powerState: "deallocated",
    });
    expect(gpuLiveStreamHref("live")).toBe("/live");
    expect(gpuLiveStreamHref("sample")).toBe("/live?data=sample");
  });
});
