import { StatusPill } from "../components/ui";
import { displayValue, type RenderedWidget } from "./processes.model";
import { asRows, boundedRatio, percent } from "./process-view-widget-utils";

export const WORKFLOW_WIDGET_TYPES = new Set(["process_steps", "comparison"]);

export function WorkflowPresentationWidget({ widget }: { readonly widget: RenderedWidget }) {
  return widget.type === "process_steps"
    ? <ProcessStepsWidget widget={widget} />
    : <ComparisonWidget widget={widget} />;
}

function ProcessStepsWidget({ widget }: { readonly widget: RenderedWidget }) {
  const steps = asRows(widget.data["steps"]);
  const ratio = boundedRatio(widget.data["progress_ratio"]);
  return <section class="process-widget-section" aria-labelledby={`${widget.id}-title`}><div class="report-summary-head"><h3 id={`${widget.id}-title`}>{widget.title}</h3><span>{displayValue(widget.data["completed"])} / {displayValue(widget.data["total"])} complete</span></div><progress max={1} value={ratio ?? 0}>{percent(ratio)}</progress><ol class="report-process-steps">{steps.map((step, index) => {
    const status = stepStatus(displayValue(step["status"]));
    return <li key={`${displayValue(step["id"])}-${index}`} class={`is-${status}`}><span class="report-step-index" aria-hidden="true">{index + 1}</span><div><strong>{displayValue(step["name"])}</strong><small>{displayValue(step["message"])}{step["at"] === undefined ? "" : ` / ${displayValue(step["at"])}`}{step["duration_ms"] === undefined ? "" : ` / ${displayValue(step["duration_ms"])} ms`}</small></div><StatusPill kind={stepTone(status)} label={status} /></li>;
  })}</ol>{widget.data["truncated"] === true ? <p class="muted small">Only the first 200 steps are shown.</p> : null}{steps.length === 0 ? <p class="muted small">No workflow steps.</p> : null}</section>;
}

function ComparisonWidget({ widget }: { readonly widget: RenderedWidget }) {
  const rows = asRows(widget.data["rows"]);
  return <section class="process-widget-section" aria-labelledby={`${widget.id}-title`}><div class="report-summary-head"><h3 id={`${widget.id}-title`}>{widget.title}</h3><span>{displayValue(widget.data["changed_count"])} of {displayValue(widget.data["total"])} changed</span></div><div class="scroll"><table class="data-table report-comparison"><caption class="sr-only">{widget.title}</caption><thead><tr><th scope="col">Field</th><th scope="col">Before</th><th scope="col">After</th><th scope="col">Result</th></tr></thead><tbody>{rows.map((row, index) => {
    const changed = row["changed"] === true;
    return <tr key={`${displayValue(row["field"])}-${index}`} class={changed ? "is-changed" : undefined}><th scope="row">{displayValue(row["field"])}</th><td data-label="Before">{displayValue(row["before"])}</td><td data-label="After">{displayValue(row["after"])}</td><td data-label="Result"><StatusPill kind={changed ? "warning" : "neutral"} label={changed ? "changed" : "unchanged"} /></td></tr>;
  })}</tbody></table></div>{widget.data["truncated"] === true ? <p class="muted small">Only the first 200 fields are shown.</p> : null}{rows.length === 0 ? <p class="muted small">No comparison rows.</p> : null}</section>;
}

type StepStatus = "pending" | "running" | "waiting" | "succeeded" | "failed" | "skipped" | "cancelled" | "unknown";

function stepStatus(value: string): StepStatus {
  if (value === "pending" || value === "running" || value === "waiting" || value === "succeeded" || value === "failed" || value === "skipped" || value === "cancelled") return value;
  return "unknown";
}

function stepTone(status: StepStatus): "success" | "warning" | "danger" | "neutral" | "info" {
  if (status === "succeeded") return "success";
  if (status === "failed" || status === "cancelled") return "danger";
  if (status === "running") return "info";
  if (status === "waiting" || status === "pending") return "warning";
  return "neutral";
}
