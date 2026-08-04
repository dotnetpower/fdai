import { describe, expect, test } from "vitest";
import {
  decodeLlmCost,
  invocationCsv,
  llmUsageCorrelationHref,
  tokenShare,
  usageTrendPoints,
} from "./llm-cost";

const summary = {
  key: "total",
  invocations: 1,
  prompt_tokens: 10,
  completion_tokens: 5,
  total_tokens: 15,
};

describe("LLM usage provenance", () => {
  test("exports bounded invocation fields and neutralizes spreadsheet formulas", () => {
    const csv = invocationCsv([{
      occurred_at: "2026-08-04T00:00:00Z",
      correlation_id: "=HYPERLINK(\"https://example.com\")",
      capability_id: "query_inventory",
      model_key: "model,one",
      tier: "T1",
      mode: "shadow",
      usage_scope: "operator_chat",
      prompt_tokens: 10,
      completion_tokens: 5,
      total_tokens: 15,
    }]);

    expect(csv).toContain('"\'=HYPERLINK(""https://example.com"")"');
    expect(csv).toContain('"model,one"');
    expect(csv.split("\r\n")).toHaveLength(3);
  });

  test("neutralizes formula triggers hidden behind whitespace or a BOM", () => {
    const base = {
      occurred_at: "2026-08-04T00:00:00Z",
      capability_id: "query_inventory",
      model_key: "model-one",
      tier: "T1",
      mode: "shadow",
      usage_scope: "operator_chat",
      prompt_tokens: 10,
      completion_tokens: 5,
      total_tokens: 15,
    } as const;

    expect(invocationCsv([{ ...base, correlation_id: "  =1+1" }]))
      .toContain('"\'  =1+1"');
    expect(invocationCsv([{ ...base, correlation_id: "\uFEFF@SUM(1,1)" }]))
      .toContain('"\'\uFEFF@SUM(1,1)"');
  });

  test("links conversation rollups to correlation-scoped audit evidence", () => {
    expect(llmUsageCorrelationHref("corr-1")).toBe("/audit?correlation=corr-1");
  });

  test("decodes measured usage without exposing cost", () => {
    const decoded = decodeLlmCost({
      source: "metering",
      range_start: "2026-07-04T00:00:00+00:00",
      range_end: "2026-07-11T00:00:00+00:00",
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
      by_hour: [],
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
    expect(decoded.range_start).toBe("2026-07-04T00:00:00+00:00");
    expect(decoded.chat.total_tokens).toBe(15);
    expect(decoded.by_model[0]?.key).toBe("gpt-4.1-mini");
    expect(decoded.total).not.toHaveProperty("cost");
    expect(decoded.records[0]?.usage_scope).toBe("operator_chat");
    expect(decoded.records[0]).not.toHaveProperty("cost");
  });

  test("derives presentation ratios and trends only from measured tokens", () => {
    expect(tokenShare(25, 100)).toBe(0.25);
    expect(tokenShare(0, 0)).toBeNull();
    expect(usageTrendPoints([
      { ...summary, key: "2026-07-22", total_tokens: 10 },
      { ...summary, key: "2026-07-23", total_tokens: 20 },
    ])).toBe("0.0,34.0 100.0,4.0");
    expect(usageTrendPoints([{ ...summary, key: "2026-07-23" }])).toBeNull();
  });
});
