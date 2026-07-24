import { describe, expect, it } from "vitest";
import { parseInvestigationActivity } from "./backend-normalizers";

function activity(execution: Record<string, unknown>) {
  return {
    activity_id: "metrics",
    kind: "metrics.querying",
    status: "completed",
    label: "Query metrics",
    agent: "Heimdall",
    completed: 1,
    total: 1,
    execution,
  };
}

describe("parseInvestigationActivity execution evidence", () => {
  it("accepts bounded evidence attested as redacted", () => {
    const parsed = parseInvestigationActivity(activity({
      tool: "Azure CLI",
      command: "az monitor metrics list --resource <resource-id>",
      redacted: true,
      output: "{\"value\": []}",
      output_truncated: true,
      exit_code: 0,
      started_at: "2026-07-24T05:00:00Z",
      completed_at: "2026-07-24T05:00:04Z",
      duration_ms: 4000,
    }));

    expect(parsed?.execution).toEqual({
      tool: "Azure CLI",
      command: "az monitor metrics list --resource <resource-id>",
      redacted: true,
      output: "{\"value\": []}",
      outputTruncated: true,
      exitCode: 0,
      startedAt: "2026-07-24T05:00:00Z",
      completedAt: "2026-07-24T05:00:04Z",
      durationMs: 4000,
    });
    expect(parsed?.agent).toBe("Heimdall");
  });

  it("drops execution evidence without a redaction attestation", () => {
    const parsed = parseInvestigationActivity(activity({
      tool: "Azure CLI",
      command: "az account show",
      redacted: false,
    }));

    expect(parsed?.execution).toBeUndefined();
  });
});
