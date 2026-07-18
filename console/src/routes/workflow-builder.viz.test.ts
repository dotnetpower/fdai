import { describe, expect, it } from "vitest";
import type { ActionTypePaletteEntry } from "../workflow/validate";
import { INITIAL_FORM, type FormState } from "./workflow-builder.model";
import { buildVizModel } from "./workflow-builder.viz";

function entry(name: string, category: string): ActionTypePaletteEntry {
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
    description: name,
  };
}

const PALETTE: readonly ActionTypePaletteEntry[] = [
  entry("remediate.right-size", "remediation"),
  entry("notify.publish-change-summary", "tool"),
  entry("weird.thing", "made-up-category"),
];

function form(over: Partial<FormState>): FormState {
  return { ...INITIAL_FORM, ...over, steps: over.steps ?? [] };
}

describe("workflow-builder buildVizModel", () => {
  it("starts with a when-node and ends with a done-node", () => {
    const nodes = buildVizModel(form({}), PALETTE);
    expect(nodes[0]?.kind).toBe("when");
    expect(nodes[nodes.length - 1]?.kind).toBe("done");
  });

  it("labels a tool step as 'notify' and others as 'do'", () => {
    const nodes = buildVizModel(
      form({
        steps: [
          { key: 0, id: "rs", action_type_ref: "remediate.right-size", guard_rule_ref: "", compensated_by: "", on_failure: "", params: {} },
          { key: 1, id: "note", action_type_ref: "notify.publish-change-summary", guard_rule_ref: "", compensated_by: "", on_failure: "", params: {} },
        ],
      }),
      PALETTE,
    );
    const steps = nodes.filter((n) => n.kind === "do" || n.kind === "notify");
    expect(steps.map((n) => n.kind)).toEqual(["do", "notify"]);
  });

  it("skips blank starter rows", () => {
    const nodes = buildVizModel(
      form({
        steps: [
          { key: 0, id: "", action_type_ref: "  ", guard_rule_ref: "", compensated_by: "", on_failure: "", params: {} },
          { key: 1, id: "rs", action_type_ref: "remediate.right-size", guard_rule_ref: "", compensated_by: "", on_failure: "", params: {} },
        ],
      }),
      PALETTE,
    );
    const steps = nodes.filter((n) => n.kind === "do" || n.kind === "notify");
    expect(steps).toHaveLength(1);
    expect(steps[0]?.ref).toBe("remediate.right-size");
  });

  it("folds an unknown category to 'other' so the class name is well-formed", () => {
    const nodes = buildVizModel(
      form({
        steps: [
          { key: 0, id: "w", action_type_ref: "weird.thing", guard_rule_ref: "", compensated_by: "", on_failure: "", params: {} },
        ],
      }),
      PALETTE,
    );
    const step = nodes.find((n) => n.ref === "weird.thing");
    expect(step?.category).toBe("other");
  });

  it("shows the human signal label for a known signal, machine ref beneath", () => {
    const nodes = buildVizModel(form({ triggerKind: "signal", signalType: "object.cost-anomaly" }), PALETTE);
    expect(nodes[0]?.name).toBe("Cost spike detected");
    expect(nodes[0]?.ref).toBe("object.cost-anomaly");
  });

  it("shows the cron expression for a schedule trigger", () => {
    const nodes = buildVizModel(form({ triggerKind: "schedule", schedule: "0 3 * * 0" }), PALETTE);
    expect(nodes[0]?.name).toBe("0 3 * * 0");
    expect(nodes[0]?.ref).toBe("0 3 * * 0");
  });

  it("falls back to 'an event' when a signal type is empty", () => {
    const nodes = buildVizModel(form({ triggerKind: "signal", signalType: "" }), PALETTE);
    expect(nodes[0]?.name).toBe("an event");
  });
});
