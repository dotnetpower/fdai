import { describe, expect, test } from "vitest";
import { PANTHEON } from "./agents.model";
import {
  decodePantheonGraph,
  decodePantheonWorkflows,
  pantheonAgentHref,
  pantheonViewFromSearch,
} from "./pantheon";

function graphPayload() {
  return {
    agents: PANTHEON.map(({ name }) => ({
      name,
      layer: "pipeline",
      reports_to: name === "Odin" ? null : "Odin",
      owns: [],
      executes: [],
      subscribes: [],
      publishes: [],
      question_domains: [],
      hot_path_llm: false,
      off_path_llm: false,
      hard_dependency: false,
    })),
    org_edges: PANTHEON.filter(({ name }) => name !== "Odin")
      .map(({ name }) => ({ from: "Odin", to: name })),
    agent_count: PANTHEON.length,
    hard_dependency_agents: [],
    hot_path_llm_agents: [],
    mermaid: "graph TD",
  };
}

function workflowPayload() {
  return {
    workflows: [{
      id: "workflow-1",
      name: "Workflow 1",
      primary_agent: "Heimdall",
      participating_agents: ["Heimdall", "Forseti"],
      trigger: "event",
      default_mode: "shadow",
      promotion_gate: "zero escapes",
    }],
    count: 1,
  };
}

describe("Pantheon view routing", () => {
  test("opens the organization chart from its direct link", () => {
    expect(pantheonViewFromSearch(new URLSearchParams("view=org"))).toBe("org");
  });

  test("defaults missing or unknown views to the directory", () => {
    expect(pantheonViewFromSearch(new URLSearchParams())).toBe("directory");
    expect(pantheonViewFromSearch(new URLSearchParams("view=unknown"))).toBe("directory");
  });

  test("opens agent focus and preserves live correlation context", () => {
    expect(pantheonAgentHref("Forseti", "correlation-1"))
      .toBe("/agents?view=org&agent=Forseti&correlation=correlation-1");
    expect(pantheonAgentHref("Forseti"))
      .toBe("/agents?view=org&agent=Forseti");
  });
});

describe("Pantheon graph contract", () => {
  test("accepts the fixed pantheon exactly once", () => {
    expect(decodePantheonGraph(graphPayload()).agent_count).toBe(15);
  });

  test("rejects count drift and duplicate agent names", () => {
    expect(() => decodePantheonGraph({ ...graphPayload(), agent_count: 14 }))
      .toThrow(/agent_count MUST match/);
    const duplicate = graphPayload();
    duplicate.agents[1] = { ...duplicate.agents[1]!, name: "Odin" };
    expect(() => decodePantheonGraph(duplicate)).toThrow(/fixed 15-agent pantheon/);
  });

  test("rejects reporting cycles and unknown parents", () => {
    const cycle = graphPayload();
    cycle.agents[1] = { ...cycle.agents[1]!, reports_to: cycle.agents[1]!.name };
    expect(() => decodePantheonGraph(cycle)).toThrow(/MUST be acyclic/);

    const unknownParent = graphPayload();
    unknownParent.agents[1] = { ...unknownParent.agents[1]!, reports_to: "UnknownAgent" };
    expect(() => decodePantheonGraph(unknownParent)).toThrow(/MUST reference known agents/);
  });

  test("requires Odin to be the only reporting root", () => {
    const multipleRoots = graphPayload();
    multipleRoots.agents[1] = { ...multipleRoots.agents[1]!, reports_to: null };
    expect(() => decodePantheonGraph(multipleRoots)).toThrow(/Odin as its only reporting root/);
  });
});

describe("Pantheon workflow contract", () => {
  test("accepts known participants and matching counts", () => {
    expect(decodePantheonWorkflows(workflowPayload()).count).toBe(1);
  });

  test("rejects count drift and duplicate workflow ids", () => {
    expect(() => decodePantheonWorkflows({ ...workflowPayload(), count: 2 }))
      .toThrow(/count MUST match/);
    const duplicate = workflowPayload();
    duplicate.workflows.push({ ...duplicate.workflows[0]! });
    duplicate.count = 2;
    expect(() => decodePantheonWorkflows(duplicate)).toThrow(/id MUST be unique/);
  });

  test("rejects unknown agents and missing primary participants", () => {
    const unknown = workflowPayload();
    unknown.workflows[0] = { ...unknown.workflows[0]!, primary_agent: "UnknownAgent" };
    expect(() => decodePantheonWorkflows(unknown)).toThrow(/primary_agent MUST be a fixed agent/);

    const missingPrimary = workflowPayload();
    missingPrimary.workflows[0] = {
      ...missingPrimary.workflows[0]!,
      participating_agents: ["Forseti"],
    };
    expect(() => decodePantheonWorkflows(missingPrimary)).toThrow(/include primary_agent/);
  });
});
