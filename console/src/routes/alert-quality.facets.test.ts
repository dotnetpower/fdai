import { describe, expect, it } from "vitest";
import fixture from "./alert-quality.backend.fixture.json";
import { ALERT_UNKNOWN_FACET, filterAlertFindings } from "./alert-quality.facets";
import { decodeAlertQuality } from "./alert-quality.model";

const scope = fixture.assessment.scope_ref;
const base = decodeAlertQuality(fixture, scope).assessment!.findings[0]!;
const filters = { rule: null, service: "", team: "", audience: "" };
const decode = (fields: Record<string, unknown>) => decodeAlertQuality({ ...fixture,
  assessment: { ...fixture.assessment, findings: [{ ...base, ...fields }] } }, scope).assessment!.findings[0]!;

describe("source-backed alert display facets", () => {
  it("rejects conflicting team or audience identity for one rule", () => {
    const known = decode({ team_refs: ["team:example"], audience_kinds: ["group"] });
    for (const change of [{ team_refs: null }, { audience_kinds: ["role"] }]) {
      expect(() => decodeAlertQuality({ ...fixture, assessment: { ...fixture.assessment,
        findings: [known, { ...known, ...change }] } }, scope)).toThrow(/facet identity/);
    }
  });

  it("preserves source team/kind sets and never aliases a service into a team", () => {
    const row = decode({ team_refs: ["team:example"], audience_kinds: ["group", "role"] });
    expect(filterAlertFindings([row], { ...filters, team: "team:example", audience: "role" })).toEqual([row]);
    expect(filterAlertFindings([row], { ...filters, team: row.service_ref })).toEqual([]);
    expect(row.team_refs).toEqual(["team:example"]);
  });

  it("distinguishes missing sources from an explicitly empty destination set", () => {
    const unknown = decode({ team_refs: null, audience_kinds: null });
    const empty = decode({ team_refs: ["team:example"], audience_kinds: [] });
    const original = [unknown, empty];
    expect(filterAlertFindings(original, { ...filters, audience: ALERT_UNKNOWN_FACET })).toEqual([unknown]);
    expect(filterAlertFindings(original, filters)).toEqual(original);
    expect(filterAlertFindings([base], { ...filters, team: ALERT_UNKNOWN_FACET })).toEqual([base]);
    expect(original).toEqual([unknown, empty]);
    expect(fixture.assessment.source_episodes).toBe(3);
  });

  it.each([
    { team_refs: [] }, { team_refs: ["team:b", "team:a"] }, { team_refs: ["team:a", "team:a"] },
    { team_refs: [" team:a"] }, { team_refs: undefined }, { team_refs: [false] },
    { audience_kinds: ["email"] }, { audience_kinds: ["role", "group"] },
    { audience_kinds: ["role", "role"] }, { audience_kinds: undefined },
  ])("rejects malformed or noncanonical facets %j", (fields) => {
    expect(() => decode(fields)).toThrow();
  });
});
