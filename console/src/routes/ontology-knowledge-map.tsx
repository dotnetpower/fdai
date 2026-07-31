import { useEffect, useState } from "preact/hooks";
import {
  decodeOntologyKnowledgeGraph,
  ontologyKnowledgeGraphSummary,
  type OntologyKnowledgeGraph,
} from "../components/ontology-knowledge-graph.model";
import { OntologyKnowledgeGraphExplorer } from "../components/ontology-knowledge-graph";
import { AsyncBoundary, type AsyncState } from "../components/ui";
import { formatNumber, t } from "./i18n/ontology";

export async function loadOntologyKnowledgeGraph(): Promise<OntologyKnowledgeGraph> {
  const module = await import("../generated/ontology-knowledge-graph.json");
  return decodeOntologyKnowledgeGraph(module.default);
}

export function OntologyKnowledgeMap() {
  const [state, setState] = useState<AsyncState<OntologyKnowledgeGraph>>({ status: "loading" });
  useEffect(() => {
    let cancelled = false;
    loadOntologyKnowledgeGraph().then(
      (graph) => { if (!cancelled) setState({ status: "ready", data: graph }); },
      (error: unknown) => {
        if (!cancelled) setState({
          status: "error",
          message: error instanceof Error ? error.message : String(error),
        });
      },
    );
    return () => { cancelled = true; };
  }, []);

  return (
    <AsyncBoundary state={state} resourceLabel={t("ontology.map.loadingLabel")}>
      {(graph) => <OntologyKnowledgeMapContent graph={graph} />}
    </AsyncBoundary>
  );
}

function OntologyKnowledgeMapContent({ graph }: { readonly graph: OntologyKnowledgeGraph }) {
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
          <code>{graph.generatedFrom}</code>
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
