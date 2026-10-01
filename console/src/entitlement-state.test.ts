import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, test, vi } from "vitest";

import {
  EntitlementStampStore,
  FIRST_STAMP_WAIT_MS,
  parseEntitlementNotice,
  STAMP_STALE_MS,
  watermarkNotice,
} from "./entitlement-state";

const SOURCE_ROOT = join(process.cwd(), "src");

function source(path: string): string {
  return readFileSync(join(SOURCE_ROOT, path), "utf8");
}

function imports(path: string): string[] {
  return [...source(path).matchAll(/^import[^;]*?from\s+"([^"]+)";/gms)]
    .map((match) => match[1] ?? "")
    .sort();
}

describe("watermark off switches", () => {
  test("the decision and the component read no setting, preference, or configuration", () => {
    expect(imports("entitlement-state.ts")).toEqual([]);
    expect(imports("components/entitlement-watermark.tsx")).toEqual([
      "../entitlement-state",
      "../i18n",
      "preact",
      "preact/hooks",
    ]);
  });

  test("the shell mounts the watermark and every transport fetch records the stamp", () => {
    const transport = source("api-transport.ts");
    const fetches = transport.match(/await fetch\(/g) ?? [];
    const records = transport.match(
      /this\.#entitlementStamps\.record\(response\.headers\.get\(ENTITLEMENT_HEADER\)\)/g,
    ) ?? [];

    expect(fetches.length).toBeGreaterThan(0);
    expect(records).toHaveLength(fetches.length);
    expect(source("app.tsx")).toMatch(
      /<EntitlementWatermark probe=\{\(\) => client\.dataSources\(\)\} \/>/,
    );
  });
});

describe("entitlement notice parsing", () => {
  test.each([
    ["none", "none"],
    [" evaluation-ended ", "evaluation-ended"],
    ["not-activated", "not-activated"],
    ["", "not-activated"],
    ["NONE", "not-activated"],
    ["active", "not-activated"],
  ])("maps %j onto the closed vocabulary as %s", (value, expected) => {
    expect(parseEntitlementNotice(value)).toBe(expected);
  });
});

describe("watermark decision", () => {
  const startedAt = 1_000;

  test("waits for the first stamp, then shows a missing stamp as not activated", () => {
    expect(watermarkNotice(null, { startedAt, now: startedAt + FIRST_STAMP_WAIT_MS - 1 }))
      .toBeNull();
    expect(watermarkNotice(null, { startedAt, now: startedAt + FIRST_STAMP_WAIT_MS }))
      .toBe("not-activated");
  });

  test("hides only for a recent none stamp", () => {
    const stamp = { notice: "none", receivedAt: startedAt } as const;

    expect(watermarkNotice(stamp, { startedAt, now: startedAt + STAMP_STALE_MS })).toBeNull();
    expect(watermarkNotice(stamp, { startedAt, now: startedAt + STAMP_STALE_MS + 1 }))
      .toBe("not-activated");
  });

  test.each(["evaluation-ended", "not-activated"] as const)(
    "shows the %s stamp immediately",
    (notice) => {
      expect(watermarkNotice({ notice, receivedAt: startedAt }, { startedAt, now: startedAt }))
        .toBe(notice);
    },
  );

  test("shows a stale ended evaluation as not activated", () => {
    expect(watermarkNotice(
      { notice: "evaluation-ended", receivedAt: startedAt },
      { startedAt, now: startedAt + STAMP_STALE_MS + 1 },
    )).toBe("not-activated");
  });
});

describe("entitlement stamp store", () => {
  test("records the latest stamp with its monotonic receipt time", () => {
    let now = 5;
    const store = new EntitlementStampStore(() => now);

    store.record("none");
    now = 9;
    store.record("evaluation-ended");

    expect(store.latest()).toEqual({ notice: "evaluation-ended", receivedAt: 9 });
  });

  test("keeps the previous stamp when a response carries no header", () => {
    const store = new EntitlementStampStore(() => 3);
    const listener = vi.fn();
    store.subscribe(listener);

    store.record(null);
    expect(store.latest()).toBeNull();
    store.record("none");
    store.record(null);

    expect(store.latest()).toEqual({ notice: "none", receivedAt: 3 });
    expect(listener).toHaveBeenCalledOnce();
  });

  test("stops notifying after unsubscribe", () => {
    const store = new EntitlementStampStore(() => 0);
    const listener = vi.fn();
    const unsubscribe = store.subscribe(listener);

    store.record("not-activated");
    unsubscribe();
    store.record("none");

    expect(listener).toHaveBeenCalledOnce();
  });
});
