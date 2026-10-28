import { describe, expect, it } from "vitest";
import type { ActionTypePaletteEntry } from "../workflow/validate";
import { filterActionTypes, paletteCategories } from "./workflow-builder.palette";

function entry(name: string, category: string | null, description: string): ActionTypePaletteEntry {
  return {
    name,
    operation: "apply",
    category,
    rollback_contract: "pr_revert",
    irreversible: false,
    default_mode: "shadow",
    execution_path: "pr_native",
    env_scope: "any",
    hil_tiers: [],
    description,
  };
}

const PALETTE = [
  entry("remediate.right-size", "remediation", "Right-size an over-provisioned resource"),
  entry("ops.scale-out", "ops", "Scale a workload out"),
  entry("tool.publish-change-summary", "tool", "Post a change summary"),
  entry("misc.unclassified", null, "No category"),
];

describe("workflow-builder ActionType search", () => {
  it("lists distinct categories with a stable fallback", () => {
    expect(paletteCategories(PALETTE)).toEqual(["ops", "other", "remediation", "tool"]);
  });

  it("returns every entry in name order for an empty query", () => {
    expect(filterActionTypes(PALETTE, "", "").map((item) => item.name)).toEqual([
      "misc.unclassified",
      "ops.scale-out",
      "remediate.right-size",
      "tool.publish-change-summary",
    ]);
  });

  it("requires every token to appear in the name, category, or description", () => {
    expect(filterActionTypes(PALETTE, "change summary", "").map((item) => item.name)).toEqual([
      "tool.publish-change-summary",
    ]);
    expect(filterActionTypes(PALETTE, "SCALE workload", "").map((item) => item.name)).toEqual([
      "ops.scale-out",
    ]);
    expect(filterActionTypes(PALETTE, "scale summary", "")).toEqual([]);
  });

  it("narrows by category and omits actions already in the draft", () => {
    expect(filterActionTypes(PALETTE, "", "other").map((item) => item.name)).toEqual([
      "misc.unclassified",
    ]);
    expect(
      filterActionTypes(PALETTE, "", "", new Set(["ops.scale-out"])).map((item) => item.name),
    ).not.toContain("ops.scale-out");
  });
});
