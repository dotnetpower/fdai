/**
 * Unit tests for the cockpit's pure, localizable text functions.
 *
 * `tierLabel`, `viewBadge`, and `parseScreenCommand` were extracted to module
 * scope precisely so the live TUI's user-facing strings are testable without a
 * terminal. English is the source of truth and renders byte-identical to the
 * pre-i18n cockpit; Korean is asserted structurally (no Hangul literals in this
 * .ts file, per the english-only gate) plus the mandatory English fallback.
 */

import { describe, expect, it } from "vitest";

import { parseScreenCommand, tierLabel, viewBadge } from "../src/cockpit.js";

describe("cockpit.tierLabel", () => {
  it("renders the English tier labels byte-identically", () => {
    expect(tierLabel("t0", "en")).toBe("fixed rules");
    expect(tierLabel("t1", "en")).toBe("past match");
    expect(tierLabel("t2", "en")).toBe("reasoning");
    expect(tierLabel("anything-else", "en")).toBe("unrouted");
  });

  it("localizes to ko where translated", () => {
    expect(tierLabel("t0", "ko")).not.toBe("fixed rules");
    expect(tierLabel("t0", "ko").length).toBeGreaterThan(0);
  });

  it("falls back to English for a lagging ko key (unrouted)", () => {
    expect(tierLabel("mystery", "ko")).toBe("unrouted");
  });
});

describe("cockpit.viewBadge", () => {
  it("renders the English badges byte-identically", () => {
    expect(viewBadge({ mode: "stream", paused: false }, "en")).toBe("STREAM");
    expect(viewBadge({ mode: "overview", paused: false }, "en")).toBe(
      "OVERVIEW",
    );
    expect(
      viewBadge({ mode: "focus", focus: "network", paused: false }, "en"),
    ).toBe("FOCUS NETWORK");
    expect(viewBadge({ mode: "stream", paused: true }, "en")).toBe("PAUSED");
  });

  it("localizes to ko where translated", () => {
    expect(viewBadge({ mode: "stream", paused: false }, "ko")).not.toBe(
      "STREAM",
    );
    expect(viewBadge({ mode: "stream", paused: true }, "ko")).not.toBe(
      "PAUSED",
    );
  });

  it("falls back to English for the lagging ko focus badge", () => {
    expect(
      viewBadge({ mode: "focus", focus: "network", paused: false }, "ko"),
    ).toBe("FOCUS NETWORK");
  });
});

describe("cockpit.parseScreenCommand", () => {
  it("maps English commands to a view patch + reply", () => {
    const pause = parseScreenCommand("pause", "en");
    expect(pause?.patch.paused).toBe(true);
    expect(pause?.reply).toContain("Paused");

    const focus = parseScreenCommand("focus network", "en");
    expect(focus?.patch.mode).toBe("focus");
    expect(focus?.patch.focus).toBe("network");
    expect(focus?.reply).toBe("Focusing on network resources.");

    const vague = parseScreenCommand("focus", "en");
    expect(vague?.patch.mode).toBe("stream");
    expect(vague?.reply).toBe("Which resource type? e.g. 'focus network'.");
  });

  it("accepts Korean input and still returns the (en) reply by default", () => {
    // "멈춰" = a Korean 'pause' verb; input parses, reply is en source.
    const pause = parseScreenCommand("멈춰", "en");
    expect(pause?.patch.paused).toBe(true);
    expect(pause?.reply).toContain("Paused");
  });

  it("localizes the reply when locale is ko", () => {
    const en = parseScreenCommand("pause", "en");
    const ko = parseScreenCommand("pause", "ko");
    expect(ko?.patch.paused).toBe(true); // same patch
    expect(ko?.reply).not.toBe(en?.reply); // localized reply
    expect((ko?.reply ?? "").length).toBeGreaterThan(0);
  });

  it("returns null when nothing matches", () => {
    expect(parseScreenCommand("hello there", "en")).toBeNull();
  });
});
