import { afterEach, describe, expect, it } from "vitest";
import { setLocale } from "../i18n";
import type { InvestigationActivity } from "./backend-types";
import { modelCallDetail, modelCallLabel } from "./model-call-text";

function call(overrides: Partial<InvestigationActivity> = {}): InvestigationActivity {
  return {
    activityId: "semantic:model:1",
    kind: "model_call",
    status: "running",
    label: "개념 선택 모델 호출",
    detail: "narrator-mini 응답 대기 중",
    completed: null,
    total: null,
    modelCall: { stage: "concept_chooser", model: "narrator-mini", durationMs: 2300 },
    ...overrides,
  };
}

describe("model call text", () => {
  afterEach(() => setLocale("en"));

  it("follows the Console language, not the language of the server text", () => {
    setLocale("en");
    expect(modelCallLabel(call())).toBe("Concept selection model call");
    expect(modelCallDetail(call())).toBe("waiting for narrator-mini");
    expect(modelCallDetail(call({ status: "completed" }))).toBe("narrator-mini · 2.3 s · completed");

    setLocale("ko");
    expect(modelCallLabel(call())).toBe("개념 선택 모델 호출");
    expect(modelCallDetail(call({ status: "failed" }))).toBe("narrator-mini · 2.3 s · 실패");
  });

  it("keeps the server text for a row without closed codes", () => {
    const { modelCall: _closedCodes, ...rest } = call();
    const plain: InvestigationActivity = { ...rest, label: "Server label", detail: "Server detail" };

    expect(modelCallLabel(plain)).toBe("Server label");
    expect(modelCallDetail(plain)).toBe("Server detail");
  });
});
