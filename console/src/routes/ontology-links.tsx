import type { OntologyEdge, OntologyNode } from "../components/ontology-graph";
import { formatNumber, t } from "./i18n/ontology";
import { ontologyDeclarationHref } from "./ontology-object-type-detail";

export function OntologyLinksView({
  names,
  nodes,
  edges,
  selectedName,
}: {
  readonly names: readonly string[];
  readonly nodes: readonly OntologyNode[];
  readonly edges: readonly OntologyEdge[];
  readonly selectedName: string | null;
}) {
  const selectedEdges = edges.filter((edge) => edge.name === selectedName);
  const selected = selectedEdges[0] ?? null;
  const invalidSelection = selectedName !== null && !names.includes(selectedName);
  const nodesByName = new Map(nodes.map((node) => [node.name, node]));

  return (
    <div class="ontology-browser-layout ontology-links-view">
      <aside class="ontology-type-sidebar">
        <section>
          <h3>{t("ontology.links.directoryTitle")} <span>{formatNumber(names.length)}</span></h3>
          {names.length === 0 ? <p class="muted">{t("ontology.common.noneRegistered")}</p> : (
            <ul>
              {names.map((name) => (
                <li key={name}>
                  <a
                    href={ontologyDeclarationHref("link-types", name)}
                    class={name === selectedName ? "is-active" : undefined}
                    aria-current={name === selectedName ? "page" : undefined}
                  >
                    <span class="ontology-link-glyph" aria-hidden="true" />
                    <code>{name}</code>
                  </a>
                </li>
              ))}
            </ul>
          )}
        </section>
      </aside>

      <section class="ontology-link-stage">
        {selected ? (
          <>
            <header class="ontology-view-head">
              <div>
                <span class="eyebrow">{t("ontology.links.kind")}</span>
                <h3><code>{selected.name}</code></h3>
                <p>{selected.description ?? t("ontology.links.noDescription")}</p>
              </div>
              <span class="badge">{t(selectedEdges.length === 1
                ? "ontology.links.usageCount"
                : "ontology.links.usageCountPlural", { count: formatNumber(selectedEdges.length) })}</span>
            </header>

            <div class="ontology-link-workspace">
              <div class="ontology-link-usages" aria-label={t("ontology.links.endpointUsages", { name: selected.name })}>
                {selectedEdges.map((edge, index) => (
                  <article class="ontology-link-usage" key={`${edge.from_type}-${edge.to_type}-${index}`}>
                    <a
                      class="ontology-endpoint"
                      href={ontologyDeclarationHref("object-types", edge.from_type)}
                    >
                      <span>{t("ontology.links.fromObject")}</span>
                      <strong>{edge.from_type}</strong>
                      <small>{nodesByName.get(edge.from_type)?.description ?? t("ontology.links.openNeighborhood")}</small>
                    </a>
                    <div class="ontology-link-signature" aria-label={`${edge.name} ${edge.cardinality}`}>
                      <span>{edge.cardinality}</span>
                      <strong>{edge.name}</strong>
                      <i aria-hidden="true">→</i>
                    </div>
                    <a
                      class="ontology-endpoint"
                      href={ontologyDeclarationHref("object-types", edge.to_type)}
                    >
                      <span>{t("ontology.links.toObject")}</span>
                      <strong>{edge.to_type}</strong>
                      <small>{nodesByName.get(edge.to_type)?.description ?? t("ontology.links.openNeighborhood")}</small>
                    </a>
                  </article>
                ))}
              </div>

              <aside class="ontology-link-inspector" aria-label={t("ontology.links.propertiesLabel")}>
                <h4>{t("ontology.links.contract")}</h4>
                <dl>
                  <dt>{t("ontology.links.cardinality")}</dt><dd><code>{selected.cardinality}</code></dd>
                  <dt>{t("ontology.links.causal")}</dt><dd>{selected.is_causal ? t("ontology.common.yes") : t("ontology.common.no")}</dd>
                  <dt>{t("ontology.links.transitive")}</dt><dd>{selected.is_transitive ? t("ontology.common.yes") : t("ontology.common.no")}</dd>
                  <dt>{t("ontology.links.temporalOrder")}</dt><dd>{selected.temporal_order ? t("ontology.common.yes") : t("ontology.common.no")}</dd>
                  <dt>{t("ontology.links.forwardRole")}</dt><dd><code>{selected.forward_role ?? t("ontology.common.noneDeclared")}</code></dd>
                  <dt>{t("ontology.links.reverseRole")}</dt><dd><code>{selected.reverse_role ?? t("ontology.common.noneDeclared")}</code></dd>
                  <dt>{t("ontology.links.semanticTraits")}</dt><dd>{selected.semantic_traits.length > 0 ? selected.semantic_traits.map((trait) => <code key={trait}>{trait}</code>) : t("ontology.common.noneDeclared")}</dd>
                  <dt>{t("ontology.links.endpointPairs")}</dt><dd>{formatNumber(selectedEdges.length)}</dd>
                </dl>
                <h4>{t("ontology.links.usedBy")}</h4>
                <ul>
                  {selectedEdges.map((edge, index) => (
                    <li key={`${edge.from_type}-${edge.to_type}-${index}`}>
                      <code>{edge.from_type}</code>
                      <span>→</span>
                      <code>{edge.to_type}</code>
                    </li>
                  ))}
                </ul>
              </aside>
            </div>
          </>
        ) : invalidSelection ? (
          <div class="state-block state-unavailable" role="alert">
            {t("ontology.links.invalid", { name: selectedName ?? "" })}
          </div>
        ) : (
          <div class="empty-state">{t("ontology.links.choose")}</div>
        )}
      </section>
    </div>
  );
}
