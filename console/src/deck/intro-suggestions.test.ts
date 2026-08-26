import { describe, expect, it } from "vitest";
import { introSuggestions } from "./intro-suggestions";
import type { ViewFact, ViewSnapshot } from "./context";

function snap(facts: ViewFact[]): ViewSnapshot {
  return {
    routeId: "live",
    routeLabel: "Live cockpit",
    headline: "test",
    facts,
    capturedAt: "2026-07-10T00:00:00Z",
  };
}

describe("introSuggestions", () => {
  it("offers route discovery when there is no snapshot", () => {
    expect(introSuggestions(null)).toEqual(["What routes are available?"]);
  });

  it("falls back to evergreen prompts when nothing notable is on screen", () => {
    const s = introSuggestions(snap([{ key: "eps", value: 4 }]));
    expect(s).toEqual([
      "What do you see on this screen?",
      "What is the tier mix right now?",
    ]);
  });

  it("surfaces failed actions first when present", () => {
    const s = introSuggestions(snap([{ key: "attention.failed", value: 3 }]));
    expect(s[0]).toBe("Why did the failed actions fail?");
  });

  it("surfaces approvals from either attention.hil or gate.hil", () => {
    expect(introSuggestions(snap([{ key: "gate.hil", value: 2 }]))).toContain(
      "What is waiting for approval?",
    );
    expect(introSuggestions(snap([{ key: "attention.hil", value: 1 }]))).toContain(
      "What is waiting for approval?",
    );
  });

  it("caps to five suggestions and de-duplicates", () => {
    const s = introSuggestions(
      snap([
        { key: "attention.failed", value: 1 },
        { key: "attention.hil", value: 1 },
        { key: "gate.hil", value: 1 },
        { key: "gate.deny", value: 1 },
        { key: "attention.stuck", value: 1 },
      ]),
    );
    expect(s.length).toBe(5);
    expect(new Set(s).size).toBe(5);
    // Situational prompts win the cap over the trailing evergreen ones.
    expect(s).toContain("Why did the failed actions fail?");
    expect(s).toContain("Which actions are stuck?");
  });

  it("treats numeric strings as counts and ignores zero", () => {
    expect(introSuggestions(snap([{ key: "attention.failed", value: "0" }]))).not.toContain(
      "Why did the failed actions fail?",
    );
    expect(introSuggestions(snap([{ key: "attention.failed", value: "2" }]))).toContain(
      "Why did the failed actions fail?",
    );
  });

  it("localizes starter questions for Korean operators", () => {
    expect(introSuggestions(snap([{ key: "eps", value: 4 }]), "ko")).toEqual([
      "이 화면에서 무엇을 확인할 수 있나요?",
      "현재 신뢰 티어 구성은 어떤가요?",
    ]);
  });
});
