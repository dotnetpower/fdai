import { describe, expect, test } from "vitest";
import { oversightViewFromSegment, viewRequiresStewardship } from "./agent-oversight-views";
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
    identity_health: {
      status: "not_configured",
      checked_at: null,
    },
  };
}

describe("Handover projection contract", () => {
  test("accepts only the five Agent oversight views", () => {
    expect(oversightViewFromSegment(undefined)).toBe("overview");
    expect(oversightViewFromSegment("human-dependencies")).toBe("human-dependencies");
    expect(oversightViewFromSegment("knowledge-handover")).toBe("knowledge-handover");
    expect(oversightViewFromSegment("approval-routes")).toBe("approval-routes");
    expect(oversightViewFromSegment("mapping-reviews")).toBe("mapping-reviews");
    expect(oversightViewFromSegment("unknown")).toBeNull();
    expect(viewRequiresStewardship("overview")).toBe(true);
    expect(viewRequiresStewardship("human-dependencies")).toBe(true);
    expect(viewRequiresStewardship("knowledge-handover")).toBe(false);
    expect(viewRequiresStewardship("approval-routes")).toBe(false);
    expect(viewRequiresStewardship("mapping-reviews")).toBe(false);
  });

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

  test("rejects bus factor that disagrees with distinct accountable subjects", () => {
    const drift = stewardshipPayload();
    drift.map.agents[0]!.bus_factor = 2;
    expect(() => decodeStewardship(drift)).toThrow(/bus_factor.*distinct accountable subjects/);
  });

  test("rejects autonomous mode layered over accountable ownership", () => {
    const contradictory = stewardshipPayload();
    contradictory.map.agents[0]!.autonomous = true;
    contradictory.map.agents[0]!.accept_autonomous_reason = "Ownership is intentionally absent." as never;
    contradictory.coverage.autonomous_agents = 1;
    expect(() => decodeStewardship(contradictory)).toThrow(/autonomy.*accountable-ownership alternative/);
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

  test("enforces v2 duty semantics while preserving v1 compatibility", () => {
    const missingDuty = stewardshipPayload();
    missingDuty.map.version = 2;
    expect(() => decodeStewardship(missingDuty)).toThrow(/v2 accountable.*declare duty/);

    const informedDuty = stewardshipPayload();
    informedDuty.map.agents[0]!.stewards[0] = {
      kind: "user",
      id: "informed-user",
      responsibility: "informed",
      duty: "backup",
    } as never;
    informedDuty.map.agents[0]!.bus_factor = 0;
    informedDuty.map.agents[0]!.autonomous = true;
    informedDuty.map.agents[0]!.accept_autonomous_reason = "Ownership is intentionally absent." as never;
    informedDuty.coverage.autonomous_agents = 1;
    expect(() => decodeStewardship(informedDuty)).toThrow(/informed.*MUST NOT declare duty/);
  });

  test("rejects identity health that is not backed by completed check evidence", () => {
    const invalidTimestamp = stewardshipPayload();
    invalidTimestamp.identity_health = {
      status: "clean",
      checked_at: "not-a-timestamp",
      finding_count: 0,
    } as never;
    expect(() => decodeStewardship(invalidTimestamp)).toThrow(/identity_health.*completed check evidence/);

    const mismatchedCount = stewardshipPayload();
    mismatchedCount.identity_health = {
      status: "warn",
      checked_at: "2026-08-05T00:00:00Z",
      finding_count: 1,
    } as never;
    expect(() => decodeStewardship(mismatchedCount)).toThrow(/identity_health.*completed check evidence/);
  });
});
