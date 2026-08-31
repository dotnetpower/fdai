import { describe, expect, it } from "vitest";
import { emptyStep } from "./workflow-builder.helpers";
import { INITIAL_FORM, type FormState } from "./workflow-builder.model";
import {
  validateDraftStructure,
  workflowGateRefs,
} from "./workflow-builder.structure";

function form(steps: FormState["steps"]): FormState {
  return { ...INITIAL_FORM, steps };
}

describe("workflow builder structural validation", () => {
  it("derives reviewed gate references from the workflow catalog", () => {
    expect(workflowGateRefs([
      {
        steps: [
          { id: "gate", kind: "gate", gate_ref: "release.production-ready" },
          { id: "other", kind: "decision", outcomes: ["ready", "held"] },
        ],
      },
      {
        steps: [
          { id: "same", kind: "gate", gate_ref: "release.production-ready" },
          { id: "change", kind: "gate", gate_ref: "change-window.active" },
        ],
      },
    ])).toEqual(["change-window.active", "release.production-ready"]);
  });

  it("accepts valid decision, parallel, gate, and later failure targets", () => {
    const issues = validateDraftStructure(form([
      {
        ...emptyStep(0),
        id: "choose",
        kind: "decision",
        outcomes: ["approved", "held"],
        on_failure: "evidence_gate",
      },
      {
        ...emptyStep(1),
        id: "fan_out",
        kind: "parallel",
        branches: ["security", "reliability"],
      },
      {
        ...emptyStep(2),
        id: "evidence_gate",
        kind: "gate",
        gate_ref: "release.production-ready",
      },
    ]), ["release.production-ready"]);

    expect(issues).toEqual([]);
  });

  it.each([
    {
      name: "unknown failure target",
      step: { ...emptyStep(0), id: "choose", kind: "decision" as const, outcomes: ["yes", "no"], on_failure: "missing" },
      issue: "unknown failure target",
    },
    {
      name: "backward cycle",
      steps: [
        { ...emptyStep(0), id: "first", kind: "gate" as const, gate_ref: "known.gate" },
        { ...emptyStep(1), id: "choose", kind: "decision" as const, outcomes: ["yes", "no"], on_failure: "first" },
      ],
      issue: "prevent a cycle",
    },
    {
      name: "duplicate decision outcome",
      step: { ...emptyStep(0), id: "choose", kind: "decision" as const, outcomes: ["yes", "yes"] },
      issue: "must be unique",
    },
    {
      name: "invalid parallel join input",
      step: { ...emptyStep(0), id: "fan_out", kind: "parallel" as const, branches: ["security"] },
      issue: "requires at least 2",
    },
    {
      name: "missing gate evidence",
      step: { ...emptyStep(0), id: "gate", kind: "gate" as const },
      issue: "requires a reviewed evidence gate",
    },
    {
      name: "unsupported gate reference",
      step: { ...emptyStep(0), id: "gate", kind: "gate" as const, gate_ref: "unknown.gate" },
      issue: "not present in the workflow catalog",
    },
  ])("rejects $name", ({ step, steps, issue }) => {
    const draftSteps = steps ?? [step!];
    expect(validateDraftStructure(form(draftSteps), ["known.gate"])).toEqual(
      expect.arrayContaining([expect.objectContaining({ message: expect.stringContaining(issue) })]),
    );
  });
});
