/**
 * Right-column focus panel for the ontology graph - description,
 * property list, and grouped in/out edges for the currently selected
 * (or hover-highlighted) type.
 *
 * SRP: presentation only. All data (`nodes`, `edges`, `neighbourhood`)
 * flows in from the parent; nothing here fetches or mutates state.
 * Extracted from `ontology-graph.tsx` so the main component stays a
 * canvas orchestrator.
 */

import { shortCard, type OntologyEdge, type OntologyNode } from "./ontology-graph.types";
import { formatNumber, t } from "../routes/i18n/ontology";

export function FocusCard({
  name,
  nodes,
  edges,
  neighbourhood,
}: {
  readonly name: string;
  readonly nodes: readonly OntologyNode[];
  readonly edges: readonly OntologyEdge[];
  readonly neighbourhood: ReadonlySet<string>;
}) {
  const node = nodes.find((n) => n.name === name);
  if (!node) return null;
  const outgoing = edges.filter((e) => e.from_type === name);
  const incoming = edges.filter((e) => e.to_type === name);
  return (
    <aside class="ontology-focus" aria-live="polite">
      <header class="ontology-focus-head">
        <span class="ontology-focus-name">{node.name}</span>
        <span class="ontology-focus-key muted">{t("ontology.graph.key", { key: node.key })}</span>
      </header>
      {node.description ? (
        <p class="ontology-focus-desc muted">{node.description}</p>
      ) : null}
      {node.properties.length > 0 ? (
        <section>
          <h4 class="ontology-focus-h">
            {t("ontology.graph.propertiesCount", { count: formatNumber(node.properties.length) })}
          </h4>
          <ul class="ontology-focus-list">
            {node.properties.map((p) => (
              <li key={p}>{p}</li>
            ))}
          </ul>
        </section>
      ) : null}
      {outgoing.length > 0 ? (
        <section>
          <h4 class="ontology-focus-h">{t("ontology.graph.outgoingCount", { count: formatNumber(outgoing.length) })}</h4>
          <ul class="ontology-focus-list">
            {outgoing.map((e, i) => (
              <li key={`${e.from_type}:${e.name}:${e.to_type}:${i}`}>
                <code>{e.name}</code>{" "}
                <span class="muted">
                  {shortCard(e.cardinality)} → {e.to_type}
                </span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
      {incoming.length > 0 ? (
        <section>
          <h4 class="ontology-focus-h">{t("ontology.graph.incomingCount", { count: formatNumber(incoming.length) })}</h4>
          <ul class="ontology-focus-list">
            {incoming.map((e, i) => (
              <li key={`${e.from_type}:${e.name}:${e.to_type}:${i}`}>
                <span class="muted">
                  {e.from_type} {shortCard(e.cardinality)} →
                </span>{" "}
                <code>{e.name}</code>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
      <div class="ontology-focus-neighbours">
        {t("ontology.graph.directNeighbors", { count: formatNumber(Math.max(0, neighbourhood.size - 1)) })}
      </div>
    </aside>
  );
}
