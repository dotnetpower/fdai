import { describe, expect, it } from "vitest";
import type { AgentNode } from "./agents.model";
import { agentViewContextRecord } from "./agents.view-model";

const selectedAgent: AgentNode = {
  name: "Var",
  layer: "approver",
  state: "approving",
  observed: true,
  correlationId: "correlation-1",
  since: "2026-09-01T00:00:00Z",
  detail: "awaiting human approval",
};

describe("agentViewContextRecord", () => {
  it("keeps temporal work and correlation evidence out of the organization context", () => {
    const record = agentViewContextRecord(selectedAgent, "org");

    expect(record).toMatchObject({
      agent: "Var",
      staff: false,
      layer: "pipeline",
      state: "approving",
    });
    expect(record).not.toHaveProperty("task");
    expect(record).not.toHaveProperty("correlation_id");
  });

  it("retains temporal work and correlation evidence in the Fleet context", () => {
    expect(agentViewContextRecord(selectedAgent, "roster")).toMatchObject({
      agent: "Var",
      task: "Awaiting human approval",
      correlation_id: "correlation-1",
    });
  });
});
