import { KpiCard, KpiGrid, StatusPill } from "../components/ui";
import { displayValue, processTone, type RenderedWidget } from "./processes.model";
import { asRecord, asRows, boundedRatio, finiteNumber, percent } from "./process-view-widget-utils";

export const SUMMARY_WIDGET_TYPES = new Set([
  "alert_status",
  "event_stream",
  "slo_summary",
  "service_summary",
  "cost_summary",
  "budget_summary",
]);

const SEVERITIES = ["critical", "high", "medium", "low", "info"] as const;

export function formatCurrency(value: unknown, currency: unknown): string {
  const amount = finiteNumber(value);
  const code = typeof currency === "string" && /^[A-Z]{3}$/.test(currency) ? currency : "USD";
  if (amount === null) return "-";
  try {
    return new Intl.NumberFormat(undefined, { style: "currency", currency: code }).format(amount);
  } catch {
    return `${amount.toFixed(2)} ${code}`;
  }
}

export function SummaryWidget({ widget }: { readonly widget: RenderedWidget }) {
  if (widget.type === "alert_status") return <AlertWidget widget={widget} />;
  if (widget.type === "event_stream") return <EventWidget widget={widget} />;
  if (widget.type === "slo_summary") return <SloWidget widget={widget} />;
  if (widget.type === "service_summary") return <ServiceWidget widget={widget} />;
  if (widget.type === "cost_summary") return <CostWidget widget={widget} />;
  return <BudgetWidget widget={widget} />;
}

function AlertWidget({ widget }: { readonly widget: RenderedWidget }) {
  const counts = asRecord(widget.data["counts_by_severity"]);
  const active = asRows(widget.data["active"]);
  return <section class="process-widget-section" aria-labelledby={`${widget.id}-title`}><h3 id={`${widget.id}-title`}>{widget.title}</h3><div class="report-status-counts">{SEVERITIES.map((severity) => <span key={severity}><StatusPill kind={severityTone(severity)} label={severity} /><strong>{displayValue(counts[severity])}</strong></span>)}</div><ol class="report-alert-list">{active.map((alert, index) => <li key={`${displayValue(alert["id"])}-${index}`}><StatusPill kind={severityTone(displayValue(alert["severity"]))} label={displayValue(alert["severity"])} /><div><strong>{displayValue(alert["title"])}</strong><span class="muted small">{displayValue(alert["resource"])} / {displayValue(alert["at"])}</span></div></li>)}</ol>{active.length === 0 ? <p class="muted small">No active alerts.</p> : null}</section>;
}

function EventWidget({ widget }: { readonly widget: RenderedWidget }) {
  const counts = asRecord(widget.data["counts_by_severity"]);
  const items = asRows(widget.data["items"]);
  return <section class="process-widget-section" aria-labelledby={`${widget.id}-title`}><h3 id={`${widget.id}-title`}>{widget.title}</h3><div class="report-status-counts">{SEVERITIES.map((severity) => <span key={severity}><StatusPill kind={severityTone(severity)} label={severity} /><strong>{displayValue(counts[severity])}</strong></span>)}</div><ol class="process-timeline">{items.map((item, index) => <li key={`${displayValue(item["id"] ?? item["event_id"])}-${index}`}><span class="process-timeline-marker" aria-hidden="true" /><div><strong>{displayValue(item["title"] ?? item["kind"] ?? item["action_kind"])}</strong><p class="muted small">{displayValue(item["resource"] ?? item["resource_id"])} / {displayValue(item["at"] ?? item["recorded_at"])}</p></div></li>)}</ol>{items.length === 0 ? <p class="muted small">No events.</p> : null}</section>;
}

function SloWidget({ widget }: { readonly widget: RenderedWidget }) {
  const attainment = boundedRatio(widget.data["attainment"]);
  const target = boundedRatio(widget.data["target"]);
  const remaining = boundedRatio(widget.data["error_budget_remaining"]);
  const healthy = attainment !== null && target !== null && attainment >= target;
  return <section class="process-widget-section" aria-labelledby={`${widget.id}-title`}><h3 id={`${widget.id}-title`}>{widget.title}</h3><div class="report-summary-head"><div><strong>{displayValue(widget.data["objective"])}</strong><span class="muted small">{displayValue(widget.data["window"])}</span></div><StatusPill kind={healthy ? "success" : "warning"} label={healthy ? "on target" : "review"} /></div><KpiGrid><KpiCard label="Attainment" value={percent(attainment)} tone={healthy ? "positive" : "warning"} /><KpiCard label="Target" value={percent(target)} /><KpiCard label="Budget remaining" value={percent(remaining)} /><KpiCard label="Burn rate" value={displayValue(widget.data["burn_rate"])} /></KpiGrid></section>;
}

function ServiceWidget({ widget }: { readonly widget: RenderedWidget }) {
  const red = asRecord(widget.data["red"]);
  const health = displayValue(widget.data["health"]);
  return <section class="process-widget-section" aria-labelledby={`${widget.id}-title`}><div class="report-summary-head"><div><h3 id={`${widget.id}-title`}>{widget.title}</h3><strong>{displayValue(widget.data["service"])}</strong></div><StatusPill kind={healthTone(health)} label={health} /></div><KpiGrid><KpiCard label="Requests / sec" value={displayValue(red["requests_rps"])} /><KpiCard label="Error rate" value={displayValue(red["error_rate"])} tone={processTone(displayValue(red["error_rate"])) === "danger" ? "danger" : "default"} /><KpiCard label="Latency p50" value={displayValue(red["latency_p50"])} /><KpiCard label="Latency p99" value={displayValue(red["latency_p99"])} /></KpiGrid></section>;
}

function CostWidget({ widget }: { readonly widget: RenderedWidget }) {
  const rows = asRows(widget.data["rows"]);
  const currency = widget.data["currency"];
  const maximum = Math.max(1, ...rows.map((row) => Math.max(0, finiteNumber(row["amount"]) ?? 0)));
  return <section class="process-widget-section" aria-labelledby={`${widget.id}-title`}><div class="report-summary-head"><h3 id={`${widget.id}-title`}>{widget.title}</h3><strong>{formatCurrency(widget.data["total"], currency)}</strong></div><div class="report-bars">{rows.map((row, index) => {
    const amount = Math.max(0, finiteNumber(row["amount"]) ?? 0);
    return <div class="report-bar-row" key={`${displayValue(row["group"])}-${index}`}><span>{displayValue(row["group"])}</span><span class="report-bar-track" aria-hidden="true"><span style={{ width: `${amount / maximum * 100}%` }} /></span><strong>{formatCurrency(row["amount"], currency)}</strong></div>;
  })}</div>{rows.length === 0 ? <p class="muted small">No cost groups.</p> : null}</section>;
}

function BudgetWidget({ widget }: { readonly widget: RenderedWidget }) {
  const utilization = boundedRatio(widget.data["utilization"]);
  const currency = widget.data["currency"];
  const over = (finiteNumber(widget.data["variance"]) ?? 0) > 0;
  return <section class="process-widget-section" aria-labelledby={`${widget.id}-title`}><div class="report-summary-head"><h3 id={`${widget.id}-title`}>{widget.title}</h3><StatusPill kind={over ? "warning" : "success"} label={over ? "over budget" : "within budget"} /></div><div class="report-progress-head"><strong>{formatCurrency(widget.data["actual"], currency)} / {formatCurrency(widget.data["budget"], currency)}</strong><span>{utilization === null ? "-" : percent(utilization)}</span></div><progress max={1} value={utilization ?? 0}>{percent(utilization)}</progress><dl class="process-fallback"><dt>Variance</dt><dd>{formatCurrency(widget.data["variance"], currency)}</dd></dl></section>;
}

function severityTone(severity: string): "danger" | "warning" | "neutral" {
  if (severity === "critical" || severity === "high") return "danger";
  if (severity === "medium") return "warning";
  return "neutral";
}

function healthTone(health: string): "success" | "warning" | "danger" | "neutral" {
  if (health === "healthy") return "success";
  if (health === "degraded") return "warning";
  if (health === "unhealthy") return "danger";
  return "neutral";
}
