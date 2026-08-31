import { describe, expect, test } from "vitest";
import { OperatorApiError } from "../api";
import {
  buildGithubNewFileUrl,
  hasActionTypeRef,
  hasEquivalentWorkflowBinding,
  humanizeName,
  loadPythonTaskAvailability,
  requestedActionType,
  loadWorkflowDefinitions,
  suggestDraftFromJudgment,
  suggestDraftFromText,
  suggestStepId,
  workflowSelection,
  workflowStepHref,
} from "./workflow-builder";
import type { ActionTypePaletteEntry } from "../workflow/validate";
import type { WorkflowBindingEntry } from "../workflow/validate";
import { buildDraft, catalogToForm } from "./workflow-builder.helpers";

describe("workflow catalog wire tolerance", () => {
  test("preserves step parameters through catalog clone and draft assembly", () => {
    const workflow = {
      schema_version: "1.0.0",
      name: "parameterized-workflow",
      version: "1.0.0",
      trigger: { kind: "signal", signal_type: "object.event" },
      default_mode: "shadow",
      promotion_gate: {
        min_shadow_days: 14,
        min_samples: 100,
        min_accuracy: 0.95,
        max_policy_escapes: 0,
      },
      steps: [{
        id: "notify",
        action_type_ref: "notify.publish-change-summary",
        params: { channel: "operations", retries: 2, urgent: false },
      }],
      step_count: 1,
      yaml: "",
    } as const;

    const draft = buildDraft(catalogToForm(workflow));
    expect(draft["steps"]).toEqual([{
      id: "notify",
      kind: "action",
      action_type_ref: "notify.publish-change-summary",
      params: { channel: "operations", retries: 2, urgent: false },
    }]);
  });

  test("preserves WAIT and APPROVAL fields through catalog clone and draft assembly", () => {
    const workflow = {
      schema_version: "1.0.0",
      name: "governed-review",
      version: "1.0.0",
      trigger: { kind: "signal", signal_type: "review.requested" },
      default_mode: "shadow",
      promotion_gate: {
        min_shadow_days: 14,
        min_samples: 100,
        min_accuracy: 0.95,
        max_policy_escapes: 0,
      },
      steps: [
        {
          id: "wait_for_evidence",
          kind: "wait",
          wait_for: "evidence.updated",
          timeout_seconds: 3600,
        },
        {
          id: "human_approval",
          kind: "approval",
          approval_role: "approver",
          timeout_seconds: 1800,
          quorum: 2,
          no_self_approval: true,
        },
      ],
      step_count: 2,
      yaml: "",
    } as const;

    expect(buildDraft(catalogToForm(workflow))["steps"]).toEqual([
      {
        id: "wait_for_evidence",
        kind: "wait",
        wait_for: "evidence.updated",
        timeout_seconds: 3600,
      },
      {
        id: "human_approval",
        kind: "approval",
        approval_role: "approver",
        timeout_seconds: 1800,
        quorum: 2,
        no_self_approval: true,
      },
    ]);
  });

  test("keeps built-in browsing available when principal definitions are unwired", async () => {
    const definitions = await loadWorkflowDefinitions({
      panel: async () => { throw new OperatorApiError(404, "Not Found"); },
    } as never);
    expect(definitions).toEqual({
      groups: { built_in: [], shared: [], mine: [] },
      bindings: [],
      counts: { built_in: 0, shared: 0, mine: 0 },
    });
  });

  test("keeps workflow browsing available when Python tasks are unwired", async () => {
    const availability = await loadPythonTaskAvailability({
      panel: async () => { throw new OperatorApiError(404, "Not Found"); },
    } as never);
    expect(availability).toBeNull();
  });

  test("keeps the ownership group in step drilldowns", () => {
    expect(workflowStepHref("shared", "shared-check", "verify/1")).toBe(
      "/workflow-builder?group=shared&workflow=shared-check&step=verify%2F1",
    );
  });

  test("preserves an explicit unknown workflow instead of substituting the default", () => {
    const workflows = [
      { name: "default-workflow", steps: [{ id: "restart", action_type_ref: "compute.restart" }] },
      { name: "other-workflow", steps: [] },
    ];
    expect(workflowSelection(workflows, "missing-workflow", null)).toBe("missing-workflow");
    expect(workflowSelection(workflows, null, null)).toBe("default-workflow");
    expect(workflowSelection(workflows, null, "compute.restart")).toBe("default-workflow");
    expect(workflowSelection(workflows, null, "missing.action")).toBeNull();
  });

  test("tolerates metadata-only live steps with a null action_type_ref", () => {
    expect(hasActionTypeRef({ action_type_ref: null })).toBe(false);
    expect(hasActionTypeRef({ action_type_ref: "" })).toBe(false);
    expect(hasActionTypeRef({ action_type_ref: "compute.restart" })).toBe(true);
  });

  test("resolves an action deep link from the authoritative palette", () => {
    const action: ActionTypePaletteEntry = {
      name: "remediate.restrict-network-access",
      operation: "update",
      category: "remediation",
      rollback_contract: "pr_revert",
      irreversible: false,
      default_mode: "shadow",
      execution_path: "gitops_pr",
      env_scope: "all",
      hil_tiers: ["t2"],
      description: "Restrict network access.",
    };
    expect(requestedActionType([action], action.name)).toBe(action);
    expect(requestedActionType([action], "unknown.action")).toBeNull();
  });
});

describe("workflow binding equivalence", () => {
  const binding: WorkflowBindingEntry = {
    binding_id: "binding-1",
    definition_id: "definition-1",
    trigger: "schedule",
    enabled: false,
    cron_expression: "0 7 * * *",
    timezone: "Asia/Seoul",
    signal_type: null,
    scope_ref: null,
    parameters: {},
    revision: 1,
  };

  test("matches the backend duplicate-binding rule", () => {
    expect(hasEquivalentWorkflowBinding(
      [binding],
      "definition-1",
      "schedule",
      " 0 7 * * * ",
      " Asia/Seoul ",
      "unused",
    )).toBe(true);
  });

  test("allows a distinct trigger configuration", () => {
    expect(hasEquivalentWorkflowBinding(
      [binding],
      "definition-1",
      "signal",
      "0 7 * * *",
      "Asia/Seoul",
      "object.event",
    )).toBe(false);
  });
});

/**
 * These tests pin the two pure helpers the Phase-A builder UX relies on:
 *
 * - `humanizeName` renders a dotted workflow id as a readable template-card
 *   title, and
 * - `suggestStepId` derives a valid, unique snake_case step id from an
 *   ActionType ref so the operator never has to invent one by hand.
 */

describe("humanizeName", () => {
  test("dotted / dashed id becomes a capitalized phrase", () => {
    expect(humanizeName("cost-aware-remediation")).toBe("Cost aware remediation");
    expect(humanizeName("dr.failover.drill")).toBe("Dr failover drill");
    expect(humanizeName("predictive_scale")).toBe("Predictive scale");
  });

  test("single token is capitalized", () => {
    expect(humanizeName("scale")).toBe("Scale");
  });
});

describe("suggestStepId", () => {
  test("uses the leaf after the last separator, snake_cased", () => {
    expect(suggestStepId("remediate.right-size", [])).toBe("right_size");
    expect(suggestStepId("ops.scale-out", [])).toBe("scale_out");
    expect(suggestStepId("tool.generate-pdf", [])).toBe("generate_pdf");
  });

  test("de-duplicates against ids already used in the draft", () => {
    expect(suggestStepId("remediate.right-size", ["right_size"])).toBe("right_size_2");
    expect(suggestStepId("remediate.right-size", ["right_size", "right_size_2"])).toBe(
      "right_size_3",
    );
  });

  test("falls back to a safe id when the ref has no alphanumerics", () => {
    expect(suggestStepId("...", [])).toBe("step");
  });
});

function at(name: string, category: string, description = ""): ActionTypePaletteEntry {
  return {
    name,
    operation: "update",
    category,
    rollback_contract: "pr_revert",
    irreversible: false,
    default_mode: "shadow",
    execution_path: null,
    env_scope: "any",
    hil_tiers: [],
    description,
  };
}

const PALETTE: readonly ActionTypePaletteEntry[] = [
  at("remediate.right-size", "remediation", "Adjust compute count to match utilization"),
  at("ops.scale-out", "ops", "Add capacity"),
  at("ops.restart-service", "ops", "Restart a service"),
  at("remediate.enable-encryption", "remediation", "Turn on encryption at rest"),
  at("remediate.disable-public-access", "remediation", "Remove public network exposure"),
  at("ops.publish-change-summary", "ops", "Publish a change summary"),
  at("ops.failover-primary", "ops", "Fail over the primary"),
];

describe("workflow semantic judgment", () => {
  test("projects exact trigger and ActionType identities", () => {
    const s = suggestDraftFromJudgment({
      primary_intent: "workflow_draft",
      trigger: { kind: "signal", signal_type: "object.cost-anomaly" },
      action_type_refs: ["remediate.right-size", "ops.publish-change-summary"],
      confidence: 0.95,
      ambiguous: false,
      execution_authority: false,
    }, PALETTE);
    expect(s).not.toBeNull();
    expect(s!.form.triggerKind).toBe("signal");
    expect(s!.form.signalType).toBe("object.cost-anomaly");
    const actions = s!.form.steps.map((st) => st.action_type_ref);
    expect(actions).toContain("remediate.right-size");
    expect(actions).toContain("ops.publish-change-summary");
    expect(s!.form.steps.every((st) => st.id.length > 0)).toBe(true);
  });

  test("projects a verified schedule", () => {
    const s = suggestDraftFromJudgment({
      primary_intent: "workflow_draft",
      trigger: { kind: "schedule", schedule: "0 3 * * 0" },
      action_type_refs: ["ops.failover-primary"],
      confidence: 0.9,
      ambiguous: false,
      execution_authority: false,
    }, PALETTE);
    expect(s).not.toBeNull();
    expect(s!.form.triggerKind).toBe("schedule");
    expect(s!.form.schedule).toBe("0 3 * * 0");
    expect(s!.form.steps.map((st) => st.action_type_ref)).toContain("ops.failover-primary");
  });

  test("text-only browser calls abstain", () => {
    expect(suggestDraftFromText("qwer zxcv hjkl", PALETTE)).toBeNull();
    expect(suggestDraftFromText("When cost spikes, right-size the VM", PALETTE)).toBeNull();
  });

  test("caps the suggested steps at three", () => {
    const s = suggestDraftFromJudgment({
      primary_intent: "workflow_draft",
      trigger: { kind: "signal", signal_type: "object.anomaly" },
      action_type_refs: PALETTE.slice(0, 4).map((entry) => entry.name),
      confidence: 0.95,
      ambiguous: false,
      execution_authority: false,
    }, PALETTE);
    expect(s).not.toBeNull();
    expect(s!.form.steps.length).toBeLessThanOrEqual(3);
    expect(s!.actionMatchesTruncated).toBe(true);
  });

  test("ambiguous or unknown machine identities fail closed", () => {
    const base = {
      primary_intent: "workflow_draft" as const,
      trigger: { kind: "signal" as const, signal_type: "object.anomaly" },
      confidence: 0.95,
      execution_authority: false as const,
    };
    expect(suggestDraftFromJudgment({ ...base, action_type_refs: [], ambiguous: true }, PALETTE)).toBeNull();
    expect(suggestDraftFromJudgment({ ...base, action_type_refs: ["unknown.action"], ambiguous: false }, PALETTE)).toBeNull();
  });

  test("suggested step ids are unique within the draft", () => {
    const s = suggestDraftFromJudgment({
      primary_intent: "workflow_draft",
      trigger: { kind: "signal", signal_type: "object.capacity-forecast" },
      action_type_refs: ["remediate.right-size", "ops.scale-out", "ops.restart-service"],
      confidence: 0.95,
      ambiguous: false,
      execution_authority: false,
    }, PALETTE);
    const ids = s!.form.steps.map((st) => st.id);
    expect(new Set(ids).size).toBe(ids.length);
  });
});

describe("buildGithubNewFileUrl", () => {
  test("returns null when the repo is not owner/repo", () => {
    expect(buildGithubNewFileUrl("", "main", "p.yaml", "x")).toBeNull();
    expect(buildGithubNewFileUrl("not-a-repo", "main", "p.yaml", "x")).toBeNull();
    expect(buildGithubNewFileUrl("a/b/c", "main", "p.yaml", "x")).toBeNull();
  });

  test("builds a new-file URL with url-encoded filename + content", () => {
    const url = buildGithubNewFileUrl(
      "acme/fdai",
      "main",
      "rule-catalog/workflows/x.yaml",
      "name: x\n",
    );
    expect(url).not.toBeNull();
    expect(url!.startsWith("https://github.com/acme/fdai/new/main?")).toBe(true);
    expect(url).toContain("filename=rule-catalog%2Fworkflows%2Fx.yaml");
    expect(url).toContain("value=name%3A+x%0A");
  });

  test("defaults an empty branch to main", () => {
    const url = buildGithubNewFileUrl("acme/fdai", "", "x.yaml", "x");
    expect(url!).toContain("/new/main?");
  });

  test("returns null when the URL would exceed the safe length ceiling", () => {
    const huge = "a".repeat(8000);
    expect(buildGithubNewFileUrl("acme/fdai", "main", "x.yaml", huge)).toBeNull();
  });
});
