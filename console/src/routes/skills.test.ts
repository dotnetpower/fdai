import { describe, expect, test } from "vitest";
import { decodeRuntimeSkills } from "./skills";

const ITEM = {
  name: "inventory-evidence",
  version: "1.0.0",
  description: "Collect inventory evidence.",
  source: "publisher.example",
  enabled: true,
  required_tools: ["query_inventory"],
  missing_tools: [],
  allowed_agents: ["Bragi"],
  agent_eligible: true,
  eligible: true,
  eligibility_reason: "eligible_pending_trust_recheck",
  body_sha256: "a".repeat(64),
  references: [{
    path: "references/guide.txt",
    sha256: "b".repeat(64),
    size_bytes: 12,
    media_type: "text/plain",
  }],
};

function payload() {
  return {
    source: "trusted-artifact-runtime",
    execution_eligibility: false,
    trust_rechecked_on_load: true,
    agent: "Bragi",
    available_tools: ["query_inventory"],
    installed_count: 1,
    eligible_count: 1,
    skills: [ITEM],
    installed_bundle_count: 1,
    eligible_bundle_count: 1,
    bundles: [{
      name: "incident-evidence-pack",
      version: "1.0.0",
      description: "Reviewed incident evidence procedures.",
      source: "publisher.example",
      digest: "c".repeat(64),
      enabled: true,
      members: [{ name: ITEM.name, version: "==1.0.0" }],
      required_tools: ["query_inventory"],
      missing_tools: [],
      allowed_agents: ["Bragi"],
      agent_eligible: true,
      compatible: true,
      missing_members: [],
      disabled_members: [],
      incompatible_members: [],
      trust_status: "rechecked_on_load",
      eligible: true,
    }],
    diagnostics: [{
      operation: "load",
      name: ITEM.name,
      reference: null,
      status: "selected",
      reason: "skill_loaded",
      digests: { body_sha256: ITEM.body_sha256 },
    }],
    mutation_controls: false,
  };
}

describe("runtime Skills panel contract", () => {
  test("decodes metadata, dependencies, eligibility, and diagnostics", () => {
    const decoded = decodeRuntimeSkills(payload());

    expect(decoded.execution_eligibility).toBe(false);
    expect(decoded.mutation_controls).toBe(false);
    expect(decoded.skills[0]?.required_tools).toEqual(["query_inventory"]);
    expect(decoded.skills[0]?.references[0]?.path).toBe("references/guide.txt");
    expect(decoded.bundles[0]?.members[0]).toEqual({
      name: "inventory-evidence",
      version: "==1.0.0",
    });
    expect(decoded.bundles[0]?.compatible).toBe(true);
    expect(decoded.diagnostics[0]?.reason).toBe("skill_loaded");
  });

  test("rejects contradictory counts and duplicate names", () => {
    expect(() => decodeRuntimeSkills({ ...payload(), installed_count: 2 }))
      .toThrow(/installed_count MUST match/);
    expect(() => decodeRuntimeSkills({
      ...payload(),
      skills: [ITEM, ITEM],
      installed_count: 2,
      eligible_count: 2,
    }))
      .toThrow(/names MUST be unique/);
    expect(() => decodeRuntimeSkills({ ...payload(), eligible_count: 0 }))
      .toThrow(/eligible_count MUST match/);
  });
});
