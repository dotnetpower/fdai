import {
  ontologyKnowledgeGraphSummary,
  type OntologyKnowledgeGraph,
} from "../components/ontology-knowledge-graph.model";
import { OntologyKnowledgeGraphExplorer } from "../components/ontology-knowledge-graph";
import { formatNumber, t } from "./i18n/ontology";

export function OntologyKnowledgeMap({ graph }: { readonly graph: OntologyKnowledgeGraph }) {
  const summary = ontologyKnowledgeGraphSummary(graph);
  const stats = [
    ["nodes", summary.nodes],
    ["relationships", summary.edges],
    ["communities", summary.communities],
    ["actions", summary.actions],
    ["agents", summary.agents],
  ] as const;
  return (
    <section class="ontology-knowledge-map" aria-labelledby="ontology-map-title">
      <header class="ontology-knowledge-map-header">
        <div>
          <h3 id="ontology-map-title">{t("ontology.map.title")}</h3>
          <p>{t("ontology.map.description")}</p>
        </div>
        <div class="ontology-knowledge-source">
          <strong>{t("ontology.map.sourceTitle")}</strong>
          <code>{graph.ontologyReleaseDigest}</code>
        </div>
      </header>
      <dl class="ontology-knowledge-summary" aria-label={t("ontology.map.summaryLabel")}>
        {stats.map(([key, value]) => (
          <div key={key}><dd>{formatNumber(value)}</dd><dt>{t(`ontology.map.${key}`)}</dt></div>
        ))}
      </dl>
      <OntologyKnowledgeGraphExplorer graph={graph} />
    </section>
  );
}
