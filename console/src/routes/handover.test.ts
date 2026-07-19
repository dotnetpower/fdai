import { describe, expect, test } from "vitest";
import { PANTHEON } from "./agents.model";
import { decodeStewardship } from "./handover";

function stewardshipPayload() {
  return {
    map: {
      version: 1,
      maintainers: ["maintainer-1"],
      maintainer_count: 1,
      hop_timeout_seconds: 900,
      over_assigned_max: 5,
      agents: PANTHEON.map(({ name }) => ({
        name,
        autonomous: false,
        accept_autonomous_reason: null,
        bus_factor: 1,
        stewards: [{ kind: "user", id: `${name}-steward`, responsibility: "accountable" }],
      })),
    },
    coverage: {
      is_clean: true,
      total_agents: 15,
      autonomous_agents: 0,
      maintainer_count: 1,
      findings: [] as Array<{
        code: string;
        severity: string;
        message: string;
        agent: string | null;
      }>,
    },
  };
}

describe("Handover projection contract", () => {
  test("accepts a count-consistent fixed pantheon map", () => {
    expect(decodeStewardship(stewardshipPayload()).map.agents).toHaveLength(15);
  });

  test("rejects duplicate agent names and maintainer count drift", () => {
    const duplicate = stewardshipPayload();
    duplicate.map.agents[1] = { ...duplicate.map.agents[1]!, name: "Odin" };
    expect(() => decodeStewardship(duplicate)).toThrow(/fixed 15-agent pantheon/);

    const maintainerDrift = stewardshipPayload();
    maintainerDrift.map.maintainer_count = 2;
    expect(() => decodeStewardship(maintainerDrift)).toThrow(/maintainer_count MUST match/);
  });

  test("rejects coverage counts that disagree with the map", () => {
    const drift = stewardshipPayload();
    drift.coverage.autonomous_agents = 1;
    expect(() => decodeStewardship(drift)).toThrow(/coverage counts MUST match/);
  });

  test("rejects unknown steward and finding enum values", () => {
    const invalidKind = stewardshipPayload();
    invalidKind.map.agents[0]!.stewards[0]!.kind = "service";
    expect(() => decodeStewardship(invalidKind)).toThrow(/kind MUST be one of user, group/);

    const invalidResponsibility = stewardshipPayload();
    invalidResponsibility.map.agents[0]!.stewards[0]!.responsibility = "owner";
    expect(() => decodeStewardship(invalidResponsibility))
      .toThrow(/responsibility MUST be one of accountable, informed/);

    const invalidSeverity = stewardshipPayload();
    invalidSeverity.coverage.findings.push({
      code: "unexpected",
      severity: "critical",
      message: "unexpected severity",
      agent: null,
    });
    expect(() => decodeStewardship(invalidSeverity)).toThrow(/severity MUST be one of warn, info/);
  });
});
