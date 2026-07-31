import { useEffect, useMemo, useRef, useState } from "preact/hooks";
import { formatNumber, t } from "../routes/i18n/ontology";
import {
  ONTOLOGY_EDGE_KINDS,
  ontologyKnowledgeGraphSummary,
  type OntologyKnowledgeEdgeKind,
  type OntologyKnowledgeGraph,
  type OntologyKnowledgeNode,
} from "./ontology-knowledge-graph.model";
import { ONTOLOGY_NODE_STYLES } from "./ontology-knowledge-graph.renderer";
import { useOntologyKnowledgeGraphController } from "./use-ontology-knowledge-graph-controller";

export function OntologyKnowledgeGraphExplorer({ graph }: { readonly graph: OntologyKnowledgeGraph }) {
  const shellRef = useRef<HTMLElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [fullscreen, setFullscreen] = useState(false);
  const [enabledEdges, setEnabledEdges] = useState<ReadonlySet<OntologyKnowledgeEdgeKind>>(
    () => new Set(ONTOLOGY_EDGE_KINDS),
  );
  const summary = useMemo(() => ontologyKnowledgeGraphSummary(graph), [graph]);
  const selected = graph.nodes.find((node) => node.id === selectedId) ?? null;
  const relationships = selected
    ? graph.edges.filter((edge) => edge.source === selected.id || edge.target === selected.id)
    : [];
  const controller = useOntologyKnowledgeGraphController({
    graph,
    selectedId,
    enabledEdges,
    onSelect: setSelectedId,
  });
  const focusNode = (id: string) => {
    setSelectedId(id);
    controller.focusNode(id);
  };

  useEffect(() => {
    const sync = () => setFullscreen(document.fullscreenElement === shellRef.current);
    document.addEventListener("fullscreenchange", sync);
    return () => document.removeEventListener("fullscreenchange", sync);
  }, []);

  const findNode = () => {
    const normalized = searchRef.current?.value.trim().toLowerCase() ?? "";
    if (!normalized) return;
    const match = graph.nodes.find((node) => node.label.toLowerCase() === normalized)
      ?? graph.nodes.find((node) => node.label.toLowerCase().includes(normalized));
    if (match) focusNode(match.id);
  };
  const toggleEdge = (kind: OntologyKnowledgeEdgeKind, checked: boolean) => {
    setEnabledEdges((current) => {
      const next = new Set(current);
      if (checked) next.add(kind); else next.delete(kind);
      return next;
    });
  };
  const toggleFullscreen = async () => {
    const shell = shellRef.current;
    if (!shell) return;
    if (document.fullscreenElement) await document.exitFullscreen();
    else await shell.requestFullscreen({ navigationUI: "hide" });
    window.setTimeout(controller.fit, 30);
  };

  return (
    <section class="ontology-knowledge-shell" ref={shellRef} aria-label={t("ontology.map.explorerLabel")}>
      <div class="ontology-knowledge-toolbar">
        <div class="ontology-knowledge-tools">
          <label>
            <span class="sr-only">{t("ontology.map.search")}</span>
            <input
              ref={searchRef}
              type="search"
              list="ontology-knowledge-node-list"
              value={query}
              placeholder={t("ontology.map.searchPlaceholder")}
              aria-label={t("ontology.map.search")}
              onInput={(event) => setQuery(event.currentTarget.value)}
              onKeyDown={(event) => { if (event.key === "Enter") findNode(); }}
            />
          </label>
          <datalist id="ontology-knowledge-node-list">
            {graph.nodes.map((node) => <option key={node.id} value={node.label} />)}
          </datalist>
          <button type="button" onClick={findNode}>{t("ontology.map.find")}</button>
          <button type="button" class="is-icon" onClick={controller.zoomIn} aria-label={t("ontology.map.zoomIn")} title={t("ontology.map.zoomIn")}>+</button>
          <button type="button" class="is-icon" onClick={controller.zoomOut} aria-label={t("ontology.map.zoomOut")} title={t("ontology.map.zoomOut")}>-</button>
          <button type="button" onClick={() => { controller.fit(); setSelectedId(null); }}>{t("ontology.map.fit")}</button>
          <button type="button" onClick={() => void toggleFullscreen()} aria-pressed={fullscreen}>
            {t(fullscreen ? "ontology.map.exitFullscreen" : "ontology.map.fullscreen")}
          </button>
        </div>
        <div class="ontology-knowledge-filters" aria-label={t("ontology.map.relationshipFilters")}>
          {ONTOLOGY_EDGE_KINDS.map((kind) => (
            <label key={kind}>
              <input
                type="checkbox"
                checked={enabledEdges.has(kind)}
                onChange={(event) => toggleEdge(kind, event.currentTarget.checked)}
              />
              {t(`ontology.map.edgeKind.${kind}`)}
            </label>
          ))}
        </div>
      </div>

      <div class="ontology-knowledge-workbench">
        <div class="ontology-knowledge-viewport" ref={controller.viewportRef}>
          <canvas
            ref={controller.canvasRef}
            role="img"
            tabIndex={0}
            aria-label={t("ontology.map.canvasDescription", {
              nodes: summary.nodes,
              edges: summary.edges,
            })}
          />
          <div class="ontology-knowledge-type-legend" aria-label={t("ontology.map.nodeTypeColors")}>
            {Object.entries(ONTOLOGY_NODE_STYLES).map(([kind, style]) => (
              <span key={kind}><i style={`background:${style.fill}`} />{style.label}</span>
            ))}
          </div>
          <div class="ontology-knowledge-overlay">
            <span><i class="is-small" />{t("ontology.map.lowDegree")}</span>
            <span><i class="is-large" />{t("ontology.map.highDegree")}</span>
            <span>{t("ontology.map.communityHint", { count: summary.communities })}</span>
          </div>
        </div>
        <KnowledgeInspector
          graph={graph}
          selected={selected}
          relationships={relationships}
          onFocus={focusNode}
        />
      </div>
      <footer class="ontology-knowledge-footer">
        <span>{t("ontology.map.footer")}</span>
        <code>{graph.generatedFrom}</code>
      </footer>
    </section>
  );
}

function KnowledgeInspector({
  graph,
  selected,
  relationships,
  onFocus,
}: {
  readonly graph: OntologyKnowledgeGraph;
  readonly selected: OntologyKnowledgeNode | null;
  readonly relationships: readonly OntologyKnowledgeGraph["edges"][number][];
  readonly onFocus: (id: string) => void;
}) {
  const summary = ontologyKnowledgeGraphSummary(graph);
  if (!selected) {
    return (
      <aside class="ontology-knowledge-inspector" aria-live="polite">
        <span class="badge">{t("ontology.map.communityGraph")}</span>
        <h3>{t("ontology.map.catalogNodes", { count: formatNumber(summary.nodes) })}</h3>
        <p>{t("ontology.map.inspectorDefault", { count: summary.communities })}</p>
        <dl>
          <div><dt>{t("ontology.map.topHub")}</dt><dd><code>{summary.topHub?.label ?? "-"}</code> - {formatNumber(summary.topHub?.degree ?? 0)}</dd></div>
          <div><dt>{t("ontology.map.layout")}</dt><dd>{t("ontology.map.layoutValue")}</dd></div>
          <div><dt>{t("ontology.map.relationships")}</dt><dd>{formatNumber(summary.edges)}</dd></div>
          <div><dt>{t("ontology.map.interaction")}</dt><dd>{t("ontology.map.interactionValue")}</dd></div>
        </dl>
      </aside>
    );
  }
  const neighborIds = new Set([selected.id]);
  for (const edge of relationships) {
    neighborIds.add(edge.source);
    neighborIds.add(edge.target);
  }
  const nodesById = new Map(graph.nodes.map((node) => [node.id, node]));
  return (
    <aside class="ontology-knowledge-inspector" aria-live="polite">
      <span class="badge">{t("ontology.map.knowledgeNode")}</span>
      <h3><code>{selected.label}</code></h3>
      <p>{selected.detail}</p>
      <dl>
        <div><dt>{t("ontology.map.ontologyKind")}</dt><dd>{ONTOLOGY_NODE_STYLES[selected.kind].label}</dd></div>
        <div><dt>{t("ontology.map.community")}</dt><dd>C{selected.community}</dd></div>
        <div><dt>{t("ontology.map.evidenceState")}</dt><dd>{t(selected.kind === "object_type" ? "ontology.map.declared" : "ontology.map.catalogBacked")}</dd></div>
        <div><dt>{t("ontology.map.degree")}</dt><dd>{formatNumber(selected.degree)}</dd></div>
        <div><dt>{t("ontology.map.relationships")}</dt><dd>{formatNumber(relationships.length)}</dd></div>
        <div><dt>{t("ontology.map.neighborhood")}</dt><dd>{formatNumber(neighborIds.size)}</dd></div>
      </dl>
      <h4>{t("ontology.map.neighbors")}</h4>
      <ul>
        {relationships.slice(0, 28).map((edge) => {
          const otherId = edge.source === selected.id ? edge.target : edge.source;
          return (
            <li key={edge.id}>
              <button type="button" onClick={() => onFocus(otherId)}>
                {edge.label} -&gt; {nodesById.get(otherId)?.label ?? otherId}
              </button>
            </li>
          );
        })}
      </ul>
    </aside>
  );
}
