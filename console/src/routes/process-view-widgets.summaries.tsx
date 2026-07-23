import { KpiCard, KpiGrid, StatusPill } from "../components/ui";
import { displayValue, processTone, type RenderedWidget } from "./processes.model";
import { asRecord, asRows, boundedRatio, finiteNumber, percent } from "./process-view-widget-utils";
import {
  formatCurrency as formatLocalizedCurrency,
  formatDateTimeValue,
  formatNumber,
  statusLabel,
  t,
} from "./i18n/workflow";

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
    return formatLocalizedCurrency(amount, code);
  } catch {
    return `${amount.toFixed(2)} ${code}`;
  }
}

export function SummaryWidget({ widget, href }: { readonly widget: RenderedWidget; readonly href: string }) {
  if (widget.type === "alert_status") return <AlertWidget widget={widget} />;
  if (widget.type === "event_stream") return <EventWidget widget={widget} />;
  if (widget.type === "slo_summary") return <SloWidget widget={widget} href={href} />;
  if (widget.type === "service_summary") return <ServiceWidget widget={widget} href={href} />;
  if (widget.type === "cost_summary") return <CostWidget widget={widget} />;
  return <BudgetWidget widget={widget} />;
}

function AlertWidget({ widget }: { readonly widget: RenderedWidget }) {
  const counts = asRecord(widget.data["counts_by_severity"]);
  const active = asRows(widget.data["active"]);
  return <section class="process-widget-section" aria-labelledby={`${widget.id}-title`}><h3 id={`${widget.id}-title`}>{widget.title}</h3><div class="report-status-counts">{SEVERITIES.map((severity) => <span key={severity}><StatusPill kind={severityTone(severity)} label={statusLabel(severity)} /><strong>{typeof counts[severity] === "number" ? formatNumber(counts[severity]) : displayValue(counts[severity])}</strong></span>)}</div><ol class="report-alert-list">{active.map((alert, index) => <li key={`${displayValue(alert["id"])}-${index}`}><StatusPill kind={severityTone(displayValue(alert["severity"]))} label={statusLabel(displayValue(alert["severity"]))} /><div><strong>{displayValue(alert["title"])}</strong><span class="muted small">{displayValue(alert["resource"])} / {formatDateTimeValue(alert["at"])}</span></div></li>)}</ol>{active.length === 0 ? <p class="muted small">{t("workflow.process.noActiveAlerts")}</p> : null}</section>;
}

function EventWidget({ widget }: { readonly widget: RenderedWidget }) {
  const counts = asRecord(widget.data["counts_by_severity"]);
  const items = asRows(widget.data["items"]);
  return <section class="process-widget-section" aria-labelledby={`${widget.id}-title`}><h3 id={`${widget.id}-title`}>{widget.title}</h3><div class="report-status-counts">{SEVERITIES.map((severity) => <span key={severity}><StatusPill kind={severityTone(severity)} label={statusLabel(severity)} /><strong>{typeof counts[severity] === "number" ? formatNumber(counts[severity]) : displayValue(counts[severity])}</strong></span>)}</div><ol class="process-timeline">{items.map((item, index) => <li key={`${displayValue(item["id"] ?? item["event_id"])}-${index}`}><span class="process-timeline-marker" aria-hidden="true" /><div><strong>{displayValue(item["title"] ?? item["kind"] ?? item["action_kind"])}</strong><p class="muted small">{displayValue(item["resource"] ?? item["resource_id"])} / {formatDateTimeValue(item["at"] ?? item["recorded_at"])}</p></div></li>)}</ol>{items.length === 0 ? <p class="muted small">{t("workflow.process.noEvents")}</p> : null}</section>;
}

function SloWidget({ widget, href }: { readonly widget: RenderedWidget; readonly href: string }) {
  const attainment = boundedRatio(widget.data["attainment"]);
  const target = boundedRatio(widget.data["target"]);
  const remaining = boundedRatio(widget.data["error_budget_remaining"]);
  const healthy = attainment !== null && target !== null && attainment >= target;
  return <section class="process-widget-section" aria-labelledby={`${widget.id}-title`}><h3 id={`${widget.id}-title`}>{widget.title}</h3><div class="report-summary-head"><div><strong>{displayValue(widget.data["objective"])}</strong><span class="muted small">{displayValue(widget.data["window"])}</span></div><StatusPill kind={healthy ? "success" : "warning"} label={t(healthy ? "workflow.process.onTarget" : "workflow.process.review")} /></div><KpiGrid><KpiCard href={href} label={t("workflow.process.attainment")} value={percent(attainment)} tone={healthy ? "positive" : "warning"} /><KpiCard href={href} label={t("workflow.process.target")} value={percent(target)} /><KpiCard href={href} label={t("workflow.process.budgetRemaining")} value={percent(remaining)} /><KpiCard href={href} label={t("workflow.process.burnRate")} value={displayValue(widget.data["burn_rate"])} /></KpiGrid></section>;
}

function ServiceWidget({ widget, href }: { readonly widget: RenderedWidget; readonly href: string }) {
  const red = asRecord(widget.data["red"]);
  const health = displayValue(widget.data["health"]);
  return <section class="process-widget-section" aria-labelledby={`${widget.id}-title`}><div class="report-summary-head"><div><h3 id={`${widget.id}-title`}>{widget.title}</h3><strong>{displayValue(widget.data["service"])}</strong></div><StatusPill kind={healthTone(health)} label={statusLabel(health)} /></div><KpiGrid><KpiCard href={href} label={t("workflow.process.requestsPerSecond")} value={displayValue(red["requests_rps"])} /><KpiCard href={href} label={t("workflow.process.errorRate")} value={displayValue(red["error_rate"])} tone={processTone(displayValue(red["error_rate"])) === "danger" ? "danger" : "default"} /><KpiCard href={href} label={t("workflow.process.latencyP50")} value={displayValue(red["latency_p50"])} /><KpiCard href={href} label={t("workflow.process.latencyP99")} value={displayValue(red["latency_p99"])} /></KpiGrid></section>;
}

function CostWidget({ widget }: { readonly widget: RenderedWidget }) {
  const rows = asRows(widget.data["rows"]);
  const currency = widget.data["currency"];
  const maximum = Math.max(1, ...rows.map((row) => Math.max(0, finiteNumber(row["amount"]) ?? 0)));
  return <section class="process-widget-section" aria-labelledby={`${widget.id}-title`}><div class="report-summary-head"><h3 id={`${widget.id}-title`}>{widget.title}</h3><strong>{formatCurrency(widget.data["total"], currency)}</strong></div><div class="report-bars">{rows.map((row, index) => {
    const amount = Math.max(0, finiteNumber(row["amount"]) ?? 0);
    return <div class="report-bar-row" key={`${displayValue(row["group"])}-${index}`}><span>{displayValue(row["group"])}</span><span class="report-bar-track" aria-hidden="true"><span style={{ width: `${amount / maximum * 100}%` }} /></span><strong>{formatCurrency(row["amount"], currency)}</strong></div>;
  })}</div>{rows.length === 0 ? <p class="muted small">{t("workflow.process.noCostGroups")}</p> : null}</section>;
}

function BudgetWidget({ widget }: { readonly widget: RenderedWidget }) {
  const utilization = boundedRatio(widget.data["utilization"]);
  const currency = widget.data["currency"];
  const over = (finiteNumber(widget.data["variance"]) ?? 0) > 0;
  return <section class="process-widget-section" aria-labelledby={`${widget.id}-title`}><div class="report-summary-head"><h3 id={`${widget.id}-title`}>{widget.title}</h3><StatusPill kind={over ? "warning" : "success"} label={t(over ? "workflow.process.overBudget" : "workflow.process.withinBudget")} /></div><div class="report-progress-head"><strong>{formatCurrency(widget.data["actual"], currency)} / {formatCurrency(widget.data["budget"], currency)}</strong><span>{utilization === null ? "-" : percent(utilization)}</span></div><progress max={1} value={utilization ?? 0}>{percent(utilization)}</progress><dl class="process-fallback"><dt>{t("workflow.process.variance")}</dt><dd>{formatCurrency(widget.data["variance"], currency)}</dd></dl></section>;
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
