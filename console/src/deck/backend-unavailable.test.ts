import { describe, expect, it } from "vitest";

import { SEMANTIC_UNAVAILABLE_TEXT, semanticUnavailable } from "./backend-unavailable";

describe("semanticUnavailable", () => {
  it.each([
    ["offline", "FDAI could not reach the conversation service. No answer was produced."],
    [
      "model not configured",
      "No conversation model is configured for this environment. No answer was produced.",
    ],
    [
      "blocked by content policy",
      "FDAI did not answer because the request was blocked by content policy. Remove sensitive data or instruction-override content before asking again.",
    ],
    [
      "backend 401",
      "The conversation request was not authorized. Sign in again before asking.",
    ],
    [
      "backend 429",
      "The conversation provider is rate limited. No answer was produced.",
    ],
    [
      "typed evidence hold missing canonical answer",
      "FDAI held the answer because the required evidence or canonical response was incomplete.",
    ],
    [
      "terminal canonical answer mismatch",
      "FDAI rejected an inconsistent conversation response. No answer was accepted.",
    ],
    [
      "missing terminal verification",
      "FDAI received no complete verified answer. No answer was accepted.",
    ],
    [
      "upstream returned empty completion",
      "FDAI received no complete verified answer. No answer was accepted.",
    ],
    ["unclassified", SEMANTIC_UNAVAILABLE_TEXT],
  ])("renders a bounded explanation for %s", (reason, expected) => {
    expect(semanticUnavailable(reason)).toEqual({
      text: expected,
      citations: [],
      followUps: [],
      source: `unavailable (${reason})`,
    });
  });
});
