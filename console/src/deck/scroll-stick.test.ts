import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import {
  completedWorkRevealTarget,
  FOLLOW_BOTTOM_PX,
  followAfterScroll,
  followStepScrollTop,
  followTargetScrollTop,
  isNearBottom,
  jumpToLatestVisible,
  type FollowState,
} from "./scroll-stick";

const following = (mode: FollowState["mode"], expected = 0): FollowState => ({
  following: true,
  mode,
  expected,
});

describe("isNearBottom", () => {
  it("counts a fully scrolled, nearly scrolled, or non-overflowing transcript as at the bottom", () => {
    expect(isNearBottom(900, 1000, 100)).toBe(true);
    expect(isNearBottom(1000 - 100 - FOLLOW_BOTTOM_PX, 1000, 100)).toBe(true);
    expect(isNearBottom(0, 100, 100)).toBe(true);
  });

  it("is false once the reader is further than the threshold from the bottom", () => {
    expect(isNearBottom(500, 1000, 100)).toBe(false);
    expect(isNearBottom(700, 1000, 100, 150)).toBe(false);
    expect(isNearBottom(700, 1000, 100, 250)).toBe(true);
  });
});

describe("question pin", () => {
  const geometry = { maxScrollTop: 2000, clientHeight: 600, pinTop: 800, revealBottom: null };

  it("follows new content until the question being answered reaches the top edge", () => {
    expect(followTargetScrollTop("pin", { ...geometry, maxScrollTop: 500 })).toBe(500);
    expect(followTargetScrollTop("pin", geometry)).toBe(788);
  });

  it("never scrolls back over text the reader may be reading", () => {
    expect(followStepScrollTop(following("pin", 788), 788, 788)).toBeNull();
    expect(followStepScrollTop(following("pin", 900), 900, 788)).toBeNull();
    expect(followStepScrollTop(following("pin", 400), 400, 788)).toBe(788);
  });

  it("reveals the settled turn's verification row below the pinned question", () => {
    expect(followTargetScrollTop("pin", { ...geometry, revealBottom: 1500 })).toBe(916);
    // A verification row already in view keeps the question pinned.
    expect(followTargetScrollTop("pin", { ...geometry, revealBottom: 1100 })).toBe(788);
    // The reveal never asks for more than the transcript can scroll.
    expect(followTargetScrollTop("pin", { ...geometry, maxScrollTop: 850, revealBottom: 1500 })).toBe(850);
  });
});

describe("bottom follow", () => {
  it("follows the newest content when nothing is pinned or the reader returned to the bottom", () => {
    const geometry = { maxScrollTop: 1400, clientHeight: 600, pinTop: 300, revealBottom: null };
    expect(followTargetScrollTop("bottom", geometry)).toBe(1400);
    expect(followTargetScrollTop("pin", { ...geometry, pinTop: null })).toBe(1400);
    expect(followTargetScrollTop("bottom", { ...geometry, maxScrollTop: -20 })).toBe(0);
  });

  it("switches a reader who scrolls onto the bottom to bottom follow", () => {
    const next = followAfterScroll({ following: false, mode: "pin", expected: 300 }, 1400, 788, true);
    expect(next).toEqual({ following: true, mode: "bottom", expected: 1400 });
  });
});

describe("reader-scrolled stop", () => {
  it("keeps following through the follower's own moves and clamps on its course", () => {
    const state = following("pin", 600);
    expect(followAfterScroll(state, 600.5, 788, false)).toBe(state);
    expect(followAfterScroll(state, 700, 788, false)).toEqual(following("pin", 700));
  });

  it("stops following when the reader moves the view anywhere else", () => {
    expect(followAfterScroll(following("pin", 788), 200, 788, false)).toEqual({
      following: false,
      mode: "pin",
      expected: 200,
    });
    expect(followAfterScroll(following("bottom", 1400), 1000, 1400, false).following).toBe(false);
    expect(followStepScrollTop({ following: false, mode: "pin", expected: 200 }, 200, 788)).toBeNull();
  });
});

describe("jump to latest", () => {
  it("appears only when real content sits below the visible edge", () => {
    expect(jumpToLatestVisible(400, 380)).toBe(true);
    // Blank padding below the newest turn is not newer content.
    expect(jumpToLatestVisible(400, 0)).toBe(false);
    expect(jumpToLatestVisible(FOLLOW_BOTTOM_PX, 380)).toBe(false);
  });
});

describe("completedWorkRevealTarget", () => {
  it("reveals the settled reply's verification row", () => {
    expect(completedWorkRevealTarget("deck-answer")).toEqual({
      turnId: "deck-answer",
      childSelector: ".deck-gr-actions",
    });
  });
});

describe("transcript follow wiring", () => {
  const hook = readFileSync(
    fileURLToPath(new URL("./use-command-deck-transcript.ts", import.meta.url)),
    "utf8",
  );
  const submit = readFileSync(
    fileURLToPath(new URL("./use-command-deck-submit.ts", import.meta.url)),
    "utf8",
  );

  it("follows layout growth and classifies every scroll", () => {
    expect(hook).toContain("new ResizeObserver(() => scheduleFollow())");
    expect(hook).toContain("if (!open) return");
    expect(hook).toContain("observer.observe(content)");
    expect(hook).toContain("followAfterScroll(");
    expect(hook).toContain("jumpToLatestVisible(");
  });

  it("pins each new question and reveals the verification row only after the terminal update", () => {
    const question = submit.indexOf("followQuestion(operatorTurn.id);");
    const answerStart = submit.indexOf("scheduleStreamPaint();\n        followLatestContent();");
    const terminalReveal = submit.indexOf("completedWorkRevealTarget(deckId)", answerStart + 1);

    expect(question).toBeGreaterThan(-1);
    expect(answerStart).toBeGreaterThan(question);
    expect(terminalReveal).toBeGreaterThan(answerStart);
  });
});
