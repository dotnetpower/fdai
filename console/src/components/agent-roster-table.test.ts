import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, test } from "vitest";
import { PANTHEON } from "../routes/agents.model";
import {
  AgentRosterTable,
  agentRosterTone,
  type AgentRosterTableLabels,
  type AgentRosterTableRow,
} from "./agent-roster-table";

const REPO_ROOT = fileURLToPath(new URL("../../../", import.meta.url));

const LABELS: AgentRosterTableLabels = {
  agent: "Agent",
  layer: "Layer",
  state: "State",
  currentWork: "Current work",
  activeIncident: "Active incident",
  stateSince: "Since",
  actions: "Actions",
  details: "Details",
  owns: "Owns",
  reportsTo: "Reports to",
  runtimeBinding: "Runtime binding",
  authority: "Authority",
  recentEvents: "Recent events",
};

function makeRow(name: string, observed: boolean): AgentRosterTableRow {
  return {
    name,
    layerKey: "pipeline",
    layerLabel: "Pipeline",
    roleTitle: `${name} role`,
    roleSummary: `${name} summary`,
    stateKind: observed ? "engaged" : "unobserved",
    stateLabel: observed ? "Engaged" : "Unobserved",
    observed,
    currentWork: observed ? "Evaluating policy" : "No runtime signal yet",
    activeIncident: observed ? "INC-101" : "None",
    stateSince: "12:00:00",
    reportsTo: "Odin",
    runtimeBinding: "event-bus subscriber",
    authorityLabel: "Advise",
    recentEventsCount: observed ? 4 : 0,
    owns: ["Incident"],
    flags: [],
    iconUrl: "url(/agent-icons/odin.svg)",
    activityHref: `/agent-activity?agent=${name}`,
    openRoleLabel: "Role",
    activityLabel: "Activity",
    askLabel: `Ask ${name}`,
  };
}

describe("AgentRosterTable", () => {
  test("preserves fixed 15-agent pantheon ordering and never substitutes unobserved metrics with zero", () => {
    const rows = PANTHEON.map((agent, index) => makeRow(agent.name, index === 0));
    const rendered = JSON.stringify(
      AgentRosterTable({
        ariaLabel: "Agent fleet",
        rows,
        labels: LABELS,
        onOpenRole: () => {},
        onAskAgent: () => {},
      }),
    );

    expect(rows).toHaveLength(15);
    for (const agent of PANTHEON) {
      expect(rendered).toContain(`"data-agent-name":"${agent.name}"`);
    }
    expect(rendered).toContain('"data-agent-observed":"false"');
    expect(rendered).toContain('"children":"-"');
    expect(agentRosterTone("engaged", true)).toBe("live");
    expect(agentRosterTone("watching", true)).toBe("info");
    expect(agentRosterTone("engaged", false)).toBe("neutral");
    expect(agentRosterTone("unobserved", false)).toBe("neutral");
  });

  test("enforces >= 12px typography floor and prohibits colored left/top accent bars", () => {
    const css = readFileSync(`${REPO_ROOT}console/src/components/agent-roster-table.css`, "utf8");
    const pxUnder12 = [...css.matchAll(/font-size:\s*(\d+(?:\.\d+)?)px\b/g)]
      .filter((match) => Number.parseFloat(match[1] ?? "12") < 12);
    const remUnder12 = [...css.matchAll(/font-size:\s*(\d+(?:\.\d+)?)rem\b/g)]
      .filter((match) => Number.parseFloat(match[1] ?? "0.75") < 0.75);
    expect(pxUnder12).toEqual([]);
    expect(remUnder12).toEqual([]);
    expect(css).not.toMatch(/border-(left|top):\s*[2-9]px\s+solid/);
  });
});
