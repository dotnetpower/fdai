/**
 * Workflow-builder browse model - pure presentation helpers for the published
 * catalog review: filtering, truthful summary facts, and readable triggers.
 *
 * SRP: catalog entries + palette -> derived view values. No preact, no DOM,
 * no I/O. Filters narrow presentation only; they never change authority.
 */

import type {
  ActionTypePaletteEntry,
  WorkflowCatalogEntry,
  WorkflowCatalogStep,
} from "../workflow/validate";
import { getLocale } from "../i18n";
import { t } from "./i18n/workflow";

export interface WorkflowBrowseFilter {
  readonly text: string;
  readonly category: string;
  readonly stepKind: string;
}

export const EMPTY_BROWSE_FILTER: WorkflowBrowseFilter = { text: "", category: "", stepKind: "" };

export function stepKindOf(step: Pick<WorkflowCatalogStep, "kind">): string {
  return step.kind ?? "action";
}

function categoryMap(palette: readonly ActionTypePaletteEntry[]): Map<string, string> {
  return new Map(palette.map((entry) => [entry.name, entry.category ?? "other"]));
}

/** ActionType categories referenced by at least one action step. */
export function workflowCategories(
  workflows: readonly WorkflowCatalogEntry[],
  palette: readonly ActionTypePaletteEntry[],
): string[] {
  const categories = categoryMap(palette);
  const found = new Set<string>();
  for (const workflow of workflows) {
    for (const step of workflow.steps) {
      if (step.action_type_ref) found.add(categories.get(step.action_type_ref) ?? "other");
    }
  }
  return [...found].sort();
}

/** Step kinds present in the catalog, in authoring order. */
export function workflowStepKinds(workflows: readonly WorkflowCatalogEntry[]): string[] {
  const order = ["action", "wait", "approval", "decision", "parallel", "gate", "evidence"];
  const found = new Set(workflows.flatMap((workflow) => workflow.steps.map(stepKindOf)));
  return [
    ...order.filter((kind) => found.has(kind)),
    ...[...found].filter((kind) => !order.includes(kind)).sort(),
  ];
}

/** Presentation-only catalog filter: every text token must appear in the
 * workflow's name, description, trigger, step ids, or step references. */
export function filterWorkflows(
  workflows: readonly WorkflowCatalogEntry[],
  filter: WorkflowBrowseFilter,
  palette: readonly ActionTypePaletteEntry[],
): WorkflowCatalogEntry[] {
  const categories = categoryMap(palette);
  const tokens = filter.text.toLowerCase().split(/\s+/).filter((token) => token.length > 0);
  return workflows.filter((workflow) => {
    if (
      filter.stepKind !== ""
      && !workflow.steps.some((step) => stepKindOf(step) === filter.stepKind)
    ) return false;
    if (
      filter.category !== ""
      && !workflow.steps.some((step) =>
        step.action_type_ref
        && (categories.get(step.action_type_ref) ?? "other") === filter.category
      )
    ) return false;
    if (tokens.length === 0) return true;
    const haystack = [
      workflow.name,
      workflow.description ?? "",
      workflow.trigger.kind,
      workflow.trigger.signal_type ?? "",
      workflow.trigger.schedule ?? "",
      workflow.default_mode,
      ...workflow.steps.flatMap((step) => [
        step.id,
        step.action_type_ref ?? "",
        step.gate_ref ?? "",
        step.wait_for ?? "",
      ]),
    ].join(" ").toLowerCase();
    return tokens.every((token) => haystack.includes(token));
  });
}

export interface WorkflowApprovalFacts {
  /** Explicit `approval` control steps. */
  readonly approvalSteps: number;
  /** Action steps whose ActionType ceiling escalates to HIL at some tier. */
  readonly hilGatedActions: number;
}

/** Count explicit approval steps separately from HIL-gated ActionTypes so the
 * summary never presents a tier ceiling as an authored approval step. */
export function workflowApprovalFacts(
  workflow: Pick<WorkflowCatalogEntry, "steps">,
  palette: readonly ActionTypePaletteEntry[],
): WorkflowApprovalFacts {
  const gated = new Set(
    palette.filter((entry) => entry.hil_tiers.length > 0).map((entry) => entry.name),
  );
  return {
    approvalSteps: workflow.steps.filter((step) => step.kind === "approval").length,
    hilGatedActions: workflow.steps.filter((step) =>
      typeof step.action_type_ref === "string" && gated.has(step.action_type_ref)
    ).length,
  };
}

function localeTag(): string {
  return getLocale() === "ko" ? "ko-KR" : "en-US";
}

function isInteger(value: string, min: number, max: number): boolean {
  if (!/^\d{1,2}$/.test(value)) return false;
  const parsed = Number(value);
  return parsed >= min && parsed <= max;
}

function clock(hour: string, minute: string): string {
  return `${hour.padStart(2, "0")}:${minute.padStart(2, "0")}`;
}

function weekdayName(day: number): string {
  // 2024-01-07 is a Sunday, so day 0..6 maps to Sunday..Saturday.
  return new Date(Date.UTC(2024, 0, 7 + (day % 7))).toLocaleDateString(localeTag(), {
    weekday: "long",
    timeZone: "UTC",
  });
}

/** Readable label for the common five-field cron shapes the catalog uses.
 * Returns null for any other shape so the caller shows the raw expression
 * instead of guessing. Catalog schedules run in UTC; a binding passes its
 * own IANA timezone. */
export function describeSchedule(expression: string, zone = "UTC"): string | null {
  const fields = expression.trim().split(/\s+/);
  if (fields.length !== 5) return null;
  const [minute, hour, dayOfMonth, month, dayOfWeek] = fields as [string, string, string, string, string];
  if (month !== "*" || !isInteger(minute, 0, 59)) return null;
  if (hour === "*" && dayOfMonth === "*" && dayOfWeek === "*") {
    return t("workflow.schedule.hourly", { minute: minute.padStart(2, "0"), zone });
  }
  if (!isInteger(hour, 0, 23)) return null;
  const time = clock(hour, minute);
  if (dayOfMonth === "*" && dayOfWeek === "*") return t("workflow.schedule.daily", { time, zone });
  if (dayOfMonth === "*" && isInteger(dayOfWeek, 0, 7)) {
    return t("workflow.schedule.weekly", { day: weekdayName(Number(dayOfWeek)), time, zone });
  }
  if (dayOfWeek === "*" && isInteger(dayOfMonth, 1, 31)) {
    return t("workflow.schedule.monthly", { day: dayOfMonth, time, zone });
  }
  return null;
}

/** Operator-facing trigger summary: a readable schedule or the signal type. */
export function triggerSummary(trigger: WorkflowCatalogEntry["trigger"]): string {
  if (trigger.kind === "schedule") {
    const schedule = trigger.schedule ?? "";
    return describeSchedule(schedule) ?? schedule;
  }
  return trigger.signal_type ?? trigger.kind;
}

const CRON_FIELD = /^(\*|\d{1,2}(-\d{1,2})?)(\/\d{1,2})?(,(\*|\d{1,2}(-\d{1,2})?)(\/\d{1,2})?)*$/;

/** Client-side shape check for a five-field cron expression. The Operator
 * remains the authority; this only flags an obviously malformed value early. */
export function isFiveFieldCron(expression: string): boolean {
  const fields = expression.trim().split(/\s+/);
  return fields.length === 5 && fields.every((field) => CRON_FIELD.test(field));
}

/** The browser's IANA timezone, or UTC when the runtime does not expose one. */
export function browserTimeZone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  } catch {
    return "UTC";
  }
}
