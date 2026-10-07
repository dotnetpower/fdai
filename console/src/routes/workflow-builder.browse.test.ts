import { afterEach, describe, expect, it } from "vitest";
import { setLocale } from "../i18n";
import type { ActionTypePaletteEntry, WorkflowCatalogEntry } from "../workflow/validate";
import {
  describeSchedule,
  EMPTY_BROWSE_FILTER,
  filterWorkflows,
  isFiveFieldCron,
  triggerSummary,
  workflowApprovalFacts,
  workflowCategories,
  workflowStepKinds,
} from "./workflow-builder.browse";

afterEach(() => setLocale("en"));

function action(name: string, category: string, hil: readonly string[] = []): ActionTypePaletteEntry {
  return {
    name,
    operation: "apply",
    category,
    rollback_contract: "state_forward_only",
    irreversible: false,
    default_mode: "shadow",
    execution_path: "direct_api",
    env_scope: "any",
    hil_tiers: [...hil],
    description: name,
  };
}

function workflow(
  name: string,
  steps: WorkflowCatalogEntry["steps"],
  trigger: WorkflowCatalogEntry["trigger"] = { kind: "signal", signal_type: "release.ready" },
): WorkflowCatalogEntry {
  return {
    schema_version: "1.0.0",
    name,
    version: "1.0.0",
    description: `${name} description`,
    trigger,
    default_mode: "shadow",
    promotion_gate: { min_shadow_days: 14, min_samples: 30, min_accuracy: 0.95, max_policy_escapes: 0 },
    steps,
    step_count: steps.length,
    yaml: "",
  };
}

const PALETTE = [
  action("ops.tune-alert-evaluation", "ops", ["T0", "T1", "T2"]),
  action("tool.request-release", "tool", ["T2"]),
  action("remediate.right-size", "remediation"),
];

const ALERT = workflow("alert-evaluation-change", [
  { id: "approve_plan", kind: "approval", approval_role: "owner" },
  { id: "tune_evaluation", kind: "action", action_type_ref: "ops.tune-alert-evaluation" },
]);
const RELEASE = workflow("deployment-release-request", [
  { id: "request_release", kind: "action", action_type_ref: "tool.request-release" },
]);
const REVIEW = workflow("architecture-review", [
  { id: "domain_reviews", kind: "parallel", branches: ["security", "cost"] },
  { id: "design_decision", kind: "decision", outcomes: ["approved", "rejected"] },
], { kind: "schedule", schedule: "0 3 * * 0" });

describe("workflow-builder browse model", () => {
  it("counts authored approval steps separately from HIL-gated ActionTypes", () => {
    expect(workflowApprovalFacts(ALERT, PALETTE)).toEqual({ approvalSteps: 1, hilGatedActions: 1 });
    expect(workflowApprovalFacts(RELEASE, PALETTE)).toEqual({ approvalSteps: 0, hilGatedActions: 1 });
    expect(workflowApprovalFacts(REVIEW, PALETTE)).toEqual({ approvalSteps: 0, hilGatedActions: 0 });
  });

  it("derives category and step-kind filter options from the catalog", () => {
    expect(workflowCategories([ALERT, RELEASE, REVIEW], PALETTE)).toEqual(["ops", "tool"]);
    expect(workflowStepKinds([ALERT, RELEASE, REVIEW])).toEqual([
      "action",
      "approval",
      "decision",
      "parallel",
    ]);
  });

  it("filters by text tokens, ActionType category, and step kind", () => {
    const all = [ALERT, RELEASE, REVIEW];
    const names = (filter: Partial<typeof EMPTY_BROWSE_FILTER>) =>
      filterWorkflows(all, { ...EMPTY_BROWSE_FILTER, ...filter }, PALETTE).map((item) => item.name);
    expect(names({})).toEqual(["alert-evaluation-change", "deployment-release-request", "architecture-review"]);
    expect(names({ text: "tune-alert" })).toEqual(["alert-evaluation-change"]);
    expect(names({ text: "request_release description" })).toEqual(["deployment-release-request"]);
    expect(names({ category: "tool" })).toEqual(["deployment-release-request"]);
    expect(names({ stepKind: "approval" })).toEqual(["alert-evaluation-change"]);
    expect(names({ stepKind: "parallel", category: "ops" })).toEqual([]);
  });

  it("describes common cron shapes and declines to guess others", () => {
    expect(describeSchedule("0 * * * *")).toBe("Every hour at :00 (UTC)");
    expect(describeSchedule("0 2 * * *")).toBe("Every day at 02:00 (UTC)");
    expect(describeSchedule("0 3 * * 0")).toBe("Every Sunday at 03:00 (UTC)");
    expect(describeSchedule("30 6 * * 1", "Asia/Seoul")).toBe("Every Monday at 06:30 (Asia/Seoul)");
    expect(describeSchedule("0 3 1 * *")).toBe("Day 1 of every month at 03:00 (UTC)");
    expect(describeSchedule("*/5 * * * *")).toBeNull();
    expect(describeSchedule("0 3 * 1 *")).toBeNull();
    expect(describeSchedule("not a cron")).toBeNull();
    setLocale("ko");
    expect(describeSchedule("0 3 * * 0")).toBe("매주 일요일 03:00 (UTC)");
  });

  it("summarizes triggers with the readable schedule or the signal type", () => {
    expect(triggerSummary(REVIEW.trigger)).toBe("Every Sunday at 03:00 (UTC)");
    expect(triggerSummary({ kind: "schedule", schedule: "*/5 * * * *" })).toBe("*/5 * * * *");
    expect(triggerSummary(RELEASE.trigger)).toBe("release.ready");
  });

  it("checks the five-field cron shape before a binding save", () => {
    expect(isFiveFieldCron("0 7 * * *")).toBe(true);
    expect(isFiveFieldCron("*/15 0-6 1,15 * 1-5")).toBe(true);
    expect(isFiveFieldCron("0 7 * *")).toBe(false);
    expect(isFiveFieldCron("0 7 * * MON")).toBe(false);
  });
});
