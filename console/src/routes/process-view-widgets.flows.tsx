import { displayValue, type RenderedWidget } from "./processes.model";
import { asRecord, asRows, boundedRatio, finiteNumber, numericPoints, sparkline, type DataRow } from "./process-view-widget-utils";

export const FLOW_WIDGET_TYPES = new Set([
  "funnel",
  "sankey",
  "treemap",
  "retention",
  "flame_graph",
  "split_graph",
]);

interface FlameFrame {
  readonly name: string;
  readonly value: unknown;
  readonly depth: number;
}

export function flattenFlameFrames(
  roots: unknown,
  maxDepth = 8,
  maxFrames = 200,
): readonly FlameFrame[] {
  const output: FlameFrame[] = [];
  const stack = [...asRows(roots)].reverse().map((node) => ({ node, depth: 0 }));
  while (stack.length > 0 && output.length < maxFrames) {
    const current = stack.pop();
    if (!current) break;
    output.push({
      name: displayValue(current.node["name"]),
      value: current.node["value"],
      depth: current.depth,
    });
    if (current.depth >= maxDepth) continue;
    const children = asRows(current.node["children"]);
    for (let index = children.length - 1; index >= 0; index -= 1) {
      const child = children[index];
      if (child) stack.push({ node: child, depth: current.depth + 1 });
    }
  }
  return output;
}

export function FlowWidget({ widget }: { readonly widget: RenderedWidget }) {
  if (widget.type === "funnel") return <FunnelWidget widget={widget} />;
  if (widget.type === "sankey") return <SankeyWidget widget={widget} />;
  if (widget.type === "treemap") return <TreemapWidget widget={widget} />;
  if (widget.type === "retention") return <RetentionWidget widget={widget} />;
  if (widget.type === "flame_graph") return <FlameGraphWidget widget={widget} />;
  return <SplitGraphWidget widget={widget} />;
}

function FunnelWidget({ widget }: { readonly widget: RenderedWidget }) {
  const stages = asRows(widget.data["stages"]);
  return <section class="process-widget-section" aria-labelledby={`${widget.id}-title`}><h3 id={`${widget.id}-title`}>{widget.title}</h3><ol class="report-funnel">{stages.map((stage, index) => {
    const ratio = boundedRatio(stage["conversion_ratio"]);
    return <li key={`${displayValue(stage["label"])}-${index}`} style={{ width: `${Math.max(18, (ratio ?? 0) * 100)}%` }}><span>{displayValue(stage["label"])}</span><strong>{displayValue(stage["value"])}</strong><small>{ratio === null ? "-" : `${(ratio * 100).toFixed(1)}%`}</small></li>;
  })}</ol>{stages.length === 0 ? <p class="muted small">No funnel stages.</p> : null}</section>;
}

function SankeyWidget({ widget }: { readonly widget: RenderedWidget }) {
  const links = asRows(widget.data["links"]);
  return <section class="process-widget-section" aria-labelledby={`${widget.id}-title`}><h3 id={`${widget.id}-title`}>{widget.title}</h3><ol class="report-flow-list">{links.map((link, index) => <li key={`${displayValue(link["source"])}-${displayValue(link["target"])}-${index}`}><span>{displayValue(link["source"])}</span><span aria-hidden="true">&rarr;</span><span>{displayValue(link["target"])}</span><strong>{displayValue(link["value"])}</strong></li>)}</ol>{links.length === 0 ? <p class="muted small">No flow links.</p> : null}</section>;
}

function TreemapWidget({ widget }: { readonly widget: RenderedWidget }) {
  const tiles = asRows(widget.data["tiles"]);
  const positiveValues = tiles.map((tile) => Math.max(0, finiteNumber(tile["value"]) ?? 0));
  const maximum = Math.max(1, ...positiveValues);
  return <section class="process-widget-section" aria-labelledby={`${widget.id}-title`}><h3 id={`${widget.id}-title`}>{widget.title}</h3><div class="report-treemap">{tiles.map((tile, index) => <article key={`${displayValue(tile["label"])}-${index}`} style={{ flexGrow: 1 + (positiveValues[index] ?? 0) / maximum * 4 }}><span>{displayValue(tile["group"])}</span><strong>{displayValue(tile["label"])}</strong><small>{displayValue(tile["value"])}</small></article>)}</div>{tiles.length === 0 ? <p class="muted small">No treemap tiles.</p> : null}</section>;
}

function RetentionWidget({ widget }: { readonly widget: RenderedWidget }) {
  const periods = Array.isArray(widget.data["periods"]) ? widget.data["periods"].slice(0, 60) : [];
  const rows = asRows(widget.data["rows"]);
  return <section class="process-widget-section" aria-labelledby={`${widget.id}-title`}><h3 id={`${widget.id}-title`}>{widget.title}</h3><div class="scroll"><table class="report-matrix"><caption class="sr-only">{widget.title}</caption><thead><tr><th scope="col">Cohort</th>{periods.map((period, index) => <th scope="col" key={`${displayValue(period)}-${index}`}>{displayValue(period)}</th>)}</tr></thead><tbody>{rows.map((row, rowIndex) => {
    const values = Array.isArray(row["values"]) ? row["values"].slice(0, periods.length) : [];
    return <tr key={`${displayValue(row["cohort"])}-${rowIndex}`}><th scope="row">{displayValue(row["cohort"])}</th>{values.map((value, index) => <td key={index} style={{ "--cell-intensity": boundedRatio(value) ?? 0 }}>{displayValue(value)}</td>)}</tr>;
  })}</tbody></table></div>{rows.length === 0 ? <p class="muted small">No retention cohorts.</p> : null}</section>;
}

function FlameGraphWidget({ widget }: { readonly widget: RenderedWidget }) {
  const frames = flattenFlameFrames(widget.data["roots"]);
  const maximum = Math.max(1, ...frames.map((frame) => Math.max(0, finiteNumber(frame.value) ?? 0)));
  return <section class="process-widget-section" aria-labelledby={`${widget.id}-title`}><h3 id={`${widget.id}-title`}>{widget.title}</h3><ol class="report-flame">{frames.map((frame, index) => <li key={`${frame.name}-${index}`} style={{ marginInlineStart: `${Math.min(frame.depth, 8) * 16}px`, width: `${Math.max(12, ((finiteNumber(frame.value) ?? 0) / maximum) * 100)}%` }}><span>{frame.name}</span><strong>{displayValue(frame.value)}</strong></li>)}</ol>{frames.length === 0 ? <p class="muted small">No flame frames.</p> : null}</section>;
}

function SplitGraphWidget({ widget }: { readonly widget: RenderedWidget }) {
  const panels = asRows(widget.data["panels"]);
  return <section class="process-widget-section" aria-labelledby={`${widget.id}-title`}><h3 id={`${widget.id}-title`}>{widget.title}</h3><div class="report-small-multiples">{panels.map((panel, index) => {
    const points = numericPoints(panel["points"]);
    return <article key={`${displayValue(panel["label"])}-${index}`}><strong>{displayValue(panel["label"])}</strong><svg viewBox="0 0 160 48" role="img" aria-label={`${displayValue(panel["label"])} trend`}><polyline points={sparkline(points, 160, 48)} fill="none" stroke="currentColor" stroke-width="2" /></svg><LabelList labels={asRecord(panel["labels"])} /></article>;
  })}</div>{panels.length === 0 ? <p class="muted small">No split graph panels.</p> : null}</section>;
}

function LabelList({ labels }: { readonly labels: DataRow }) {
  const entries = Object.entries(labels);
  return entries.length === 0 ? null : <span class="muted small">{entries.map(([key, value]) => `${key}=${displayValue(value)}`).join(", ")}</span>;
}
