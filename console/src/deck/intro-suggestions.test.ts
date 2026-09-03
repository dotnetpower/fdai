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
  it("offers only contract-backed questions when there is no snapshot", () => {
    expect(introSuggestions(null)).toEqual([
      "Show resources that are currently not running.",
      "Show current service-health advisories for the authorized subscription.",
    ]);
  });

  it("offers contract-backed questions when nothing notable is on screen", () => {
    const s = introSuggestions(snap([{ key: "eps", value: 4 }]));
    expect(s).toEqual([
      "Show resources that are currently not running.",
      "Show current service-health advisories for the authorized subscription.",
    ]);
  });

  it("does not expose unimplemented situational questions", () => {
    const s = introSuggestions(snap([{ key: "attention.failed", value: 3 }]));
    expect(s).not.toContain("Why did the failed actions fail?");
  });

  it("localizes starter questions for Korean operators", () => {
    expect(introSuggestions(snap([{ key: "eps", value: 4 }]), "ko")).toEqual([
      "현재 실행 중이 아닌 리소스를 보여줘.",
      "권한이 있는 구독의 현재 서비스 상태 권고를 보여줘.",
    ]);
  });
});
