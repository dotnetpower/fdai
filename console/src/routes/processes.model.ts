import { ReadApiError } from "../api";

export interface ProcessSummary {
  readonly id: string;
  readonly workflow_ref: string;
  readonly workflow_version: string;
  readonly status: string;
  readonly current_step: string;
  readonly target_resource_id: string;
  readonly updated_at: string;
  readonly has_view: boolean;
}

export interface ProcessListResponse {
  readonly items: readonly ProcessSummary[];
}

export interface RenderedWidget {
  readonly id: string;
  readonly type: string;
  readonly title: string;
  readonly data: Readonly<Record<string, unknown>>;
  readonly options: Readonly<Record<string, unknown>>;
  readonly error?: string;
  readonly children?: readonly RenderedWidget[];
}

export interface RenderedReport {
  readonly id: string;
  readonly name: string;
  readonly description: string;
  readonly generated_at: string;
  readonly widgets: readonly RenderedWidget[];
}

export interface RenderedProcessView {
  readonly id: string;
  readonly version: string;
  readonly name: string;
  readonly description: string;
  readonly route: string;
  readonly process: ProcessSummary & {
    readonly started_at: string;
    readonly correlation_id: string;
    readonly revision: number;
  };
  readonly regions: readonly {
    readonly id: string;
    readonly column_span: number;
    readonly report: RenderedReport;
  }[];
}

export function processIdFromHash(hash: string): string | null {
  let normalized = hash;
  try {
    normalized = decodeURIComponent(hash);
  } catch {
    // Preserve the raw hash when a malformed percent escape is present.
  }
  const queryIndex = normalized.indexOf("?");
  if (queryIndex < 0) return null;
  return new URLSearchParams(normalized.slice(queryIndex + 1)).get("process");
}

export function processHref(processId: string): string {
  return `#/processes?process=${encodeURIComponent(processId)}`;
}

export function processTone(status: string): "success" | "warning" | "danger" | "info" {
  if (["succeeded", "approved", "ready", "compensated"].includes(status)) return "success";
  if (["failed", "rejected", "cancelled", "timed_out", "blocked"].includes(status)) return "danger";
  if (["waiting", "conditional", "pending"].includes(status)) return "warning";
  return "info";
}

export function displayValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "-";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

export function defaultProcessId(
  items: readonly ProcessSummary[],
  currentHash: string,
): string | null {
  return processIdFromHash(currentHash) ?? items.find((item) => item.has_view)?.id ?? null;
}

export function decodeProcessList(value: unknown): ProcessListResponse {
  const root = record(value, "process list");
  if (!Array.isArray(root["items"])) throw new Error("process list items MUST be an array");
  return { items: root["items"].map((item, index) => decodeSummary(item, `items[${index}]`)) };
}

export function decodeRenderedProcessView(value: unknown): RenderedProcessView {
  const root = record(value, "process view");
  const process = record(root["process"], "process view process");
  if (!Array.isArray(root["regions"])) throw new Error("process view regions MUST be an array");
  return {
    id: stringField(root, "id", "process view"),
    version: stringField(root, "version", "process view"),
    name: stringField(root, "name", "process view"),
    description: stringField(root, "description", "process view"),
    route: stringField(root, "route", "process view"),
    process: {
      ...decodeSummary(process, "process view process", false),
      started_at: stringField(process, "started_at", "process view process"),
      correlation_id: stringField(process, "correlation_id", "process view process"),
      revision: numberField(process, "revision", "process view process"),
    },
    regions: root["regions"].map((item, index) => {
      const region = record(item, `regions[${index}]`);
      const report = record(region["report"], `regions[${index}].report`);
      if (!Array.isArray(report["widgets"])) {
        throw new Error(`regions[${index}].report widgets MUST be an array`);
      }
      return {
        id: stringField(region, "id", `regions[${index}]`),
        column_span: numberField(region, "column_span", `regions[${index}]`),
        report: {
          id: stringField(report, "id", `regions[${index}].report`),
          name: stringField(report, "name", `regions[${index}].report`),
          description: stringField(report, "description", `regions[${index}].report`),
          generated_at: stringField(report, "generated_at", `regions[${index}].report`),
          widgets: report["widgets"].map((widget, widgetIndex) =>
            decodeWidget(widget, `regions[${index}].report.widgets[${widgetIndex}]`)),
        },
      };
    }),
  };
}

export function processListFailure(error: unknown):
  | { readonly status: "unavailable"; readonly message: string }
  | { readonly status: "error"; readonly message: string } {
  if (error instanceof ReadApiError && (error.status === 404 || error.status === 501)) {
    return {
      status: "unavailable",
      message: "Process projections are not wired on this deployment.",
    };
  }
  return {
    status: "error",
    message: error instanceof Error ? error.message : String(error),
  };
}

function decodeSummary(value: unknown, label: string, requireHasView = true): ProcessSummary {
  const item = record(value, label);
  return {
    id: stringField(item, "id", label),
    workflow_ref: stringField(item, "workflow_ref", label),
    workflow_version: stringField(item, "workflow_version", label),
    status: stringField(item, "status", label),
    current_step: stringField(item, "current_step", label),
    target_resource_id: stringField(item, "target_resource_id", label),
    updated_at: stringField(item, "updated_at", label),
    has_view: requireHasView ? booleanField(item, "has_view", label) : true,
  };
}

function decodeWidget(value: unknown, label: string): RenderedWidget {
  const widget = record(value, label);
  const children = widget["children"];
  if (children !== undefined && !Array.isArray(children)) {
    throw new Error(`${label} children MUST be an array`);
  }
  return {
    id: stringField(widget, "id", label),
    type: stringField(widget, "type", label),
    title: stringField(widget, "title", label),
    data: record(widget["data"], `${label}.data`),
    options: record(widget["options"], `${label}.options`),
    ...(typeof widget["error"] === "string" ? { error: widget["error"] } : {}),
    ...(children ? { children: children.map((child, index) => decodeWidget(child, `${label}.children[${index}]`)) } : {}),
  };
}

function record(value: unknown, label: string): Readonly<Record<string, unknown>> {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`${label} MUST be an object`);
  }
  return value as Readonly<Record<string, unknown>>;
}

function stringField(value: Readonly<Record<string, unknown>>, key: string, label: string): string {
  if (typeof value[key] !== "string") throw new Error(`${label}.${key} MUST be a string`);
  return value[key];
}

function numberField(value: Readonly<Record<string, unknown>>, key: string, label: string): number {
  if (typeof value[key] !== "number" || !Number.isFinite(value[key])) {
    throw new Error(`${label}.${key} MUST be a finite number`);
  }
  return value[key];
}

function booleanField(value: Readonly<Record<string, unknown>>, key: string, label: string): boolean {
  if (typeof value[key] !== "boolean") throw new Error(`${label}.${key} MUST be a boolean`);
  return value[key];
}
