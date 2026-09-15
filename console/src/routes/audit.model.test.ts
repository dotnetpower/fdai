import { describe, expect, test } from "vitest";
import type { AuditItem } from "../types";
import { appendAuditPage, auditContextRecord, auditEntryText, auditRecordedPhase, resolveAuditEntry, searchAuditItems } from "./audit.model";
import { auditFiltersFromSearch } from "./audit";

function item(seq: number): AuditItem {
  return { seq, event_id: `event-${seq}`, correlation_id: null, actor: "fdai", action_kind: "test", mode: "shadow", entry: {}, entry_hash: "hash", previous_hash: "previous", recorded_at: "2026-07-13T00:00:00Z" };
}

describe("audit pagination", () => {
  test("keeps selected record identity and causal fields in screen context", () => {
    expect(auditContextRecord({
      ...item(42), entry: { reason: "Requires human approval", detail: "No dispatch", outcome: "hil" },
    })).toMatchObject({
      seq: 42, reason: "Requires human approval", detail: "No dispatch", outcome: "hil", summary: "-",
    });
  });
  test("searches recorded identities only within the loaded page", () => {
    const first = { ...item(2), actor: "Saga", entry: { idempotency_key: "idem-one", rule_id: "rule-one" } };
    const second = { ...item(1), entry: { summary: "Saga is mentioned, but is not the actor" } };
    expect(searchAuditItems([first, second], " saga ")).toEqual([first]);
    expect(searchAuditItems([first, second], "IDEM-ONE")).toEqual([first]);
    expect(searchAuditItems([first, second], "rule-one")).toEqual([first]);
    expect(searchAuditItems([first, second], "absent")).toEqual([]);
    expect(searchAuditItems([first, second], "")).toEqual([first, second]);
  });

  test("does not convert outcomes, hashes, or action names into verified stages", () => {
    const record = { ...item(1), action_kind: "effect_observation.recorded", entry: { outcome: "succeeded" } };
    expect(auditRecordedPhase(record)).toBeNull();
    expect(auditRecordedPhase({ ...record, entry: { stage: "verify" } })).toBe("observe");
    expect(auditRecordedPhase({ ...record, entry: { stage: "execute" } })).toBe("dispatch");
    expect(auditRecordedPhase({ ...record, entry: { stage: "unknown" } })).toBeNull();
    expect(auditEntryText({ stage: false }, "stage")).toBeNull();
    expect(auditEntryText({ stage: " " }, "stage")).toBeNull();
  });

  test("turns an exact entry link into immutable server-side sequence bounds", () => {
    const filters = auditFiltersFromSearch(new URLSearchParams("entry=42"));
    expect(filters.fromSeq).toBe(42);
    expect(filters.throughSeq).toBe(42);
    expect(filters.invalid).toEqual([]);
  });

  test("appends only the response for the current cursor", () => {
    const current = { items: [item(2)], nextCursor: "cursor-2" };
    expect(appendAuditPage(current, "stale", { items: [item(1)], next_cursor: null })).toBe(current);
    expect(appendAuditPage(current, "cursor-2", { items: [item(1)], next_cursor: null })).toEqual({ items: [item(2), item(1)], nextCursor: null });
  });

  test("deduplicates replayed audit rows", () => {
    const current = { items: [item(2)], nextCursor: "cursor-2" };
    expect(appendAuditPage(current, "cursor-2", { items: [item(2), item(1)], next_cursor: null }).items.map((row) => row.seq)).toEqual([2, 1]);
  });

  test("distinguishes selected, off-page, absent, and invalid entry links", () => {
    const page = { items: [item(2)], nextCursor: "cursor-2" };
    expect(resolveAuditEntry(page, "2")).toEqual({ status: "selected", seq: 2 });
    expect(resolveAuditEntry(page, "1")).toEqual({ status: "pending", seq: 1 });
    expect(resolveAuditEntry({ ...page, nextCursor: null }, "1")).toEqual({
      status: "unavailable",
      seq: 1,
    });
    expect(resolveAuditEntry(page, "not-a-seq")).toEqual({
      status: "invalid",
      value: "not-a-seq",
    });
  });
});
