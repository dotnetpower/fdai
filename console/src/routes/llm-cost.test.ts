import { describe, expect, test } from "vitest";
import { decodeLlmCost, llmUsageCorrelationHref } from "./llm-cost";

const summary = {
  key: "total",
  invocations: 1,
  prompt_tokens: 10,
  completion_tokens: 5,
  total_tokens: 15,
};

describe("LLM usage provenance", () => {
  test("links conversation rollups to correlation-scoped audit evidence", () => {
    expect(llmUsageCorrelationHref("corr-1")).toBe("/audit?correlation=corr-1");
  });

  test("decodes measured chat, model, and invocation usage without cost", () => {
    const decoded = decodeLlmCost({
      source: "metering",
      latest_occurred_at: "2026-07-10T09:00:00+00:00",
      invocations: 1,
      total: summary,
      chat: summary,
      by_scope: [{ ...summary, key: "operator_chat" }],
      by_model: [{ ...summary, key: "gpt-4.1-mini" }],
      chat_by_model: [{ ...summary, key: "gpt-4.1-mini" }],
      by_mode: [],
      by_conversation: [],
      by_conversation_truncated: false,
      conversation_count: 0,
      by_day: [],
      by_month: [],
      records: [{
        occurred_at: "2026-07-10T09:00:00+00:00",
        correlation_id: "chat-1",
        capability_id: "t1.judge",
        model_key: "gpt-4.1-mini",
        tier: "T1",
        mode: "enforce",
        usage_scope: "operator_chat",
        prompt_tokens: 10,
        completion_tokens: 5,
        total_tokens: 15,
      }],
      records_truncated: false,
      record_count: 1,
    });

    expect(decoded.latest_occurred_at).toBe("2026-07-10T09:00:00+00:00");
    expect(decoded.chat.total_tokens).toBe(15);
    expect(decoded.by_model[0]?.key).toBe("gpt-4.1-mini");
    expect(decoded.records[0]?.usage_scope).toBe("operator_chat");
    expect(decoded.records[0]).not.toHaveProperty("cost");
  });
});
