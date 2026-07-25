import { describe, expect, it } from "vitest";
import { tokenSuffix } from "./backend-normalizers";

describe("tokenSuffix", () => {
  it("formats nonnegative total and component token usage", () => {
    expect(tokenSuffix({ total_tokens: 0 })).toBe(" · 0 tok");
    expect(tokenSuffix({ prompt_tokens: 800, completion_tokens: 250 })).toBe(" · 1.1k tok");
  });

  it.each([
    { total_tokens: -1 },
    { prompt_tokens: 100, completion_tokens: -150 },
    { prompt_tokens: 100, completion_tokens: -50 },
    { prompt_tokens: -1, completion_tokens: 10 },
  ])("hides invalid negative token telemetry: %o", (usage) => {
    expect(tokenSuffix(usage)).toBe("");
  });
});
