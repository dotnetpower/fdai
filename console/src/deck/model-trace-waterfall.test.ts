import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

import type { ModelTrace } from "./backend";
import {
  buildModelTraceBars,
  formatModelTraceMessageGroup,
  groupModelTraceMessages,
} from "./model-trace-waterfall";

const SHA = "a".repeat(64);
const styles = readFileSync(fileURLToPath(new URL("../styles.css", import.meta.url)), "utf8");

function call(id: string, start: string, completed: string | null) {
  return {
    call_id: id,
    kind: "answer-stream",
    model: "test-model",
    status: completed ? "completed" as const : "incomplete" as const,
    started_at: start,
    completed_at: completed,
    duration_ms: completed ? Date.parse(completed) - Date.parse(start) : null,
    request: { messages: [], sha256: SHA },
    response: completed ? { role: "assistant" as const, content: "ok", sha256: SHA } : null,
    usage: null,
    redactions: [],
  };
}

describe("buildModelTraceBars", () => {
  it("positions concurrent calls on one shared question window", () => {
    const trace: ModelTrace = {
      schema_version: 1,
      redacted: true,
      omitted_calls: 0,
      calls: [
        call("second", "2026-07-31T01:00:01Z", "2026-07-31T01:00:03Z"),
        call("first", "2026-07-31T01:00:00Z", "2026-07-31T01:00:02Z"),
      ],
    };

    const bars = buildModelTraceBars(trace);

    expect(bars.map((bar) => bar.call.call_id)).toEqual(["first", "second"]);
    expect(bars[0]?.leftPct).toBe(0);
    expect(bars[0]?.widthPct).toBeGreaterThan(50);
    expect(bars[1]?.leftPct).toBeGreaterThan(25);
  });

  it("keeps an incomplete call visible as a minimum-width sliver", () => {
    const trace: ModelTrace = {
      schema_version: 1,
      redacted: true,
      omitted_calls: 0,
      calls: [call("pending", "2026-07-31T01:00:00Z", null)],
    };

    expect(buildModelTraceBars(trace)[0]?.widthPct).toBe(2.5);
  });

  it("groups consecutive system layers without changing later message roles", () => {
    const groups = groupModelTraceMessages([
      { role: "system", content: "Safety" },
      { role: "system", content: '{"status":"ready","items":[1,2]}' },
      { role: "user", content: "Question" },
      { role: "system", content: "Late system" },
    ]);

    expect(groups).toEqual([
      { role: "system", contents: ["Safety", '{"status":"ready","items":[1,2]}'] },
      { role: "user", contents: ["Question"] },
      { role: "system", contents: ["Late system"] },
    ]);
    expect(formatModelTraceMessageGroup(groups[0]!)).toEqual({
      format: "text",
      text: 'Safety\n\n{\n  "status": "ready",\n  "items": [\n    1,\n    2\n  ]\n}',
    });
  });

  it("keeps a single JSON message marked as JSON and themes overflow", () => {
    expect(formatModelTraceMessageGroup({
      role: "tool",
      contents: ['{"matched":true}'],
    })).toEqual({
      format: "json",
      text: '{\n  "matched": true\n}',
    });
    expect(styles).toContain("scrollbar-color: #68737e #101820;");
    expect(styles).toContain(".deck-model-trace-messages pre::-webkit-scrollbar-thumb,");
  });
});
