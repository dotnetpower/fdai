import { describe, expect, test } from "vitest";
import type { AuditItem } from "../types";
import { appendAuditPage } from "./audit.model";

function item(seq: number): AuditItem {
  return { seq, event_id: `event-${seq}`, correlation_id: null, actor: "fdai", action_kind: "test", mode: "shadow", entry: {}, entry_hash: "hash", previous_hash: "previous", recorded_at: "2026-07-13T00:00:00Z" };
}

describe("audit pagination", () => {
  test("appends only the response for the current cursor", () => {
    const current = { items: [item(2)], nextCursor: "cursor-2" };
    expect(appendAuditPage(current, "stale", { items: [item(1)], next_cursor: null })).toBe(current);
    expect(appendAuditPage(current, "cursor-2", { items: [item(1)], next_cursor: null })).toEqual({ items: [item(2), item(1)], nextCursor: null });
  });

  test("deduplicates replayed audit rows", () => {
    const current = { items: [item(2)], nextCursor: "cursor-2" };
    expect(appendAuditPage(current, "cursor-2", { items: [item(2), item(1)], next_cursor: null }).items.map((row) => row.seq)).toEqual([2, 1]);
  });
});