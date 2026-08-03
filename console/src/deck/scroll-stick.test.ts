import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import {
  completedWorkRevealTarget,
  isNearBottom,
  revealTargetScrollTop,
  STICK_THRESHOLD_PX,
} from "./scroll-stick";

describe("isNearBottom", () => {
  it("is true when fully scrolled to the bottom", () => {
    // scrollTop == scrollHeight - clientHeight
    expect(isNearBottom(900, 1000, 100)).toBe(true);
  });

  it("is true within the threshold of the bottom", () => {
    // distance = 1000 - 100 - 830 = 70 <= 80
    expect(isNearBottom(830, 1000, 100)).toBe(true);
  });

  it("is false when scrolled up beyond the threshold", () => {
    // distance = 1000 - 100 - 500 = 400 > 80
    expect(isNearBottom(500, 1000, 100)).toBe(false);
  });

  it("is true for a container that does not overflow", () => {
    // distance = 100 - 100 - 0 = 0
    expect(isNearBottom(0, 100, 100)).toBe(true);
  });

  it("respects a custom threshold", () => {
    // distance = 1000 - 100 - 700 = 200
    expect(isNearBottom(700, 1000, 100, 150)).toBe(false);
    expect(isNearBottom(700, 1000, 100, 250)).toBe(true);
  });

  it("tolerates sub-pixel rounding at the exact boundary", () => {
    const scrollTop = 1000 - 100 - STICK_THRESHOLD_PX; // distance == threshold
    expect(isNearBottom(scrollTop, 1000, 100)).toBe(true);
  });
});

describe("revealTargetScrollTop", () => {
  it("aligns observed work below the transcript edge without scrolling negative", () => {
    expect(revealTargetScrollTop(500, 100, 260)).toBe(648);
    expect(revealTargetScrollTop(0, 100, 80)).toBe(0);
  });

  it("anchors observed work only after the terminal answer update", () => {
    const submit = readFileSync(
      fileURLToPath(new URL("./use-command-deck-submit.ts", import.meta.url)),
      "utf8",
    );
    const answerStart = submit.indexOf("scheduleStreamPaint();\n        pinTranscriptToLatest();");
    const terminalUpdate = submit.indexOf("const firstActivityTurnId", answerStart + 1);

    expect(answerStart).toBeGreaterThan(-1);
    expect(terminalUpdate).toBeGreaterThan(answerStart);
  });
});

describe("completedWorkRevealTarget", () => {
  it("reveals incident choices instead of anchoring the investigation start", () => {
    expect(completedWorkRevealTarget("deck-answer", "activity-start", true)).toEqual({
      turnId: "deck-answer",
      childSelector: ".deck-incident-candidates",
    });
  });

  it("preserves the investigation anchor for ordinary replies", () => {
    expect(completedWorkRevealTarget("deck-answer", "activity-start", false)).toEqual({
      turnId: "activity-start",
    });
  });
});
