import type { PillKind } from "../components/ui";
import { routeHref } from "../router";

export interface WorkflowAppEntry {
  readonly id: string;
  readonly workflow_ref: string;
  readonly view_ref: string;
  readonly lifecycle: "published";
  readonly audience: "reader";
  readonly label: Readonly<Record<"en" | "ko", string>>;
  readonly description: Readonly<Record<"en" | "ko", string>>;
  readonly route: string;
  readonly group: "operations";
  readonly order: number;
}

export interface WorkflowAppsResponse {
  readonly items: readonly WorkflowAppEntry[];
  readonly count: number;
}

export function decodeWorkflowApps(value: unknown): WorkflowAppsResponse {
  const root = record(value, "workflow apps");
  if (!Array.isArray(root["items"])) throw new Error("workflow apps items MUST be an array");
  const count = integer(root["count"], "workflow apps count");
  const items = root["items"].map((item, index) => decodeApp(item, `items[${index}]`));
  if (count !== items.length) throw new Error("workflow apps count MUST equal items length");
  assertUnique(items.map((item) => item.id), "workflow app ids");
  assertUnique(items.map((item) => item.workflow_ref), "workflow app workflow refs");
  assertUnique(items.map((item) => String(item.order)), "workflow app orders");
  return { items, count };
}

export function workflowAppHref(
  appId: string,
  search?: URLSearchParams,
): string {
  return routeHref("workflow-apps", {
    segments: [appId],
    params: {
      data: search?.get("data") === "sample" ? "sample" : null,
    },
  });
}

function decodeApp(value: unknown, label: string): WorkflowAppEntry {
  const item = record(value, label);
  const id = text(item["id"], `${label}.id`);
  if (!/^[a-z][a-z0-9-]{1,63}$/.test(id)) throw new Error(`${label}.id MUST be kebab-case`);
  const route = text(item["route"], `${label}.route`);
  if (route !== `/workflow-apps/${id}`) throw new Error(`${label}.route MUST match its id`);
  if (item["lifecycle"] !== "published") throw new Error(`${label}.lifecycle MUST be published`);
  if (item["audience"] !== "reader") throw new Error(`${label}.audience MUST be reader`);
  if (item["group"] !== "operations") throw new Error(`${label}.group MUST be operations`);
  return {
    id,
    workflow_ref: text(item["workflow_ref"], `${label}.workflow_ref`),
    view_ref: text(item["view_ref"], `${label}.view_ref`),
    lifecycle: "published",
    audience: "reader",
    label: localized(item["label"], `${label}.label`),
    description: localized(item["description"], `${label}.description`),
    route,
    group: "operations",
    order: integer(item["order"], `${label}.order`),
  };
}

function localized(value: unknown, label: string): Readonly<Record<"en" | "ko", string>> {
  const item = record(value, label);
  return { en: text(item["en"], `${label}.en`), ko: text(item["ko"], `${label}.ko`) };
}

function record(value: unknown, label: string): Record<string, unknown> {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`${label} MUST be an object`);
  }
  return value as Record<string, unknown>;
}

function text(value: unknown, label: string): string {
  if (typeof value !== "string" || value.trim().length === 0) {
    throw new Error(`${label} MUST be a non-empty string`);
  }
  return value;
}

function integer(value: unknown, label: string): number {
  if (typeof value !== "number" || !Number.isInteger(value) || value < 0) {
    throw new Error(`${label} MUST be a non-negative integer`);
  }
  return value;
}

function assertUnique(values: readonly string[], label: string): void {
  if (new Set(values).size !== values.length) throw new Error(`${label} MUST be unique`);
}

/** Lifecycle tone for an app manifest. Only `published` reads as available;
 * other lifecycle values stay neutral instead of borrowing a success color. */
export function workflowAppLifecycleTone(lifecycle: string): PillKind {
  if (lifecycle === "published") return "success";
  if (lifecycle === "shadow") return "shadow";
  if (lifecycle === "retired") return "neutral";
  return "info";
}

const RUN_STATUS_ORDER = [
  "waiting",
  "failed",
  "timed_out",
  "compensating",
  "running",
  "pending",
  "succeeded",
  "compensated",
  "cancelled",
];

/** Per-status run counts, attention states first, for the run filter. */
export function workflowRunStatusCounts(
  items: readonly { readonly status: string }[],
): { readonly status: string; readonly count: number }[] {
  const counts = new Map<string, number>();
  for (const item of items) counts.set(item.status, (counts.get(item.status) ?? 0) + 1);
  const rank = (status: string) => {
    const index = RUN_STATUS_ORDER.indexOf(status);
    return index === -1 ? RUN_STATUS_ORDER.length : index;
  };
  return [...counts.entries()]
    .map(([status, count]) => ({ status, count }))
    .sort((left, right) => rank(left.status) - rank(right.status) || left.status.localeCompare(right.status));
}
