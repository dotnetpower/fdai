import { describe, expect, it } from "vitest";

import {
  backendTooltip,
  backendTooltipView,
  conversationCountLabel,
  hasOverflowingText,
  routerTooltip,
  shouldLoadMoreConversations,
} from "./command-deck-presenters";

describe("conversation history paging", () => {
  it("shows a bounded count while more cursor pages exist", () => {
    expect(conversationCountLabel(100, true)).toBe("100+");
    expect(conversationCountLabel(200, true)).toBe("100+");
    expect(conversationCountLabel(200, false)).toBe("100+");
    expect(conversationCountLabel(73, false)).toBe("73");
  });

  it("loads the next page near the scroll boundary only when available", () => {
    const nearBottom = { clientHeight: 400, scrollHeight: 1000, scrollTop: 500 };
    const farFromBottom = { clientHeight: 400, scrollHeight: 1000, scrollTop: 300 };
    expect(shouldLoadMoreConversations(nearBottom, true)).toBe(true);
    expect(shouldLoadMoreConversations(farFromBottom, true)).toBe(false);
    expect(shouldLoadMoreConversations(nearBottom, false)).toBe(false);
  });
});

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
    const health = {
      available: true,
      mode: "azure-ad-routed",
      model: "narrator-fast",
      endpoint: "https://chat.example.com",
      router,
    } as const;
    const content = backendTooltip(health);

    expect(content.split("\n")).toHaveLength(4);
    expect(content).toContain("chat mode azure-ad-routed · https://chat.example.com");
    expect(content).not.toMatch(/\{(?:endpoint|candidates)\}/);
    expect(backendTooltipView(health)).toEqual({
      mode: "azure-ad-routed",
      endpoint: "https://chat.example.com",
      router: {
        deployment: "narrator-fast",
        reason: "latency",
        candidates: [
          { deployment: "narrator-fast", p50: "1149ms", p95: "1390ms", samples: 2, selected: true },
          { deployment: "narrator-safe", p50: "5507ms", p95: "6086ms", samples: 2, selected: false },
        ],
      },
    });
  });

  it("shows an independently measured vision router", () => {
    const health = {
      available: true,
      mode: "azure-ad-routed",
      model: "narrator-fast",
      endpoint: "https://chat.example.com",
      router: {
        ...router,
        vision: {
          available: true,
          chose: "vision-fast",
          candidates: [{
            deployment: "vision-fast",
            p50_ms: 900,
            p95_ms: 1100,
            samples: 3,
            history_ms: [800, 900, 1100],
          }],
        },
      },
    } as const;

    expect(backendTooltipView(health).visionRouter).toEqual({
      deployment: "vision-fast",
      candidates: [{
        deployment: "vision-fast",
        p50: "900ms",
        p95: "1100ms",
        samples: 3,
        selected: true,
      }],
    });
  });

  it("omits empty reason parentheses without inventing a reason", () => {
    const content = routerTooltip({ ...router, reason: "" });

    expect(content).toContain("auto-router chose narrator-fast");
    expect(content).not.toContain("()");
  });
});
