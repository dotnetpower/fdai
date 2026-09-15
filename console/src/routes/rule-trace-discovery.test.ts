import { describe, expect, it } from "vitest";
import type { AuditItem, AuditPage } from "../types";
import { buildTraceDiscovery } from "./rule-trace-discovery";

const item = (
  seq: number,
  correlationId: string | null,
  actionKind: string,
  entry: Record<string, unknown> = {},
): AuditItem => ({
  seq,
  event_id: `event-${seq}`,
  correlation_id: correlationId,
  actor: seq % 2 === 0 ? "Forseti" : "fdai.measurement",
  action_kind: actionKind,
  mode: "shadow",
  entry,
  entry_hash: `hash-${seq}`,
  previous_hash: `hash-${seq - 1}`,
  recorded_at: `2026-09-14T03:00:0${seq}Z`,
});

describe("recent Trace discovery", () => {
  it("groups newest correlations without presenting an incomplete Audit page as history", () => {
    const page: AuditPage = {
      items: [
        item(4, null, "notification.route"),
        item(3, "corr-read", "measurement.control_loop.v1", {
          resource_ref: "resource-1",
        }),
        item(2, "corr-decision", "risk_gate.unified", {
          decision: "hil",
          target_resource_ref: "resource-2",
        }),
        item(1, "corr-read", "control_loop.compliant", {
          resource_ref: "resource-1",
        }),
      ],
      next_cursor: "older",
    };

    const discovery = buildTraceDiscovery(page);

    expect(discovery.indexComplete).toBe(false);
    expect(discovery.sampledRecordCount).toBe(4);
    expect(discovery.items.map((trace) => trace.correlationId)).toEqual([
      "corr-read",
      "corr-decision",
    ]);
    expect(discovery.items[0]).toEqual(expect.objectContaining({
      traceKind: "read",
      sampledRecordCount: 2,
      targetResourceRef: "resource-1",
    }));
    expect(discovery.items[1]).toEqual(expect.objectContaining({
      traceKind: "decision",
      latestDecision: "hil",
      targetResourceRef: "resource-2",
    }));
  });

  it("keeps null and sentinel correlations out and honors the item limit", () => {
    const page: AuditPage = {
      items: [
        item(4, "None", "notification.route"),
        item(3, "corr-3", "notification.route"),
        item(2, "corr-2", "notification.route"),
        item(1, "corr-1", "notification.route"),
      ],
      next_cursor: null,
    };

    const discovery = buildTraceDiscovery(page, 2);

    expect(discovery.indexComplete).toBe(true);
    expect(discovery.items.map((trace) => trace.correlationId)).toEqual([
      "corr-3",
      "corr-2",
    ]);
  });
});
