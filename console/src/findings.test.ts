import { afterEach, describe, expect, test, vi } from "vitest";
import type { OperatorApiClient } from "./api";
import {
  decodeFindingPage, findingBrowserAlert, findingWasSeen, findingNeedsAttention,
  loadCurrentFindings, markFindingPending, rememberFinding,
} from "./findings";

const row = (id = "a".repeat(64), version = 1) => ({
  finding_id: id, notification_version: version, notification_reason: "opened",
  notification_changed_at: "2026-09-01T00:00:00Z",
  resource_ref: "resource:example", resource_kind: "virtual_machine",
  signal: "host_cpu", severity: "high", status: "active",
  observation: "CPU is high", occurred_at: "2026-09-01T00:00:00Z",
  evidence_complete: true, evidence_state: "complete", evidence_gaps: [], evidence_refs: ["metric:sample"],
  execution_authority: false, cause_claim_supported: false,
});
const page = (items: readonly unknown[] = [row()], next_cursor: string | null = null, total_count = items.length) =>
  ({ source: "runtime-observed", items, next_cursor, total_count });

afterEach(() => vi.unstubAllGlobals());

describe("authoritative Finding feed", () => {
  test("reads every page and preserves simultaneous signals on one resource", async () => {
    const panel = vi.fn<OperatorApiClient["panel"]>()
      .mockResolvedValueOnce(page([row()], "a".repeat(64), 2))
      .mockResolvedValueOnce(page([{ ...row("b".repeat(64)), signal: "resource_availability" }], null, 2));
    const results = await loadCurrentFindings({ panel });
    expect(results).toHaveLength(2);
    expect(panel).toHaveBeenLastCalledWith("/findings", { limit: "200", cursor: "a".repeat(64) });
  });

  test.each([
    { ...page(), source: "sample" },
    { ...page(), total_count: -1 },
    page([{ ...row(), execution_authority: true }]),
    page([{ ...row(), finding_id: "../escape" }]),
    page([{ ...row(), notification_version: 0 }]),
    page([{ ...row(), evidence_complete: "true" }]),
  ])("rejects malformed or synthetic evidence", (value) => {
    expect(() => decodeFindingPage(value)).toThrow();
  });

  test("never turns a missing page into an empty success", async () => {
    const panel = vi.fn<OperatorApiClient["panel"]>().mockResolvedValue(page([], null, 2));
    await expect(loadCurrentFindings({ panel })).rejects.toThrow("incomplete");
  });

  test("detects repeated cursors instead of silently truncating", async () => {
    const panel = vi.fn<OperatorApiClient["panel"]>().mockResolvedValue(page([row()], "a".repeat(64), 2));
    await expect(loadCurrentFindings({ panel })).rejects.toThrow(/Duplicate|progress/);
  });

  test("uses stable notification identity, not a poll or minute identity", () => {
    const first = decodeFindingPage(page()).items[0]!;
    const second = decodeFindingPage(page([{ ...row(), occurred_at: "2026-09-01T00:01:00Z" }])).items[0]!;
    expect(findingBrowserAlert(first)).toEqual(findingBrowserAlert(second));
    expect(findingBrowserAlert(first).path).toContain(`finding=${first.finding_id}`);
  });

  test("deduplicates across reloads while isolating principals and revisions", () => {
    const values = new Map<string, string>();
    vi.stubGlobal("localStorage", {
      getItem: (key: string) => values.get(key) ?? null,
      setItem: (key: string, value: string) => values.set(key, value),
    });
    const first = decodeFindingPage(page()).items[0]!;
    const updated = decodeFindingPage(page([row("a".repeat(64), 2)])).items[0]!;
    expect(findingWasSeen(first, "one")).toBe(false);
    rememberFinding(first, "one");
    expect(findingWasSeen(first, "one")).toBe(true);
    expect(findingWasSeen(first, "two")).toBe(false);
    expect(findingWasSeen(updated, "one")).toBe(false);
  });

  test("keeps a rate-limited fault eligible when recovery arrives before display", () => {
    const values = new Map<string, string>();
    vi.stubGlobal("localStorage", {
      getItem: (key: string) => values.get(key) ?? null,
      setItem: (key: string, value: string) => values.set(key, value),
    });
    const fault = decodeFindingPage(page()).items[0]!;
    const recovery = decodeFindingPage(page([{
      ...row("a".repeat(64), 2), status: "resolved", notification_reason: "recovered",
    }])).items[0]!;
    expect(findingNeedsAttention(recovery, "one")).toBe(false);
    markFindingPending(fault, "one");
    expect(findingNeedsAttention(recovery, "one")).toBe(true);
    markFindingPending(recovery, "one");
    expect(findingNeedsAttention(fault, "one")).toBe(false);
    rememberFinding(recovery, "one");
    rememberFinding(fault, "one");
    expect(findingWasSeen(recovery, "one")).toBe(true);
  });
});
