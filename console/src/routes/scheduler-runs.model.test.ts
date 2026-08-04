import { describe, expect, test } from "vitest";
import {
  appendSchedulerRunPage,
  decodeSchedulerRunPage,
  formatSchedulerTimestamp,
  schedulerRunTone,
  summarizeSchedulerRuns,
} from "./scheduler-runs.model";
import { assertSchedulerRunTask } from "./scheduler-runs";

const PAGE = {
  task_id: "inventory",
  source: "synthetic-dev",
  durable: false,
  items: [{
    run_id: "schedule:inventory:1",
    task_id: "inventory",
    scheduled_for: "2026-07-17T08:00:00+00:00",
    claimed_at: "2026-07-17T08:00:01+00:00",
    status: "published",
    attempt: 1,
    completed_at: "2026-07-17T08:00:02+00:00",
    error_kind: null,
  }],
  next_cursor: "next",
};

describe("scheduler run response", () => {
  test("decodes a bounded history page", () => {
    const page = decodeSchedulerRunPage(PAGE);
    expect(page.task_id).toBe("inventory");
    expect(page.source).toBe("synthetic-dev");
    expect(page.durable).toBe(false);
    expect(page.items[0]?.status).toBe("published");
    expect(page.next_cursor).toBe("next");
  });

  test("rejects unknown machine status", () => {
    expect(() => decodeSchedulerRunPage({
      ...PAGE,
      items: [{ ...PAGE.items[0], status: "running" }],
    })).toThrow("status is invalid");
  });

  test("appends only the requested cursor page and removes retry duplicates", () => {
    const current = decodeSchedulerRunPage(PAGE);
    const duplicate = PAGE.items[0]!;
    const next = decodeSchedulerRunPage({
      ...PAGE,
      items: [duplicate, { ...duplicate, run_id: "schedule:inventory:2" }],
      next_cursor: null,
    });

    expect(appendSchedulerRunPage(current, "stale", next)).toBe(current);
    expect(appendSchedulerRunPage(current, "next", next).items.map((item) => item.run_id))
      .toEqual(["schedule:inventory:1", "schedule:inventory:2"]);
  });

  test("maps terminal failure states to danger", () => {
    expect(schedulerRunTone("published")).toBe("success");
    expect(schedulerRunTone("claimed")).toBe("warning");
    expect(schedulerRunTone("lost")).toBe("danger");
  });

  test("rejects a response for a different requested task", () => {
    const page = decodeSchedulerRunPage(PAGE);
    expect(() => assertSchedulerRunTask(page, "cost-probe")).toThrow(
      "task_id does not match",
    );
    expect(() => assertSchedulerRunTask(page, "inventory")).not.toThrow();
  });

  test("formats valid timestamps with a timezone and preserves invalid evidence", () => {
    expect(formatSchedulerTimestamp(null)).toBe("-");
    expect(formatSchedulerTimestamp("not-a-timestamp")).toBe("not-a-timestamp");
    expect(formatSchedulerTimestamp("2026-07-17T08:00:00Z")).toMatch(/2026/);
  });

  test("summarizes publish evidence without claiming execution success", () => {
    const published = decodeSchedulerRunPage(PAGE).items[0]!;
    const failed = {
      ...published,
      run_id: "schedule:inventory:2",
      status: "failed" as const,
      claimed_at: "2026-07-17T08:00:03Z",
      completed_at: "2026-07-17T08:00:07Z",
      error_kind: "publish_timeout",
    };
    const invalid = {
      ...published,
      run_id: "schedule:inventory:3",
      status: "lost" as const,
      claimed_at: "invalid",
      completed_at: "2026-07-17T08:00:09Z",
    };

    expect(summarizeSchedulerRuns([published, failed, invalid])).toEqual({
      loaded: 3,
      published: 1,
      failedOrLost: 2,
      publishRate: 1 / 3,
      medianCloseMs: 1000,
      p95CloseMs: 4000,
    });
    expect(summarizeSchedulerRuns([])).toEqual({
      loaded: 0,
      published: 0,
      failedOrLost: 0,
      publishRate: null,
      medianCloseMs: null,
      p95CloseMs: null,
    });
  });
});
