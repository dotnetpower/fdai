import { Fragment, type ComponentChildren } from "preact";
import { useState } from "preact/hooks";
import { ErrorState, KpiCard, KpiGrid, StatusPill } from "../components/ui";
import { displayValue, processTone, type RenderedWidget } from "./processes.model";
import { GRAPH_WIDGET_TYPES, GraphWidget } from "./process-view-widgets.graphs";
import { FLOW_WIDGET_TYPES, FlowWidget } from "./process-view-widgets.flows";
import { SUMMARY_WIDGET_TYPES, SummaryWidget } from "./process-view-widgets.summaries";
import { CONTENT_WIDGET_TYPES, ContentWidget } from "./process-view-widgets.content";
import { BLOCKED_REPORT_WIDGET_TYPES } from "./process-view-widget-contract";
import { WORKFLOW_WIDGET_TYPES, WorkflowPresentationWidget } from "./process-view-widgets.workflow";

export const SUPPORTED_REPORT_WIDGET_TYPES = new Set([
  "query_value", "bar_chart", "timeseries", "top_list", "table",
  "list_stream", "check_status", "topology_map", "group", "tabs",
  "change", "distribution", "heatmap", "pie_chart", "scatter_plot",
  "sparkline", "gauge", "progress_bar",
  "funnel", "sankey", "treemap", "retention", "flame_graph", "split_graph",
  "alert_status", "event_stream", "slo_summary", "service_summary",
  "cost_summary", "budget_summary",
  "free_text", "note", "image", "hostmap", "geomap",
  "process_steps", "comparison",
]);

export const MAX_WIDGET_RENDER_DEPTH = 8;

export function ProcessWidget({ widget, depth = 0 }: { readonly widget: RenderedWidget; readonly depth?: number }) {
  if (depth > MAX_WIDGET_RENDER_DEPTH) {
    return <ErrorState message={`${widget.title}: nested widget depth exceeds ${MAX_WIDGET_RENDER_DEPTH}`} />;
  }
  if (widget.error) return <ErrorState message={`${widget.title}: ${widget.error}`} />;
  if (BLOCKED_REPORT_WIDGET_TYPES.has(widget.type)) {
    return <BlockedWidget widget={widget} />;
  }
  if (widget.type === "query_value") {
    return (
      <KpiCard
        label={widget.title}
        value={displayValue(widget.data["value"])}
        tone={toneForValue(widget.data["value"])}
      />
    );
  }
  if (widget.type === "bar_chart") return <BarChartWidget widget={widget} />;
  if (widget.type === "timeseries") return <TimeseriesWidget widget={widget} />;
  if (widget.type === "check_status") return <CheckStatusWidget widget={widget} />;
  if (widget.type === "table" || widget.type === "top_list") return <TableWidget widget={widget} />;
  if (widget.type === "list_stream") return <StreamWidget widget={widget} />;
  if (widget.type === "topology_map") return <TopologyWidget widget={widget} />;
  if (GRAPH_WIDGET_TYPES.has(widget.type)) return <GraphWidget widget={widget} />;
  if (FLOW_WIDGET_TYPES.has(widget.type)) return <FlowWidget widget={widget} />;
  if (SUMMARY_WIDGET_TYPES.has(widget.type)) return <SummaryWidget widget={widget} />;
  if (CONTENT_WIDGET_TYPES.has(widget.type)) return <ContentWidget widget={widget} />;
  if (WORKFLOW_WIDGET_TYPES.has(widget.type)) return <WorkflowPresentationWidget widget={widget} />;
  if (widget.type === "tabs") return <TabsWidget widget={widget} depth={depth} />;
  if (widget.type === "group") {
    return (
      <section class="process-widget-group">
        <h3>{widget.title}</h3>
        <div class="process-widget-grid">
          {(widget.children ?? []).map((child) => <ProcessWidget key={child.id} widget={child} depth={depth + 1} />)}
        </div>
      </section>
    );
  }
  return <UnavailableWidget widget={widget} />;
}

function BarChartWidget({ widget }: { readonly widget: RenderedWidget }) {
  const bars = asRows(widget.data["bars"]);
  const values = bars.map((bar) => numericBarValue(bar["value"]));
  const max = Math.max(1, ...values.filter((value): value is number => value !== null));
  return (
    <section class="process-widget-section report-bar-chart" aria-labelledby={`${widget.id}-title`}>
      <h3 id={`${widget.id}-title`}>{widget.title}</h3>
      <div class="report-bars">
        {bars.map((bar, index) => {
          const value = numericBarValue(bar["value"]);
          return (
            <div class="report-bar-row" key={`${widget.id}-${index}`} aria-label={`${displayValue(bar["label"])}: ${displayValue(bar["value"])}`}>
              <span>{displayValue(bar["label"])}</span>
              <span class="report-bar-track" aria-hidden="true">
                <span style={{ width: `${barWidthPercent(value, max)}%` }} />
              </span>
              <strong>{displayValue(bar["value"])}</strong>
            </div>
          );
        })}
      </div>
      {bars.length === 0 ? <p class="muted small">No data in this window.</p> : null}
    </section>
  );
}

function TimeseriesWidget({ widget }: { readonly widget: RenderedWidget }) {
  const series = asRows(widget.data["series"]);
  return (
    <section class="process-widget-section report-timeseries" aria-labelledby={`${widget.id}-title`}>
      <h3 id={`${widget.id}-title`}>{widget.title}</h3>
      {series.map((item, index) => {
        const points = numericPoints(item["points"]);
        return (
          <div class="report-series" key={`${widget.id}-${index}`}>
            <span class="muted small">{displayValue(item["label"])}</span>
            {points.length > 0 ? (
              <svg viewBox="0 0 320 96" role="img" aria-label={`${displayValue(item["label"])} trend`}>
                <polyline points={sparkline(points, 320, 96)} fill="none" stroke="currentColor" stroke-width="2" />
              </svg>
            ) : <p class="muted small">No points.</p>}
            {points.length > 0 ? <details><summary>Data points</summary><div class="scroll"><table class="data-table"><caption class="sr-only">{displayValue(item["label"])} points</caption><thead><tr><th scope="col">Timestamp</th><th scope="col">Value</th></tr></thead><tbody>{points.map(([timestamp, value], pointIndex) => <tr key={`${timestamp}-${pointIndex}`}><td>{timestamp}</td><td>{value}</td></tr>)}</tbody></table></div></details> : null}
          </div>
        );
      })}
      {series.length === 0 ? <p class="muted small">No data in this window.</p> : null}
    </section>
  );
}

function TabsWidget({ widget, depth }: { readonly widget: RenderedWidget; readonly depth: number }) {
  const children = widget.children ?? [];
  const [active, setActive] = useState(0);
  const selected = children[active];
  return (
    <section class="process-widget-section report-tabs">
      <h3>{widget.title}</h3>
      <div role="tablist" aria-label={widget.title} class="report-tab-list">
        {children.map((child, index) => (
          <button
            key={child.id}
            id={`${widget.id}-tab-${index}`}
            type="button"
            role="tab"
            aria-selected={index === active}
            aria-controls={`${widget.id}-panel-${index}`}
            tabIndex={index === active ? 0 : -1}
            onClick={() => setActive(index)}
            onKeyDown={(event) => {
              const next = activateTabByKey(index, event.key, children.length, (targetIndex) => {
                event.currentTarget.parentElement
                  ?.querySelectorAll<HTMLButtonElement>("[role='tab']")
                  .item(targetIndex)
                  ?.focus();
              });
              if (next !== index) {
                event.preventDefault();
                setActive(next);
              }
            }}
          >
            {child.title}
          </button>
        ))}
      </div>
      {selected ? (
        <div id={`${widget.id}-panel-${active}`} role="tabpanel" aria-labelledby={`${widget.id}-tab-${active}`}>
          <ProcessWidget widget={selected} depth={depth + 1} />
        </div>
      ) : <p class="muted small">No tabs configured.</p>}
    </section>
  );
}

export function nextTabIndex(current: number, key: string, count: number): number {
  if (count < 1) return 0;
  if (key === "Home") return 0;
  if (key === "End") return count - 1;
  if (key === "ArrowRight" || key === "ArrowDown") return (current + 1) % count;
  if (key === "ArrowLeft" || key === "ArrowUp") return (current - 1 + count) % count;
  return current;
}

export function activateTabByKey(
  current: number,
  key: string,
  count: number,
  focus: (index: number) => void,
): number {
  const next = nextTabIndex(current, key, count);
  if (next !== current) focus(next);
  return next;
}

export function numericBarValue(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

export function barWidthPercent(value: number | null, maximum: number): number {
  if (value === null || value <= 0 || maximum <= 0) return 0;
  return Math.min(100, (value / maximum) * 100);
}

function CheckStatusWidget({ widget }: { readonly widget: RenderedWidget }) {
  const summary = asRecord(widget.data["summary"]);
  const checks = asRows(widget.data["checks"]);
  return (
    <section class="process-widget-section">
      <h3>{widget.title}</h3>
      <KpiGrid>
        {(["ok", "warn", "fail", "unknown"] as const).map((status) => (
          <KpiCard
            key={status}
            label={status}
            value={displayValue(summary[status])}
            tone={status === "ok" ? "positive" : status === "fail" ? "danger" : status === "warn" ? "warning" : "default"}
          />
        ))}
      </KpiGrid>
      <div class="process-check-list">
        {checks.map((check, index) => (
          <div class="process-check-row" key={`${displayValue(check["name"])}-${index}`}>
            <StatusPill kind={pillForCheck(displayValue(check["status"]))} label={displayValue(check["status"])} />
            <strong>{displayValue(check["name"])}</strong>
            <span class="muted">{displayValue(check["message"])}</span>
          </div>
        ))}
      </div>
    </section>
  );
}

function TableWidget({ widget }: { readonly widget: RenderedWidget }) {
  const rows = asRows(widget.data["rows"]);
  const configured = Array.isArray(widget.data["columns"])
    ? widget.data["columns"].map(String)
    : [];
  const columns = configured.length > 0 ? configured : deriveColumns(rows);
  return (
    <section class="process-widget-section">
      <h3>{widget.title}</h3>
      <div class="scroll">
        <table class="data-table process-data-table">
          <caption class="sr-only">{widget.title}</caption>
          <thead><tr>{widget.type === "top_list" ? <th scope="col">Rank</th> : null}{columns.map((column) => <th scope="col" key={column}>{column}</th>)}</tr></thead>
          <tbody>
            {rows.map((row, index) => (
              <tr key={`${widget.id}-${index}`}>
                {widget.type === "top_list" ? <th scope="row">{index + 1}</th> : null}
                {columns.map((column) => <td key={column}>{displayValue(row[column])}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {rows.length === 0 ? <p class="muted small">No rows.</p> : null}
    </section>
  );
}

function StreamWidget({ widget }: { readonly widget: RenderedWidget }) {
  const items = asRows(widget.data["items"]);
  return (
    <section class="process-widget-section">
      <h3>{widget.title}</h3>
      <ol class="process-timeline">
        {items.map((item, index) => (
          <li key={`${widget.id}-${index}`}>
            <span class="process-timeline-marker" />
            <div>
              <strong>{displayValue(item["kind"] ?? item["action_kind"])}</strong>
              <p class="muted small">{displayValue(item["step_id"])} · {displayValue(item["at"])}</p>
              {streamDetails(item).length > 0 ? <details><summary>Recorded fields</summary><dl class="process-fallback">{streamDetails(item).map(([key, value]) => <Fragment key={key}><dt>{key}</dt><dd>{displayValue(value)}</dd></Fragment>)}</dl></details> : null}
            </div>
          </li>
        ))}
      </ol>
    </section>
  );
}

function TopologyWidget({ widget }: { readonly widget: RenderedWidget }) {
  const nodes = asRows(widget.data["nodes"]);
  const edges = asRows(widget.data["edges"]);
  return (
    <section class="process-widget-section">
      <h3>{widget.title}</h3>
      <div class="process-topology-nodes">
        {nodes.map((node, index) => (
          <div class="process-topology-node" key={`${displayValue(node["id"])}-${index}`}>
            <span>{displayValue(node["group"])}</span>
            <strong>{displayValue(node["label"] ?? node["id"])}</strong>
            <small>{displayValue(node["value"])}</small>
          </div>
        ))}
      </div>
      <ul class="process-edge-list muted small" aria-label={`${widget.title} relationships`}>
        {edges.map((edge, index) => (
          <li key={`${widget.id}-edge-${index}`}>
            {displayValue(edge["source"])} → {displayValue(edge["target"])} · {displayValue(edge["value"])}
          </li>
        ))}
      </ul>
    </section>
  );
}

function UnavailableWidget({ widget }: { readonly widget: RenderedWidget }) {
  return (
    <section class="process-widget-section state-unavailable" role="status">
      <h3>{widget.title}</h3>
      <p class="muted">Widget type <code>{widget.type}</code> is not available in this console build.</p>
    </section>
  );
}

function BlockedWidget({ widget }: { readonly widget: RenderedWidget }) {
  return (
    <section class="process-widget-section state-unavailable" role="status">
      <h3>{widget.title}</h3>
      <p>
        Widget type <code>{widget.type}</code> is intentionally blocked on generated workflow
        surfaces because it can load executable or independently navigable remote content.
      </p>
    </section>
  );
}

function asRecord(value: unknown): Readonly<Record<string, unknown>> {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as Readonly<Record<string, unknown>>
    : {};
}

function asRows(value: unknown): readonly Readonly<Record<string, unknown>>[] {
  return Array.isArray(value) ? value.filter((item) => item !== null && typeof item === "object") : [];
}

function streamDetails(
  item: Readonly<Record<string, unknown>>,
): readonly (readonly [string, unknown])[] {
  const summaryKeys = new Set(["kind", "action_kind", "step_id", "at"]);
  return Object.entries(item).filter(([key]) => !summaryKeys.has(key)).slice(0, 20);
}

function deriveColumns(rows: readonly Readonly<Record<string, unknown>>[]): readonly string[] {
  const names = new Set<string>();
  rows.forEach((row) => Object.keys(row).forEach((key) => names.add(key)));
  return [...names].slice(0, 20);
}

function numericPoints(value: unknown): readonly (readonly [number, number])[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((point) =>
    Array.isArray(point) && point.length >= 2 && point.every((entry) => typeof entry === "number" && Number.isFinite(entry))
      ? [[point[0] as number, point[1] as number] as const]
      : [],
  );
}

function sparkline(points: readonly (readonly [number, number])[], width: number, height: number): string {
  const xs = points.map(([x]) => x);
  const ys = points.map(([, y]) => y);
  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  const minY = Math.min(...ys);
  const maxY = Math.max(...ys);
  const rangeX = maxX - minX || 1;
  const rangeY = maxY - minY || 1;
  return points.map(([x, y]) =>
    `${(((x - minX) / rangeX) * width).toFixed(1)},${(height - ((y - minY) / rangeY) * height).toFixed(1)}`,
  ).join(" ");
}

function pillForCheck(status: string): "success" | "warning" | "danger" | "neutral" {
  if (status === "ok") return "success";
  if (status === "fail") return "danger";
  if (status === "warn") return "warning";
  return "neutral";
}

function toneForValue(value: unknown): "positive" | "warning" | "danger" | "default" {
  const tone = processTone(displayValue(value));
  return tone === "success" ? "positive" : tone === "danger" ? "danger" : tone === "warning" ? "warning" : "default";
}

export function RenderedRegion({ children, span }: { readonly children: ComponentChildren; readonly span: number }) {
  return <div class="process-rendered-region" style={{ gridColumn: `span ${span}` }}>{children}</div>;
}
