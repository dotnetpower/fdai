import { describe, expect, it } from "vitest";

import {
  backendTooltip,
  hasOverflowingText,
  routerTooltip,
} from "./command-deck-presenters";

describe("conversation title overflow", () => {
  it("enables the full-title tooltip only when the rendered text is truncated", () => {
    expect(hasOverflowingText({ clientWidth: 120, scrollWidth: 121 })).toBe(true);
    expect(hasOverflowingText({ clientWidth: 120, scrollWidth: 120 })).toBe(false);
    expect(hasOverflowingText({ clientWidth: 120, scrollWidth: 80 })).toBe(false);
  });
});

describe("backend connection tooltip", () => {
  const router = {
    chose: "narrator-fast",
    reason: "latency",
    candidates: [
      {
        deployment: "narrator-fast",
        p50_ms: 1149.4,
        p95_ms: 1390.2,
        samples: 2,
        history_ms: [1149.4, 1390.2],
      },
      {
        deployment: "narrator-safe",
        p50_ms: 5507.2,
        p95_ms: 6086.1,
        samples: 2,
        history_ms: [5507.2, 6086.1],
      },
    ],
  } as const;

  it("puts the route decision and each candidate on distinct lines", () => {
    expect(routerTooltip(router)?.split("\n")).toEqual([
      "auto-router (latency) chose narrator-fast",
      "* narrator-fast · p50 1149ms · p95 1390ms · n=2",
      "  narrator-safe · p50 5507ms · p95 6086ms · n=2",
    ]);
  });

  it("fills endpoint and candidate placeholders without leaking template tokens", () => {
    const content = backendTooltip({
      available: true,
      mode: "azure-ad-routed",
      model: "narrator-fast",
      endpoint: "https://chat.example.com",
      router,
    });

    expect(content.split("\n")).toHaveLength(4);
    expect(content).toContain("chat mode azure-ad-routed · https://chat.example.com");
    expect(content).not.toMatch(/\{(?:endpoint|candidates)\}/);
  });

  it("omits empty reason parentheses without inventing a reason", () => {
    const content = routerTooltip({ ...router, reason: "" });

    expect(content).toContain("auto-router chose narrator-fast");
    expect(content).not.toContain("()");
  });
});
