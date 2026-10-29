import { describe, expect, it } from "vitest";
import {
  decodeConsoleInbox, loadConsoleInbox, markInboxSeen, unseenInboxItems,
} from "./console-inbox";

function row(index: number, overrides: Record<string, unknown> = {}) {
  return {
    inbox_id: index.toString(16).padStart(32, "0"),
    category: "operational_alert",
    severity: "error",
    title: `Alert ${index}`,
    body: "Bounded body.",
    correlation_id: `correlation-${index}`,
    recorded_at: `2026-10-29T00:00:0${index}Z`,
    execution_authority: false,
    ...overrides,
  };
}

const page = (items: unknown[]) => ({
  source: "runtime-observed", total_count: items.length, items, execution_authority: false,
});

describe("Console inbox decoding", () => {
  it("decodes a bounded authoritative page", () => {
    const items = decodeConsoleInbox(page([row(1), row(2)]));

    expect(items.map((item) => item.title)).toEqual(["Alert 1", "Alert 2"]);
  });

  it.each([
    ["authority", row(1, { execution_authority: true })],
    ["severity", row(1, { severity: "verbose" })],
    ["identity", row(1, { inbox_id: "not-an-id" })],
    ["time", row(1, { recorded_at: "yesterday" })],
    ["title", row(1, { title: " " })],
  ])("rejects an invalid %s", (_label, bad) => {
    expect(() => decodeConsoleInbox(page([bad]))).toThrow();
  });

  it("rejects duplicates and non-authoritative pages", () => {
    expect(() => decodeConsoleInbox(page([row(1), row(1)]))).toThrow();
    expect(() => decodeConsoleInbox({ ...page([]), source: "sample" })).toThrow();
  });

  it("reads the Operator inbox route with a bounded limit", async () => {
    const calls: Array<[string, Record<string, string> | undefined]> = [];
    const items = await loadConsoleInbox({
      panel: async (path, params) => { calls.push([path, params]); return page([row(1)]); },
    });

    expect(calls).toEqual([["/notifications/inbox", { limit: "100" }]]);
    expect(items).toHaveLength(1);
  });
});

describe("Console inbox unread marker", () => {
  function memory() {
    const values = new Map<string, string>();
    return {
      getItem: (name: string) => values.get(name) ?? null,
      setItem: (name: string, value: string) => { values.set(name, value); },
    };
  }

  it("counts only alerts newer than the last seen one", () => {
    const storage = memory();
    const items = decodeConsoleInbox(page([row(1), row(2), row(3)]));

    expect(unseenInboxItems(items, storage)).toHaveLength(3);
    markInboxSeen(items.slice(0, 2), storage);
    expect(unseenInboxItems(items, storage).map((item) => item.title)).toEqual(["Alert 3"]);
  });

  it("treats an unavailable store as nothing seen", () => {
    const items = decodeConsoleInbox(page([row(1)]));
    const broken = { getItem: () => { throw new Error("denied"); }, setItem: () => { throw new Error("denied"); } };

    expect(unseenInboxItems(items, broken)).toHaveLength(1);
    expect(() => markInboxSeen(items, broken)).not.toThrow();
  });
});
