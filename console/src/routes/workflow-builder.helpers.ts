/**
 * Workflow-builder pure helpers - name/id normalization, catalog->form
 * projection, draft assembly, GitHub URL construction, param formatting.
 *
 * SRP: deterministic, testable, no React, no I/O. Extracted from
 * `workflow-builder.tsx` so both the components and the vitest suite can
 * import them without pulling in preact/hooks.
 */

import { loadConfig } from "../config";
import type { WorkflowCatalogEntry } from "../workflow/validate";
import {
  SIGNAL_TYPE_OPTIONS,
  type DraftStep,
  type FormState,
} from "./workflow-builder.model";

/** Empty starter row. `key` is a stable client-side identity so re-orders
 * and removals do not shuffle React state. */
export function emptyStep(key: number): DraftStep {
  return {
    key,
    id: "",
    action_type_ref: "",
    guard_rule_ref: "",
    compensated_by: "",
    on_failure: "",
    params: {},
  };
}

/** Plain-language label for a signal value, or "" if it is a custom one. */
export function signalLabel(value: string): string {
  return SIGNAL_TYPE_OPTIONS.find((o) => o.value === value)?.label ?? "";
}

/** Human-friendly label for an ActionType machine name
 * ("remediate.right-size" -> "Right-size"). Shown wherever an operator
 * reads an action, always with the exact machine name kept alongside. */
export function humanizeActionName(name: string): string {
  const seg = name.includes(".") ? name.slice(name.lastIndexOf(".") + 1) : name;
  const words = seg.replace(/[-_]/g, " ").trim();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/** Turn a built-in workflow into an editable draft so an operator can
 * clone-and-tweak instead of starting from a blank form. */
export function catalogToForm(w: WorkflowCatalogEntry): FormState {
  // Keep the "-copy" name within the 80-char id limit so the clone still
  // passes the server name pattern.
  const copyName = `${w.name}-copy`;
  return {
    name: copyName.length <= 80 ? copyName : `${w.name.slice(0, 75)}-copy`,
    version: w.version,
    description: w.description ?? "",
    triggerKind: w.trigger.kind === "schedule" ? "schedule" : "signal",
    signalType: w.trigger.signal_type ?? "object.drift",
    schedule: w.trigger.schedule ?? "",
    minShadowDays: String(w.promotion_gate.min_shadow_days),
    minSamples: String(w.promotion_gate.min_samples),
    minAccuracy: String(w.promotion_gate.min_accuracy),
    maxPolicyEscapes: String(w.promotion_gate.max_policy_escapes),
    antiScope: w.anti_scope ?? "",
    steps: w.steps.map((s, i) => ({
      key: i,
      id: s.id,
      action_type_ref: s.action_type_ref,
      guard_rule_ref: s.guard_rule_ref ?? "",
      compensated_by: s.compensated_by ?? "",
      on_failure: s.on_failure ?? "",
      params: { ...(s.params ?? {}) },
    })),
  };
}

/** Humanize a server issue key ("draft:steps.s1.action_type_ref") into a
 * readable location ("steps > s1 > action type ref") for the issues table,
 * keeping the raw key available as a tooltip. */
export function humanizeIssueKey(key: string): string {
  const noPrefix = key.replace(/^draft:/, "").trim();
  if (noPrefix === "" || noPrefix === "<root>") return "workflow";
  return noPrefix.replace(/\./g, " > ").replace(/_/g, " ");
}

/** Build a GitHub "new file" URL that pre-fills the workflow YAML at its
 * catalog path, so a validated draft becomes a PR in one click. Returns
 * null when the repo is not a valid `owner/repo`. Pure and exported for
 * tests; the config-reading wrapper is `githubNewFileUrl`. */
export function buildGithubNewFileUrl(
  repo: string,
  branch: string,
  filePath: string,
  yaml: string,
): string | null {
  if (!/^[\w.-]+\/[\w.-]+$/.test(repo.trim())) return null;
  const params = new URLSearchParams({ filename: filePath, value: yaml });
  const url = `https://github.com/${repo.trim()}/new/${encodeURIComponent(
    branch.trim() || "main",
  )}?${params.toString()}`;
  // GitHub / browsers reject very long URLs (the YAML rides in ?value=). Above
  // a safe ceiling, fall back to copy / download rather than open a broken or
  // truncated new-file link.
  if (url.length > 7000) return null;
  return url;
}

/** Config-reading wrapper: returns the new-file URL when a catalog repo is
 * configured, else null (the console then falls back to copy / download).
 * The console never commits - this only opens GitHub in a new tab. */
export function githubNewFileUrl(filePath: string, yaml: string): string | null {
  const cfg = loadConfig();
  return buildGithubNewFileUrl(cfg.workflowCatalogRepo, cfg.workflowCatalogBranch, filePath, yaml);
}

/** Turn a dotted workflow name ("cost-aware-remediation") into a readable
 * title ("Cost aware remediation") for template cards. */
export function humanizeName(name: string): string {
  const words = name.replace(/[._-]+/g, " ").trim();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/** Suggest a snake_case step id from an ActionType ref so the operator does
 * not have to invent one. "remediate.right-size" -> "right_size", made
 * unique against ids already used in the draft. */
export function suggestStepId(actionTypeRef: string, takenIds: readonly string[]): string {
  const leaf = actionTypeRef.split(/[./:]/).pop() ?? actionTypeRef;
  const base =
    leaf
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "_")
      .replace(/^_+|_+$/g, "") || "step";
  const taken = new Set(takenIds);
  if (!taken.has(base)) return base;
  for (let i = 2; ; i += 1) {
    const candidate = `${base}_${i}`;
    if (!taken.has(candidate)) return candidate;
  }
}

/** Assemble the JSON draft the validate endpoint expects, dropping empty
 * optional fields so the server sees a clean mapping. */
export function buildDraft(form: FormState): Record<string, unknown> {
  const trigger: Record<string, unknown> = { kind: form.triggerKind };
  if (form.triggerKind === "signal") trigger["signal_type"] = form.signalType.trim();
  else trigger["schedule"] = form.schedule.trim();

  const steps = form.steps.map((s) => {
    const step: Record<string, unknown> = {
      id: s.id.trim(),
      action_type_ref: s.action_type_ref.trim(),
    };
    if (s.guard_rule_ref.trim()) step["guard_rule_ref"] = s.guard_rule_ref.trim();
    if (s.compensated_by.trim()) step["compensated_by"] = s.compensated_by.trim();
    if (s.on_failure.trim()) step["on_failure"] = s.on_failure.trim();
    if (Object.keys(s.params).length > 0) step["params"] = { ...s.params };
    return step;
  });

  const draft: Record<string, unknown> = {
    schema_version: "1.0.0",
    name: form.name.trim(),
    version: form.version.trim(),
    trigger,
    default_mode: "shadow",
    promotion_gate: {
      min_shadow_days: Number(form.minShadowDays),
      min_samples: Number(form.minSamples),
      min_accuracy: Number(form.minAccuracy),
      max_policy_escapes: Number(form.maxPolicyEscapes),
    },
    steps,
  };
  if (form.description.trim()) draft["description"] = form.description.trim();
  if (form.antiScope.trim()) draft["anti_scope"] = form.antiScope.trim();
  return draft;
}

/** Render a step's params map as a compact "k=v, k=v" string, or "-". */
export function formatParams(
  params: Record<string, string | number | boolean> | undefined,
): string {
  if (!params) return "-";
  const pairs = Object.entries(params);
  if (pairs.length === 0) return "-";
  return pairs.map(([k, v]) => `${k}=${v}`).join(", ");
}
