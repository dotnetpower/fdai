import { describe, expect, it } from "vitest";

import { parseModelTrace } from "./backend";

const SHA = "a".repeat(64);

function trace() {
  return {
    schema_version: 1,
    redacted: true,
    omitted_calls: 0,
    calls: [{
      call_id: "model-call-1",
      kind: "answer-stream",
      model: "test-model",
      status: "completed",
      started_at: "2026-07-31T01:00:00Z",
      completed_at: "2026-07-31T01:00:01Z",
      duration_ms: 1000,
      request: {
        messages: [
          { role: "system", content: "system" },
          { role: "user", content: "question" },
        ],
        sha256: SHA,
      },
      response: { role: "assistant", content: "answer", sha256: SHA },
      usage: { prompt_tokens: 10, completion_tokens: 2, total_tokens: 12 },
      redactions: [{ rule: "url", replacements: 1 }],
    }],
  };
}

describe("parseModelTrace", () => {
  it("accepts one bounded redacted provider trace", () => {
    expect(parseModelTrace(trace())).toEqual(trace());
  });

  it.each([
    { schema_version: 2 },
    { redacted: false },
    { calls: Array(9).fill(trace().calls[0]) },
    { calls: [{ ...trace().calls[0], completed_at: "2026-07-31T00:59:59Z" }] },
    { calls: [{ ...trace().calls[0], status: "incomplete" }] },
    { calls: [{ ...trace().calls[0], request: { ...trace().calls[0]!.request, sha256: "bad" } }] },
    { calls: [{ ...trace().calls[0], response: { ...trace().calls[0]!.response, role: "tool" } }] },
  ])("rejects malformed or internally inconsistent traces", (override) => {
    expect(parseModelTrace({ ...trace(), ...override })).toBeUndefined();
  });

  it("accepts an unfinished call only without completion fields or response", () => {
    const unfinished = {
      ...trace().calls[0],
      status: "incomplete",
      completed_at: null,
      duration_ms: null,
      response: null,
      usage: null,
    };

    expect(parseModelTrace({ ...trace(), calls: [unfinished] })?.calls[0]?.status)
      .toBe("incomplete");
  });
});
