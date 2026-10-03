import { afterEach, describe, expect, it } from "vitest";
import { setLocale } from "../i18n";
import type { TurnBudgetTelemetry } from "./backend-types";
import { plannedWorkText, turnBudgetParts, turnBudgetText } from "./investigation-roles";

const BUDGET: TurnBudgetTelemetry = {
  schema_version: 1,
  model_calls: { used: 3, reserved: 0, maximum: 5 },
  tokens: { used: 4382, reserved: 0, maximum: 48000 },
  elapsed_ms: { used: 3136, reserved: 0, maximum: 60000 },
  as_of: "2026-09-28T10:41:06.296Z",
  complete: true,
};

afterEach(() => setLocale("en"));

describe("investigation roles", () => {
  it("names the pinned plan's waves and reads", () => {
    setLocale("en");
    expect(plannedWorkText({ schema_version: 1, density: "procedural", waves: 2, planned_reads: 7 }))
      .toBe("Planned: 2 waves, 7 reads");
    expect(plannedWorkText({ schema_version: 1, density: "compact", waves: 1, planned_reads: 1 }))
      .toBe("Planned: 1 wave, 1 read");
    setLocale("ko");
    expect(plannedWorkText({ schema_version: 1, density: "procedural", waves: 2, planned_reads: 7 }))
      .toBe("계획: 웨이브 2개, 조회 7건");
  });

  it("states the settled budget as used-of-maximum facts", () => {
    setLocale("en");
    expect(turnBudgetText(BUDGET)).toBe("Used: 3 of 5 model calls, 4.4k of 48k tokens, 3.1 s of 60 s");
    setLocale("ko");
    expect(turnBudgetText(BUDGET)).toBe("사용량: 모델 호출 3/5회, 토큰 4.4k/48k, 시간 3.1 s/60 s");
  });

  it("names the limit that ended the turn and an incomplete measurement", () => {
    setLocale("en");
    expect(turnBudgetText({
      ...BUDGET,
      elapsed_ms: { used: 60820, reserved: 0, maximum: 60000 },
      exhaustion_reason: "deadline",
    })).toBe("Turn deadline reached: 3 of 5 model calls, 4.4k of 48k tokens, 60.8 s of 60 s");
    // Charged but unmeasured tokens stay reserved, so the measurement is incomplete.
    expect(turnBudgetText({
      ...BUDGET,
      tokens: { used: 900, reserved: 2000, maximum: 48000 },
      complete: false,
    })).toBe("Used: 3 of 5 model calls, 900 plus 2k reserved of 48k tokens, 3.1 s of 60 s, measurement incomplete");
  });

  it("splits the facts around their measures so each measure stays on one line", () => {
    setLocale("en");
    expect(turnBudgetParts({ ...BUDGET, complete: false })).toEqual({
      lead: "Used: ",
      measures: ["3 of 5 model calls", "4.4k of 48k tokens", "3.1 s of 60 s"],
      trail: ", measurement incomplete",
    });
    setLocale("ko");
    expect(turnBudgetParts({
      ...BUDGET,
      elapsed_ms: { used: 60820, reserved: 0, maximum: 60000 },
      exhaustion_reason: "deadline",
    })).toEqual({
      lead: "턴 기한 도달: ",
      measures: ["모델 호출 3/5회", "토큰 4.4k/48k", "시간 60.8 s/60 s"],
      trail: "",
    });
  });
});
