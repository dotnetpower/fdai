import { describe, expect, it } from "vitest";
import {
  appendBackgroundTaskPage,
  backgroundTaskTone,
  decodeBackgroundTaskPage,
  decodeBackgroundTaskProgress,
} from "./background-tasks.model";

const TASK = {
  task_id: "task-one",
  attempt_id: "task-one:1",
  request_summary: "Investigate the latency regression after the rollout.",
  request_truncated: false,
  accountable_agent: "Heimdall",
  execution_worker: "background-task-coordinator",
  kind: "read_only_investigation",
  status: "running",
  revision: 2,
  created_at: "2026-08-23T05:00:00+00:00",
  updated_at: "2026-08-23T05:01:00+00:00",
  retention_until: "2026-09-22T05:00:00+00:00",
  lease_expires_at: "2026-08-23T05:01:30+00:00",
  budget: { max_wall_seconds: 300 },
  usage: { tokens: 10, cost_microusd: 20, tool_calls: 1 },
  result_summary: null,
  result_truncated: false,
  evidence_refs: [],
  evidence_truncated: false,
  terminal_reason: null,
  started_at: "2026-08-23T05:00:01+00:00",
  finished_at: null,
  duration_seconds: null,
  completion_state: null,
};

describe("background task model", () => {
  it("decodes a bounded page and cursor", () => {
    const page = decodeBackgroundTaskPage({
      tasks: [TASK],
      has_more: true,
      next_cursor: {
        before_updated_at: TASK.updated_at,
        before_task_id: TASK.task_id,
      },
    });

    expect(page.tasks[0]?.status).toBe("running");
    expect(page.tasks[0]?.accountable_agent).toBe("Heimdall");
    expect(page.tasks[0]?.request_summary).toContain("latency regression");
    expect(page.next_cursor?.before_task_id).toBe("task-one");
  });

  it("keeps legacy projections explicit instead of inventing attribution", () => {
    const {
      request_summary: _requestSummary,
      request_truncated: _requestTruncated,
      accountable_agent: _agent,
      execution_worker: _worker,
      result_summary: _resultSummary,
      result_truncated: _resultTruncated,
      evidence_refs: _evidenceRefs,
      evidence_truncated: _evidenceTruncated,
      ...legacy
    } = TASK;
    const page = decodeBackgroundTaskPage({
      tasks: [legacy],
      has_more: false,
      next_cursor: null,
    });

    expect(page.tasks[0]?.request_summary).toBeNull();
    expect(page.tasks[0]?.accountable_agent).toBeNull();
    expect(page.tasks[0]?.execution_worker).toBe("background-task-coordinator");
    expect(page.tasks[0]?.evidence_refs).toEqual([]);
  });

  it("rejects unsupported status and inconsistent cursors", () => {
    expect(() => decodeBackgroundTaskPage({
      tasks: [{ ...TASK, status: "invented" }],
      has_more: false,
      next_cursor: null,
    })).toThrow("status is invalid");
    expect(() => decodeBackgroundTaskPage({
      tasks: [],
      has_more: true,
      next_cursor: null,
    })).toThrow("cursor MUST match has_more");
  });

  it("requires monotonic progress", () => {
    expect(() => decodeBackgroundTaskProgress({
      task_id: "task-one",
      status: "running",
      next_sequence: 1,
      has_more: false,
      events: [
        { sequence: 1, kind: "second", message: "Second", at: TASK.updated_at, usage: {} },
        { sequence: 0, kind: "first", message: "First", at: TASK.created_at, usage: {} },
      ],
    })).toThrow("sequence MUST increase");
  });

  it("merges pagination without duplicate tasks", () => {
    const cursor = { before_updated_at: TASK.updated_at, before_task_id: TASK.task_id };
    const current = decodeBackgroundTaskPage({
      tasks: [TASK],
      has_more: true,
      next_cursor: cursor,
    });
    const next = decodeBackgroundTaskPage({
      tasks: [TASK, { ...TASK, task_id: "task-two", attempt_id: "task-two:1" }],
      has_more: false,
      next_cursor: null,
    });

    expect(appendBackgroundTaskPage(current, cursor, next).tasks.map((task) => task.task_id))
      .toEqual(["task-one", "task-two"]);
  });

  it("maps task states to local status tones", () => {
    expect(backgroundTaskTone("succeeded")).toBe("success");
    expect(backgroundTaskTone("running")).toBe("warning");
    expect(backgroundTaskTone("failed")).toBe("danger");
    expect(backgroundTaskTone("cancelled")).toBe("neutral");
  });
});
