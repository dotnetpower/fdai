/** Read-only impact summary, selectable relationship graph, and evidence boundary presentation. */

import { useEffect, useState } from "preact/hooks";
import { architectureHref } from "../components/architecture-map.model";
import { StatusPill, type PillKind } from "../components/ui";
import {
  impactEdgeEvidenceState,
  type BlastRadiusResponse,
  type ImpactEdgeEvidenceState,
  type ImpactRelationshipSourceCoverage,
  type TraversedEdge,
} from "./blast-radius.model";
import { formatNumber, t } from "./i18n/ontology";

export function ImpactSummary({ data }: { readonly data: BlastRadiusResponse }) {
  const directCount = data.reached.filter((node) => node.depth === 1).length;
  const indirectCount = data.reached.filter((node) => node.depth > 1).length;
  const sourceCoverage = sourceCoveragePresentation(data.relationship_source_coverage);
  const coverageComplete = data.complete
    && data.relationship_evidence_complete === true
    && sourceCoverage.fullyMaterialized;
  return (
    <section class="blast-summary-metrics" aria-label={t("ontology.blast.summaryLabel")}>
      <div class="blast-summary-metric">
        <span>{t("ontology.blast.selectedTarget")}</span>
        <strong>{formatNumber(1)}</strong>
        <small>{t("ontology.blast.exactLogicalIdentity")}</small>
      </div>
      <div class="blast-summary-metric">
        <span>{t("ontology.blast.directlyReachedCount")}</span>
        <strong>{formatNumber(directCount)}</strong>
        <small>{t("ontology.blast.storedOutgoingRelationships")}</small>
      </div>
      <div class="blast-summary-metric">
        <span>{t("ontology.blast.indirectContext")}</span>
        <strong>{formatNumber(indirectCount)}</strong>
        <small>{t("ontology.blast.observedNotChanged")}</small>
      </div>
      <div class="blast-summary-metric">
        <span>{t("ontology.blast.evidenceCoverage")}</span>
        <strong class="is-label">
          {t(coverageComplete
            ? "ontology.blast.completeCoverage"
            : "ontology.blast.partialCoverage")}
        </strong>
        <small>
          {t(coverageComplete
            ? "ontology.blast.completeCoverageHint"
            : "ontology.blast.partialCoverageHint")}
        </small>
      </div>
    </section>
  );
}

interface ImpactNodePosition {
  readonly x: number;
  readonly y: number;
}

const IMPACT_NODE_POSITIONS: readonly ImpactNodePosition[] = [
  { x: 23, y: 26 },
  { x: 76, y: 27 },
  { x: 75, y: 72 },
  { x: 23, y: 74 },
  { x: 50, y: 86 },
  { x: 50, y: 14 },
  { x: 23, y: 40 },
  { x: 77, y: 60 },
];

function impactNodePosition(index: number): ImpactNodePosition {
  if (index === 0) return { x: 50, y: 50 };
  const position = IMPACT_NODE_POSITIONS[index - 1];
  if (position === undefined) {
    throw new Error("Impact graph node exceeds the presentation bound.");
  }
  return position;
}

function impactRelationshipLabel(linkType: string | null): string {
  switch (linkType) {
    case "contains":
      return t("ontology.blast.relationshipContains");
    case "depends_on":
      return t("ontology.blast.relationshipDependsOn");
    case "attached_to":
      return t("ontology.blast.relationshipAttachedTo");
    case "runtime_calls":
      return t("ontology.blast.relationshipRuntimeCalls");
    default:
      return t("ontology.blast.relationshipUnknown");
  }
}

interface EvidencePresentation {
  readonly className: string;
  readonly kind: PillKind;
  readonly label: string;
}

export function impactEvidencePresentation(edge: TraversedEdge): EvidencePresentation {
  const state = impactEdgeEvidenceState(edge);
  const labels: Readonly<Record<ImpactEdgeEvidenceState, string>> = {
    configuration_observed: t("ontology.blast.configurationObserved"),
    independently_verified: t("ontology.blast.independentlyVerified"),
    stale: t("ontology.blast.staleEvidence"),
    source_incomplete: t("ontology.blast.sourceIncomplete"),
    coverage_unavailable: t("ontology.blast.coverageAccountingUnavailable"),
    unavailable: t("ontology.blast.evidenceUnavailable"),
    legacy_verified: t("ontology.blast.legacyVerified"),
    legacy_unverified: t("ontology.blast.unverified"),
  };
  const kind: PillKind = state === "independently_verified"
    ? "success"
    : state === "configuration_observed"
      ? "info"
      : "warning";
  return {
    className: `is-${state.replaceAll("_", "-")}`,
    kind,
    label: labels[state],
  };
}

function evidenceDescriptionKey(
  edge: TraversedEdge | undefined,
): string {
  if (edge === undefined) return "ontology.blast.selectedNodeDescription";
  switch (impactEdgeEvidenceState(edge)) {
    case "configuration_observed":
      return "ontology.blast.selectedConfigurationDescription";
    case "independently_verified":
      return "ontology.blast.selectedIndependentDescription";
    case "stale":
      return "ontology.blast.selectedStaleDescription";
    case "source_incomplete":
      return "ontology.blast.selectedSourceIncompleteDescription";
    case "coverage_unavailable":
      return "ontology.blast.selectedCoverageUnavailableDescription";
    case "unavailable":
      return "ontology.blast.selectedUnavailableDescription";
    case "legacy_verified":
    case "legacy_unverified":
      return "ontology.blast.selectedLegacyDescription";
  }
}

interface SourceCoveragePresentation {
  readonly fullyMaterialized: boolean;
  readonly label: string;
}

function sourceCoveragePresentation(
  coverage: ImpactRelationshipSourceCoverage | null,
): SourceCoveragePresentation {
  if (coverage === null) {
    return {
      fullyMaterialized: false,
      label: t("ontology.blast.coverageAccountingUnavailable"),
    };
  }
  let gaps: string | null = null;
  if (coverage.reviewed_unavailable > 0 && coverage.unclassified > 0) {
    gaps = t("ontology.blast.mixedSourceGaps", {
      unavailable: formatNumber(coverage.reviewed_unavailable),
      unclassified: formatNumber(coverage.unclassified),
    });
  } else if (coverage.unclassified > 0) {
    gaps = t("ontology.blast.unclassifiedCount", {
      count: formatNumber(coverage.unclassified),
    });
  } else if (coverage.reviewed_unavailable > 0) {
    gaps = t("ontology.blast.knownUnavailableCount", {
      count: formatNumber(coverage.reviewed_unavailable),
    });
  }
  if (!coverage.complete) {
    return {
      fullyMaterialized: false,
      label: gaps === null
        ? t("ontology.blast.sourceCoverageIncomplete")
        : t("ontology.blast.sourceIncompleteWithGaps", { gaps }),
    };
  }
  if (gaps !== null) {
    return {
      fullyMaterialized: false,
      label: gaps,
    };
  }
  return {
    fullyMaterialized: true,
    label: t("ontology.blast.completeCoverage"),
  };
}

export function BlastImpact({
  data,
  architectureView,
  evidenceHref,
}: {
  readonly data: BlastRadiusResponse;
  readonly architectureView: string | null;
  readonly evidenceHref: string;
}) {
  const targetNode = data.reached.find((node) => node.resource_id === data.target);
  if (targetNode === undefined) {
    throw new Error("Impact projection target node is missing.");
  }
  const graphNodes = [
    targetNode,
    ...data.reached
      .filter((node) => node.resource_id !== data.target)
      .slice(0, IMPACT_NODE_POSITIONS.length),
  ];
  const layouts = graphNodes.map((node, index) => ({
    node,
    position: impactNodePosition(index),
  }));
  const positionById = new Map(
    layouts.map(({ node, position }) => [node.resource_id, position]),
  );
  const [selectedId, setSelectedId] = useState(data.target);
  useEffect(() => {
    setSelectedId(data.target);
  }, [data.source_generation, data.target]);
  const selectedNode = graphNodes.find((node) => node.resource_id === selectedId) ?? targetNode;
  const selectedEdges = data.edges.filter(
    (edge) => edge.source === selectedNode.resource_id
      || edge.target === selectedNode.resource_id,
  );
  const displayedEdges = selectedEdges.slice(0, 5);
  const incomingEdge = selectedNode.depth === 0
    ? undefined
    : data.edges.find(
      (edge) => edge.target === selectedNode.resource_id
        && edge.depth === selectedNode.depth
        && edge.link_type === selectedNode.via_link_type,
    );
  const selectedEvidence = incomingEdge ? impactEvidencePresentation(incomingEdge) : null;
  const selectedEvidenceState = incomingEdge
    ? impactEdgeEvidenceState(incomingEdge)
    : null;
  const selectedUnresolved = selectedEvidenceState !== null
    && selectedEvidenceState !== "configuration_observed"
    && selectedEvidenceState !== "independently_verified";
  const hiddenNodeCount = Math.max(0, data.affected_count - (graphNodes.length - 1));
  const selectedKicker = selectedUnresolved
    ? t("ontology.blast.coverageGap")
    : selectedNode.depth === 0
      ? t("ontology.blast.selectedTarget")
      : selectedNode.depth === 1
        ? t("ontology.blast.directlyReached")
        : t("ontology.blast.indirectContext");
  const selectedDescription = selectedNode.depth === 0
    ? t("ontology.blast.selectedTargetDescription")
    : t(evidenceDescriptionKey(incomingEdge), {
      depth: formatNumber(selectedNode.depth),
      link: impactRelationshipLabel(selectedNode.via_link_type),
    });
  const selectedStatus = selectedNode.depth === 0
    ? { kind: "info" as const, label: t("ontology.blast.targetBadge") }
    : selectedEvidence ?? {
        kind: "warning" as const,
        label: t("ontology.blast.evidenceUnavailable"),
      };
  const sourceCoverage = sourceCoveragePresentation(data.relationship_source_coverage);
  const evidenceStates = [
    ...new Map(data.edges.map((edge) => {
      const presentation = impactEvidencePresentation(edge);
      return [presentation.className, presentation] as const;
    })).values(),
  ];

  return (
    <div class="blast-impact-layout">
      <div
        class="blast-impact-graph"
        role="group"
        aria-label={t("ontology.blast.graphLabel")}
      >
        <div class="blast-impact-legend" aria-label={t("ontology.blast.graphLegend")}>
          {data.traversal_links.map((linkType) => (
            <span key={linkType}>
              <i class={`is-${linkType.replaceAll("_", "-")}`} aria-hidden="true" />
              {impactRelationshipLabel(linkType)}
            </span>
          ))}
          {evidenceStates.map((evidence) => (
            <span key={evidence.className}>
              <i class={evidence.className} aria-hidden="true" />
              {evidence.label}
            </span>
          ))}
        </div>
        <svg
          class="blast-impact-lines"
          viewBox="0 0 100 100"
          preserveAspectRatio="none"
          aria-hidden="true"
        >
          {data.edges.map((edge) => {
            const source = positionById.get(edge.source);
            const target = positionById.get(edge.target);
            if (source === undefined || target === undefined) return null;
            const evidence = impactEvidencePresentation(edge);
            return (
              <line
                key={`${edge.source}:${edge.link_type}:${edge.target}`}
                x1={source.x}
                y1={source.y}
                x2={target.x}
                y2={target.y}
                class={`is-${edge.link_type.replaceAll("_", "-")} ${evidence.className}`}
                vector-effect="non-scaling-stroke"
              />
            );
          })}
        </svg>
        {layouts.map(({ node, position }) => {
          const nodeIncomingEdge = node.depth === 0
            ? undefined
            : data.edges.find(
              (edge) => edge.target === node.resource_id
                && edge.depth === node.depth
                && edge.link_type === node.via_link_type,
            );
          const evidence = nodeIncomingEdge
            ? impactEvidencePresentation(nodeIncomingEdge)
            : null;
          const unresolved = nodeIncomingEdge !== undefined
            && !["configuration_observed", "independently_verified"].includes(
              impactEdgeEvidenceState(nodeIncomingEdge),
            );
          return (
            <button
              key={node.resource_id}
              class={`blast-impact-node${node.depth === 0 ? " is-target" : ""}${unresolved ? " is-unverified" : ""}${evidence ? ` ${evidence.className}` : ""}`}
              type="button"
              style={`left:${position.x}%;top:${position.y}%`}
              aria-pressed={selectedNode.resource_id === node.resource_id}
              onClick={() => setSelectedId(node.resource_id)}
            >
              <strong>{shortResource(node.resource_id)}</strong>
              <small>
                {node.depth === 0
                  ? t("ontology.blast.nodeTargetMeta")
                  : t("ontology.blast.nodeDepthMeta", {
                    depth: formatNumber(node.depth),
                    link: impactRelationshipLabel(node.via_link_type),
                  })}
              </small>
            </button>
          );
        })}
        {hiddenNodeCount > 0 ? (
          <a class="blast-impact-overflow" href={evidenceHref}>
            {t("ontology.blast.showingNodes", {
              shown: formatNumber(graphNodes.length - 1),
              total: formatNumber(data.affected_count),
            })}
          </a>
        ) : null}
      </div>
      <aside class="blast-impact-inspector" aria-live="polite">
        <header class="blast-impact-inspector-head">
          <div>
            <span class="blast-impact-kicker">{selectedKicker}</span>
            <h4>
              <a href={architectureHref(selectedNode.resource_id, architectureView)}>
                <code>{shortResource(selectedNode.resource_id)}</code>
              </a>
            </h4>
            <p>{selectedDescription}</p>
          </div>
          <StatusPill kind={selectedStatus.kind} label={selectedStatus.label} />
        </header>
        <section class="blast-impact-inspector-section">
          <h5>{t("ontology.blast.relationshipEvidence")}</h5>
          {displayedEdges.length > 0 ? (
            <ul class="blast-impact-edge-list">
              {displayedEdges.map((edge) => {
                const evidence = impactEvidencePresentation(edge);
                return (
                  <li key={`${edge.source}:${edge.link_type}:${edge.target}`}>
                    <div>
                      <code>{shortResource(edge.source)}</code>
                      <span class="blast-impact-edge-arrow" aria-hidden="true">-&gt;</span>
                      <code>{shortResource(edge.target)}</code>
                      <small>
                        <code>{edge.link_type}</code>
                        {edge.evidence?.source ? ` - ${edge.evidence.source}` : ""}
                      </small>
                    </div>
                    <StatusPill kind={evidence.kind} label={evidence.label} />
                  </li>
                );
              })}
            </ul>
          ) : (
            <p class="muted">{t("ontology.blast.noRelatedEdges")}</p>
          )}
          {selectedEdges.length > displayedEdges.length ? (
            <p class="blast-impact-more">
              {t("ontology.blast.additionalRelationships", {
                count: formatNumber(selectedEdges.length - displayedEdges.length),
              })}
            </p>
          ) : null}
        </section>
        <section class="blast-impact-inspector-section">
          <h5>{t("ontology.blast.evidenceBoundary")}</h5>
          <dl class="blast-impact-facts">
            <div>
              <dt>{t("ontology.blast.exactResourceId")}</dt>
              <dd><code>{selectedNode.resource_id}</code></dd>
            </div>
            <div>
              <dt>{t("ontology.blast.relationshipEvidenceState")}</dt>
              <dd>{selectedEvidence?.label ?? t("ontology.blast.notApplicable")}</dd>
            </div>
            {incomingEdge?.evidence?.source ? (
              <div>
                <dt>{t("ontology.blast.relationshipEvidenceSource")}</dt>
                <dd>{incomingEdge.evidence.source}</dd>
              </div>
            ) : null}
            {incomingEdge?.evidence?.mapping_id ? (
              <div>
                <dt>{t("ontology.blast.relationshipMapping")}</dt>
                <dd><code>{incomingEdge.evidence.mapping_id}</code></dd>
              </div>
            ) : null}
            {incomingEdge?.evidence?.evidence_method ? (
              <div>
                <dt>{t("ontology.blast.relationshipEvidenceMethod")}</dt>
                <dd><code>{incomingEdge.evidence.evidence_method}</code></dd>
              </div>
            ) : null}
            {incomingEdge?.evidence?.cutoff ? (
              <div>
                <dt>{t("ontology.blast.relationshipEvidenceCutoff")}</dt>
                <dd>
                  <time dateTime={incomingEdge.evidence.cutoff}>
                    {incomingEdge.evidence.cutoff}
                  </time>
                </dd>
              </div>
            ) : null}
            {incomingEdge?.evidence?.reason ? (
              <div>
                <dt>{t("ontology.blast.relationshipEvidenceRecovery")}</dt>
                <dd>{t(`ontology.blast.evidenceReason.${incomingEdge.evidence.reason}`)}</dd>
              </div>
            ) : null}
            <div>
              <dt>{t("ontology.blast.projectionCutoff")}</dt>
              <dd><time dateTime={data.source_cutoff}>{data.source_cutoff}</time></dd>
            </div>
            <div>
              <dt>{t("ontology.blast.coverage")}</dt>
              <dd>
                {t(data.complete
                  ? "ontology.blast.completeCoverage"
                  : "ontology.blast.partialCoverage")}
              </dd>
            </div>
            <div>
              <dt>{t("ontology.blast.relationshipSourceCoverage")}</dt>
              <dd>{sourceCoverage.label}</dd>
            </div>
            <div>
              <dt>{t("ontology.blast.mutationAuthority")}</dt>
              <dd>{t("ontology.blast.none")}</dd>
            </div>
          </dl>
        </section>
      </aside>
    </div>
  );
}

export function BlastTraversalContract({ data }: { readonly data: BlastRadiusResponse }) {
  const states = data.edges.map(impactEdgeEvidenceState);
  const configurationCount = states.filter(
    (state) => state === "configuration_observed",
  ).length;
  const independentCount = states.filter(
    (state) => state === "independently_verified",
  ).length;
  const unresolvedCount = states.length - configurationCount - independentCount;
  const sourceCoverage = sourceCoveragePresentation(data.relationship_source_coverage);
  const sourceCoverageIncomplete = !sourceCoverage.fullyMaterialized;
  const coverageLabel = !data.complete
    ? t("ontology.blast.partialCoverage")
    : sourceCoverageIncomplete
      ? sourceCoverage.label
    : unresolvedCount > 0
      ? t("ontology.blast.unresolvedEvidenceCount", {
          count: formatNumber(unresolvedCount),
        })
      : configurationCount > 0 && independentCount > 0
        ? t("ontology.blast.mixedVerifiedCount", {
            configuration: formatNumber(configurationCount),
            independent: formatNumber(independentCount),
          })
        : independentCount > 0
          ? t("ontology.blast.independentlyVerifiedCount", {
              count: formatNumber(independentCount),
            })
          : configurationCount > 0
            ? t("ontology.blast.configurationObservedCount", {
                count: formatNumber(configurationCount),
              })
      : t("ontology.blast.noneRecorded");
  return (
    <section class="blast-traversal-contract" aria-labelledby="blast-traversal-contract-title">
      <h3 id="blast-traversal-contract-title">
        {t("ontology.blast.traversalContract")}
      </h3>
      <ul>
        <li>
          <span>
            <strong>{t("ontology.blast.storedDirectionPreserved")}</strong>
            <small>{t("ontology.blast.storedDirectionDescription")}</small>
          </span>
          <StatusPill kind="success" label={t("ontology.blast.pass")} />
        </li>
        <li>
          <span>
            <strong>{t("ontology.blast.unknownCoverageRetained")}</strong>
            <small>{t("ontology.blast.unknownCoverageDescription")}</small>
          </span>
          <StatusPill
            kind={!data.complete || sourceCoverageIncomplete || unresolvedCount > 0
              ? "warning"
              : "success"}
            label={coverageLabel}
          />
        </li>
        <li>
          <span>
            <strong>{t("ontology.blast.mutationAuthority")}</strong>
            <small>{t("ontology.blast.mutationAuthorityDescription")}</small>
          </span>
          <StatusPill kind="neutral" label={t("ontology.blast.none")} />
        </li>
      </ul>
    </section>
  );
}

function shortResource(value: string): string {
  const parts = value.split("/").filter(Boolean);
  const last = parts[parts.length - 1] ?? value;
  return last.length > 22 ? `${last.slice(0, 20)}...` : last;
}
