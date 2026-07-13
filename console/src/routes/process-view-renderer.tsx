import type { ComponentChildren } from "preact";
import { ErrorState, KpiCard, KpiGrid, StatusPill } from "../components/ui";
import { displayValue, processTone, type RenderedWidget } from "./processes.model";

export function ProcessWidget({ widget }: { readonly widget: RenderedWidget }) {
  if (widget.error) return <ErrorState message={`${widget.title}: ${widget.error}`} />;
  if (widget.type === "query_value") {
    return (
      <KpiCard
        label={widget.title}
        value={displayValue(widget.data["value"])}
        tone={toneForValue(widget.data["value"])}
      />
    );
  }
  if (widget.type === "check_status") return <CheckStatusWidget widget={widget} />;
  if (widget.type === "table") return <TableWidget widget={widget} />;
  if (widget.type === "list_stream") return <StreamWidget widget={widget} />;
  if (widget.type === "topology_map") return <TopologyWidget widget={widget} />;
  if (widget.type === "group" || widget.type === "tabs") {
    return (
      <section class="process-widget-group">
        <h3>{widget.title}</h3>
        <div class="process-widget-grid">
          {(widget.children ?? []).map((child) => <ProcessWidget key={child.id} widget={child} />)}
        </div>
      </section>
    );
  }
  return <FallbackWidget widget={widget} />;
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
          <thead><tr>{columns.map((column) => <th key={column}>{column}</th>)}</tr></thead>
          <tbody>
            {rows.map((row, index) => (
              <tr key={`${widget.id}-${index}`}>
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
      <div class="process-edge-list muted small">
        {edges.map((edge, index) => (
          <span key={`${widget.id}-edge-${index}`}>
            {displayValue(edge["source"])} → {displayValue(edge["target"])} · {displayValue(edge["value"])}
          </span>
        ))}
      </div>
    </section>
  );
}

function FallbackWidget({ widget }: { readonly widget: RenderedWidget }) {
  const rows = Object.entries(widget.data).map(([key, value]) => ({ key, value }));
  return (
    <section class="process-widget-section">
      <h3>{widget.title}</h3>
      <dl class="process-fallback">
        {rows.map(({ key, value }) => <><dt>{key}</dt><dd>{displayValue(value)}</dd></>)}
      </dl>
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

function deriveColumns(rows: readonly Readonly<Record<string, unknown>>[]): readonly string[] {
  const names = new Set<string>();
  rows.forEach((row) => Object.keys(row).forEach((key) => names.add(key)));
  return [...names].slice(0, 20);
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
