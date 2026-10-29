import { useLayoutEffect, useRef, useState } from "preact/hooks";
import { getLocale } from "../i18n";
import { t } from "./i18n/governance";
import { guidanceText, type WaraGuidance } from "./wara-guidance.model";

type Diagram = WaraGuidance["diagram"];
interface Box { readonly x: number; readonly y: number; readonly width: number; readonly height: number }
interface Geometry { readonly width: number; readonly height: number; readonly boxes: Readonly<Record<string, Box>> }

export function guidanceNodePresentation(diagram: Diagram, node: Diagram["nodes"][number], locale: string) {
  const detail = guidanceText(node.detail, locale);
  const fullExplanation = detail.length > 220;
  const relationship = diagram.edges.find((edge) => edge.to === node.id) ?? diagram.edges.find((edge) => edge.from === node.id);
  return {
    fullExplanation,
    primaryDetail: fullExplanation && relationship ? guidanceText(relationship.label, locale) : detail,
    detail,
  };
}

export function guidanceColumns(diagram: Diagram): readonly (readonly Diagram["nodes"][number][])[] {
  const ranks = new Map(diagram.nodes.map((node) => [node.id, 0]));
  // Edge style changes meaning, never authority; both styles need a legible directed layout.
  for (let pass = 0; pass < diagram.nodes.length; pass += 1) {
    let changed = false;
    for (const edge of diagram.edges) {
      const next = Math.min(2, (ranks.get(edge.from) ?? 0) + 1);
      if (next > (ranks.get(edge.to) ?? 0)) { ranks.set(edge.to, next); changed = true; }
    }
    if (!changed) break;
  }
  for (const node of diagram.nodes) {
    const targets = diagram.edges.filter((edge) => edge.from === node.id).map((edge) => ranks.get(edge.to) ?? 0);
    if (targets.length > 0) ranks.set(node.id, Math.max(ranks.get(node.id) ?? 0, Math.min(...targets) - 1));
  }
  return [0, 1, 2].map((rank) => diagram.nodes.filter((node) => ranks.get(node.id) === rank)).filter((column) => column.length > 0);
}

export function guidanceEdgePath(from: Box, to: Box, index: number, narrow: boolean, ports?: { readonly startY: number; readonly endY: number }): string {
  const startY = ports?.startY ?? from.y + from.height / 2;
  const endY = ports?.endY ?? to.y + to.height / 2;
  if (!narrow && from.x + from.width < to.x) {
    const startX = from.x + from.width;
    if (to.x - startX > from.width) {
      return `M ${startX} ${startY} H ${startX + 12} V ${4 + index * 2} H ${to.x - 12} V ${endY} H ${to.x - 3}`;
    }
    const lane = startX + 10 + index * 2;
    return `M ${startX} ${startY} H ${lane} V ${endY} H ${to.x - 3}`;
  }
  const lane = narrow ? 10 + index * 2 : Math.min(from.x, to.x) - 10 - index * 2;
  return `M ${from.x} ${startY} H ${lane} V ${endY} H ${to.x - 3}`;
}

export function WaraGuidanceDiagram({ diagram, expanded, onExpand }: {
  readonly diagram: Diagram;
  readonly expanded: boolean;
  readonly onExpand: () => void;
}) {
  const rootRef = useRef<HTMLDivElement>(null);
  const explanationsRef = useRef<HTMLElement>(null);
  const [geometry, setGeometry] = useState<Geometry | null>(null);
  const locale = getLocale();
  const columns = guidanceColumns(diagram);
  const marker = `wara-arrow-${diagram.id}`;
  const extendedNodes = diagram.nodes.filter((node) => guidanceNodePresentation(diagram, node, locale).fullExplanation);
  const explanationsId = `${diagram.id}-explanations`;

  function openExplanation(nodeId: string): void {
    const explanations = explanationsRef.current;
    if (!explanations) return;
    const target = explanations.querySelector<HTMLElement>(`[data-guidance-explanation="${nodeId}"]`);
    target?.focus({ preventScroll: true });
    target?.scrollIntoView({ block: "start" });
  }
  useLayoutEffect(() => {
    const root = rootRef.current;
    if (!root) return;
    const measure = () => {
      const origin = root.getBoundingClientRect();
      const boxes = Object.fromEntries(Array.from(root.querySelectorAll<HTMLElement>("[data-guidance-node]")).map((node) => {
        const box = node.getBoundingClientRect();
        return [node.dataset["guidanceNode"], { x: box.left - origin.left, y: box.top - origin.top, width: box.width, height: box.height }];
      }));
      setGeometry({ width: root.clientWidth, height: root.clientHeight, boxes });
    };
    const observer = new ResizeObserver(measure);
    observer.observe(root);
    root.querySelectorAll("[data-guidance-node]").forEach((node) => observer.observe(node));
    measure();
    return () => observer.disconnect();
  }, [diagram, locale]);

  return (
    <>
    <figure class="wara-guidance-figure" aria-labelledby={`${diagram.id}-title`} aria-describedby={`${diagram.id}-description`}>
      <header class="wara-guidance-figure-head">
        <div><p class="wara-guidance-eyebrow">{t("governance.rules.wara.guidance.referenceFigure")}</p><h4 id={`${diagram.id}-title`}>{guidanceText(diagram.title, locale)}</h4></div>
        <button type="button" class="btn" aria-pressed={expanded} onClick={onExpand}>{t(`governance.rules.wara.guidance.${expanded ? "compact" : "expand"}`)}</button>
      </header>
      <div class="wara-guidance-graph" ref={rootRef} style={{ "--guidance-columns": columns.length }}>
        {geometry ? <svg class="wara-guidance-connectors" viewBox={`0 0 ${geometry.width} ${geometry.height}`} width={geometry.width} height={geometry.height} aria-hidden="true" role="presentation" focusable="false">
          <defs><marker id={marker} viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="currentColor" /></marker></defs>
          {diagram.edges.map((edge, index) => {
            const from = geometry.boxes[edge.from];
            const to = geometry.boxes[edge.to];
            const outgoing = diagram.edges.filter((item) => item.from === edge.from);
            const incoming = diagram.edges.filter((item) => item.to === edge.to);
            return from && to ? <path key={`${edge.from}-${edge.to}-${index}`} data-guidance-edge={edge.style} data-edge-from={edge.from} data-edge-to={edge.to} d={guidanceEdgePath(from, to, index, geometry.width < 620, {
              startY: from.y + from.height * (outgoing.indexOf(edge) + 1) / (outgoing.length + 1),
              endY: to.y + to.height * (incoming.indexOf(edge) + 1) / (incoming.length + 1),
            })} fill="none" stroke="currentColor" stroke-width="2" stroke-dasharray={edge.style === "dashed" ? "5 5" : undefined} marker-end={`url(#${marker})`} /> : null;
          })}
        </svg> : null}
        {columns.map((column, index) => <div class="wara-guidance-graph-column" key={index}>
          {column.map((node) => {
            const presentation = guidanceNodePresentation(diagram, node, locale);
            return <div key={node.id} class="wara-guidance-node" data-guidance-node={node.id} data-role={node.role}>
            <span class="wara-guidance-node-role sr-only">{t(`governance.rules.wara.guidance.role.${node.role}`)}</span>
            <strong>{guidanceText(node.label, locale)}</strong>
            <p>{presentation.primaryDetail}</p>
            {presentation.fullExplanation ? <button type="button" class="wara-guidance-node-more" aria-controls={explanationsId} onClick={() => openExplanation(node.id)}>{t("governance.rules.wara.guidance.fullExplanation")}</button> : null}
          </div>;
          })}
        </div>)}
      </div>
      <figcaption>
        <p id={`${diagram.id}-description`}>{guidanceText(diagram.description, locale)}</p>
        <p class="wara-guidance-legend"><span>{t("governance.rules.wara.guidance.solid")}</span><span>{t("governance.rules.wara.guidance.dashed")}</span></p>
      </figcaption>
    </figure>
        {extendedNodes.length > 0 ? <section id={explanationsId} class="wara-guidance-explanations" ref={explanationsRef} aria-labelledby={`${explanationsId}-title`}>
          <h3 id={`${explanationsId}-title`}>{t("governance.rules.wara.guidance.fullExplanations")}</h3>
          <dl>{extendedNodes.map((node) => <div key={node.id}>
            <dt>{guidanceText(node.label, locale)}</dt>
            <dd tabIndex={-1} data-guidance-explanation={node.id}>{guidanceText(node.detail, locale)}</dd>
          </div>)}</dl>
        </section> : null}
        <details class="wara-guidance-relationships">
          <summary>{t("governance.rules.wara.guidance.relationships")}</summary>
          <ol>{diagram.edges.map((edge, index) => <li key={index}>
            <strong>{guidanceText(diagram.nodes.find((node) => node.id === edge.from)!.label, locale)}</strong>
            {" → "}<strong>{guidanceText(diagram.nodes.find((node) => node.id === edge.to)!.label, locale)}</strong>
            {`: ${guidanceText(edge.label, locale)} (${t(`governance.rules.wara.guidance.${edge.style === "dashed" ? "conditional" : "connection"}`)})`}
          </li>)}</ol>
        </details>
    </>
  );
}
