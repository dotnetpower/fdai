import { useMemo, useState } from "preact/hooks";
import { formatNumber, t } from "../routes/i18n/ontology";
import type { OntologyEdge, OntologyNode } from "./ontology-graph";
import {
  ONTOLOGY_SEMANTIC_LENSES,
  buildOntologySemanticProjection,
  relationshipsForSemanticNode,
  type OntologySemanticLens,
  type OntologySemanticModel,
  type OntologySemanticRelation,
} from "./ontology-semantic-model";

interface Props {
  readonly model: OntologySemanticModel;
  readonly nodes: readonly OntologyNode[];
  readonly edges: readonly OntologyEdge[];
  readonly releaseDigest: string;
  readonly projectionRevision: string;
}

export function OntologySemanticMap({
  model,
  nodes,
  edges,
  releaseDigest,
  projectionRevision,
}: Props) {
  const projection = useMemo(
    () => buildOntologySemanticProjection(model, nodes, edges),
    [model, nodes, edges],
  );
  const preferred = projection.bands
    .flatMap((band) => band.nodes)
    .find((node) => node.name === "BusinessService")?.name;
  const first = projection.bands.flatMap((band) => band.nodes)[0]?.name ?? null;
  const [selectedName, setSelectedName] = useState<string | null>(preferred ?? first);
  const [lens, setLens] = useState<OntologySemanticLens>("relationship");
  const selected = nodes.find((node) => node.name === selectedName) ?? null;
  const selectedRelations = relationshipsForSemanticNode(projection.relations, selectedName);
  const relationCountByNode = useMemo(() => {
    const counts = new Map<string, number>();
    for (const relation of projection.relations) {
      counts.set(relation.from, (counts.get(relation.from) ?? 0) + 1);
      if (relation.to !== relation.from) {
        counts.set(relation.to, (counts.get(relation.to) ?? 0) + 1);
      }
    }
    return counts;
  }, [projection.relations]);
  const actionTypes = useMemo(
    () => new Set(
      projection.bands
        .find((band) => band.id === "decision_and_learning")
        ?.nodes.map((node) => node.name) ?? [],
    ),
    [projection.bands],
  );
  const actionRelations = useMemo(
    () => projection.relations.filter(
      (relation) => actionTypes.has(relation.from) || actionTypes.has(relation.to),
    ),
    [actionTypes, projection.relations],
  );

  return (
    <section class="ontology-semantic-map" aria-labelledby="ontology-semantic-title">
      <header class="ontology-semantic-header">
        <div>
          <h3 id="ontology-semantic-title">{t("ontology.semantic.title")}</h3>
          <p>{t("ontology.semantic.description")}</p>
        </div>
        <div class="ontology-semantic-source">
          <strong>{t("ontology.semantic.release")}</strong>
          <code>{releaseDigest}</code>
        </div>
      </header>

      <div class="ontology-semantic-lenses" role="group" aria-label={t("ontology.semantic.lenses")}>
        {ONTOLOGY_SEMANTIC_LENSES.map((item) => (
          <button
            key={item}
            type="button"
            aria-pressed={lens === item}
            onClick={() => setLens(item)}
          >
            {t(`ontology.semantic.lens.${item}`)}
          </button>
        ))}
      </div>

      <div class="ontology-semantic-workbench">
        <div class="ontology-semantic-canvas">
          <div class="ontology-semantic-bands">
            {projection.bands.map((band) => (
              <section key={band.id} class={`ontology-semantic-band is-${band.id}`}>
                <header>
                  <div>
                    <span>{t(`ontology.semantic.band.${band.id}`)}</span>
                    <small>{t(`ontology.semantic.bandDescription.${band.id}`)}</small>
                  </div>
                  <strong>{formatNumber(band.nodes.length)}</strong>
                </header>
                <div class="ontology-semantic-nodes">
                  {band.nodes.map((node) => (
                    <button
                      key={node.name}
                      type="button"
                      class={node.name === selectedName ? "is-selected" : undefined}
                      aria-pressed={node.name === selectedName}
                      onClick={() => setSelectedName(node.name)}
                    >
                      <code>{node.name}</code>
                      <span>{formatNumber(relationCountByNode.get(node.name) ?? 0)} {t("ontology.semantic.links")}</span>
                    </button>
                  ))}
                </div>
              </section>
            ))}
          </div>

          {lens === "relationship" ? (
            <RelationList
              relations={selectedName === null
                ? projection.relations
                : [...selectedRelations.outgoing, ...selectedRelations.incoming]}
            />
          ) : null}
          {lens === "state" ? <StateLanes /> : null}
          {lens === "context" ? (
            <ContextStatus releaseDigest={releaseDigest} projectionRevision={projectionRevision} />
          ) : null}
          {lens === "action" ? (
            <RelationList relations={actionRelations} />
          ) : null}
        </div>

        <SemanticInspector
          selected={selected}
          lens={lens}
          incoming={selectedRelations.incoming}
          outgoing={selectedRelations.outgoing}
        />
      </div>
    </section>
  );
}

function RelationList({ relations }: { readonly relations: readonly OntologySemanticRelation[] }) {
  return (
    <section class="ontology-semantic-relations" aria-label={t("ontology.semantic.relationships")}>
      <header>
        <strong>{t("ontology.semantic.relationships")}</strong>
        <span>{formatNumber(relations.length)}</span>
      </header>
      {relations.length === 0 ? (
        <p>{t("ontology.semantic.noRelationships")}</p>
      ) : (
        <ul>
          {relations.map((relation) => (
            <li key={`${relation.from}:${relation.name}:${relation.to}`}>
              <code>{relation.from}</code>
              <span>--{relation.name}--&gt;</span>
              <code>{relation.to}</code>
              <RelationshipFlags relation={relation} />
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function RelationshipFlags({ relation }: { readonly relation: OntologySemanticRelation }) {
  const flags = [
    relation.isCausal ? t("ontology.semantic.causal") : null,
    relation.isTemporal ? t("ontology.semantic.temporal") : null,
    relation.isTransitive ? t("ontology.semantic.transitive") : null,
  ].filter((value): value is string => value !== null);
  return flags.length === 0 ? null : (
    <small class="ontology-semantic-relation-flags">{flags.join(" / ")}</small>
  );
}

function StateLanes() {
  return (
    <section class="ontology-semantic-state" aria-label={t("ontology.semantic.stateLanes")}>
      {(["observed", "derived", "desired", "execution"] as const).map((lane) => (
        <div key={lane}>
          <strong>{t(`ontology.semantic.state.${lane}`)}</strong>
          <span>{t(`ontology.semantic.stateDescription.${lane}`)}</span>
        </div>
      ))}
    </section>
  );
}

function ContextStatus({
  releaseDigest,
  projectionRevision,
}: {
  readonly releaseDigest: string;
  readonly projectionRevision: string;
}) {
  return (
    <section class="ontology-semantic-context" aria-label={t("ontology.semantic.contextStatus")}>
      <span class="badge">{t("ontology.semantic.receiptRequired")}</span>
      <dl>
        <div><dt>{t("ontology.semantic.release")}</dt><dd><code>{releaseDigest}</code></dd></div>
        <div><dt>{t("ontology.semantic.projection")}</dt><dd><code>{projectionRevision}</code></dd></div>
        <div><dt>{t("ontology.semantic.runtimeEvidence")}</dt><dd>{t("ontology.semantic.notSelected")}</dd></div>
        <div><dt>{t("ontology.semantic.mutationAuthority")}</dt><dd>{t("ontology.common.no")}</dd></div>
      </dl>
    </section>
  );
}

function SemanticInspector({
  selected,
  lens,
  incoming,
  outgoing,
}: {
  readonly selected: OntologyNode | null;
  readonly lens: OntologySemanticLens;
  readonly incoming: readonly OntologySemanticRelation[];
  readonly outgoing: readonly OntologySemanticRelation[];
}) {
  return (
    <aside class="ontology-semantic-inspector" aria-live="polite">
      <span class="badge">{t(`ontology.semantic.lens.${lens}`)}</span>
      <h3><code>{selected?.name ?? t("ontology.objects.defaultName")}</code></h3>
      <p>{selected?.description ?? t("ontology.common.noDescription")}</p>
      <dl>
        <div><dt>{t("ontology.semantic.properties")}</dt><dd>{formatNumber(selected?.property_count ?? 0)}</dd></div>
        <div><dt>{t("ontology.common.outgoing")}</dt><dd>{formatNumber(outgoing.length)}</dd></div>
        <div><dt>{t("ontology.common.incoming")}</dt><dd>{formatNumber(incoming.length)}</dd></div>
      </dl>
      <RelationshipDirection title={t("ontology.common.outgoing")} relations={outgoing} />
      <RelationshipDirection title={t("ontology.common.incoming")} relations={incoming} />
    </aside>
  );
}

function RelationshipDirection({
  title,
  relations,
}: {
  readonly title: string;
  readonly relations: readonly OntologySemanticRelation[];
}) {
  return (
    <section>
      <h4>{title}</h4>
      {relations.length === 0 ? <p>{t("ontology.semantic.none")}</p> : (
        <ul>
          {relations.map((relation) => (
            <li key={`${relation.from}:${relation.name}:${relation.to}`}>
              <code>{relation.from}</code>
              <span>--{relation.name}--&gt;</span>
              <code>{relation.to}</code>
              <RelationshipFlags relation={relation} />
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
