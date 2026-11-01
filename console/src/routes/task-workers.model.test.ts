import { describe, expect, it } from "vitest";
import {
  buildTaskWorkersViewModel,
  decodeTaskWorkerDetailProjection,
  decodeTaskWorkerEventsProjection,
  decodeTaskWorkerListProjection,
} from "./task-workers.model";

const SAMPLE_WORKER_ROW = {
  worker_id: "worker-1",
  parent_trace_ref: "trace-1",
  status: "succeeded",
  budget: {
    max_wall_seconds: 30,
    max_tool_calls: 8,
    max_tokens: 4096,
    max_cost_microusd: 500000,
    heartbeat_seconds: 5,
  },
  created_at: "2026-11-01T12:00:00Z",
  updated_at: "2026-11-01T12:00:05Z",
  heartbeat_at: "2026-11-01T12:00:04Z",
  allowed_tools: ["get_resource_state", "resolve_resource"],
  denied_tools: [],
  evidence_count: 2,
  usage: {
    tokens: 320,
    cost_microusd: 1200,
    tool_calls: 2,
  },
  terminal_reason: "completed",
  trusted: false,
  read_only: true,
  execution_authority: "none",
};

describe("task-workers.model", () => {
  it("decodes list, detail, and event projections and builds bilingual read-only view models", () => {
    const list = decodeTaskWorkerListProjection({
      read_only: true,
      execution_authority: "none",
      workers: [SAMPLE_WORKER_ROW],
    });
    const detail = decodeTaskWorkerDetailProjection({
      read_only: true,
      execution_authority: "none",
      worker: {
        ...SAMPLE_WORKER_ROW,
        evidence_refs: ["inv:res-1", "inv:res-2"],
        result: {
          worker_id: "worker-1",
          parent_trace_ref: "trace-1",
          status: "succeeded",
          summary: "Observed resource state is healthy.",
          evidence_refs: ["inv:res-1", "inv:res-2"],
          caveats: [],
          usage: { tokens: 320, cost_microusd: 1200, tool_calls: 2 },
          terminal_reason: "completed",
          started_at: "2026-11-01T12:00:01Z",
          finished_at: "2026-11-01T12:00:05Z",
          trusted: false,
        },
      },
    });
    const events = decodeTaskWorkerEventsProjection({
      read_only: true,
      execution_authority: "none",
      worker_id: "worker-1",
      events: [
        {
          worker_id: "worker-1",
          sequence: 0,
          kind: "worker.created",
          at: "2026-11-01T12:00:00Z",
          details: [["parent_trace_ref", "trace-1"]],
        },
        {
          worker_id: "worker-1",
          sequence: 1,
          kind: "worker.completion_delivery_failed",
          at: "2026-11-01T12:00:05Z",
          details: [["error", "RuntimeError"]],
        },
      ],
    });

    const enView = buildTaskWorkersViewModel(list, "en", detail, events);
    expect(enView.readOnly).toBe(true);
    expect(enView.executionAuthority).toBe("none");
    expect(enView.canCreateWorker).toBe(false);
    expect(enView.canCancelWorker).toBe(false);
    expect(enView.canApproveOrExecute).toBe(false);
    expect(enView.workers[0]?.statusLabel).toBe("Succeeded");
    expect(enView.workers[0]?.untrustedBadgeLabel).toBe("Untrusted contribution");
    expect(enView.selectedSummary).toBe("Observed resource state is healthy.");
    expect(enView.deliveryFailedEventCount).toBe(1);

    const koView = buildTaskWorkersViewModel(list, "ko", detail, events);
    expect(koView.title).toBe("제한형 작업 워커");
    expect(koView.workers[0]?.statusLabel).toBe("성공");
    expect(koView.workers[0]?.untrustedBadgeLabel).toBe("신뢰되지 않은 워커 결과");
    expect(koView.canApproveOrExecute).toBe(false);
  });

  it("rejects goal/constraints leakage in list rows or trusted=true worker outputs", () => {
    expect(() =>
      decodeTaskWorkerListProjection({
        read_only: true,
        execution_authority: "none",
        workers: [{ ...SAMPLE_WORKER_ROW, goal: "leaked goal" }],
      }),
    ).toThrow(/MUST NOT expose goal or constraints/);

    expect(() =>
      decodeTaskWorkerListProjection({
        read_only: true,
        execution_authority: "none",
        workers: [{ ...SAMPLE_WORKER_ROW, trusted: true }],
      }),
    ).toThrow(/trusted MUST be false/);

    expect(() =>
      decodeTaskWorkerListProjection({
        read_only: true,
        execution_authority: "none",
        workers: [SAMPLE_WORKER_ROW, SAMPLE_WORKER_ROW],
      }),
    ).toThrow(/duplicate worker_id/);

    const truncatedDetail = decodeTaskWorkerDetailProjection({
      read_only: true,
      execution_authority: "none",
      worker: {
        ...SAMPLE_WORKER_ROW,
        evidence_refs: ["inv:res-1"],
        result: {
          worker_id: "worker-1",
          parent_trace_ref: "trace-1",
          status: "succeeded",
          summary: "Truncated summary...",
          summary_truncated: true,
          evidence_refs: ["inv:res-1"],
          caveats: [],
          usage: { tokens: 320, cost_microusd: 1200, tool_calls: 2 },
          terminal_reason: "completed",
          started_at: "2026-11-01T12:00:01Z",
          finished_at: "2026-11-01T12:00:05Z",
          trusted: false,
        },
      },
    });
    expect(truncatedDetail.worker.result?.summary_truncated).toBe(true);
  });
});
