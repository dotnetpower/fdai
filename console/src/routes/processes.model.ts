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
  const queryIndex = hash.indexOf("?");
  if (queryIndex < 0) return null;
  return new URLSearchParams(hash.slice(queryIndex + 1)).get("process");
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
