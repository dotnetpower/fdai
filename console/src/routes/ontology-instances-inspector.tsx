import { useState } from "preact/hooks";
import { Tooltip } from "../components/tooltip";
import { StatusPill } from "../components/ui";
import { RecordedStateFacts } from "../components/recorded-state-facts";
import { routeHref } from "../router";
import { formatDateTime, formatNumber, t } from "./i18n/ontology";
import type {
  OntologyInstanceAksDiagnosticReceipt,
  OntologyInstanceActivity,
  OntologyInstanceExploration,
  OntologyInstanceLink,
  OntologyInstanceNetworkPath,
  OntologyInstanceResource,
} from "./ontology-instances.model";
import {
  groupOntologyInstanceRelationships,
  ontologyInstanceCapacityKind,
  ontologyInstanceNetworkPaths,
  ontologyInstancePresentationLinks,
  ontologyInstanceStatusTone,
  ontologyInstanceTrafficDirection,
} from "./ontology-instances.model";

type InspectorView = "overview" | "relationships" | "events" | "sources";
const INDIRECT_RELATIONSHIP_PAGE_SIZE = 40;

export function OntologyInstanceInspector({
  data,
  root,
  onSelect,
  hidden,
  onToggle,
}: {
  readonly data: OntologyInstanceExploration;
  readonly root: OntologyInstanceResource;
  readonly onSelect: (resourceId: string | null) => void;
  readonly hidden: boolean;
  readonly onToggle: () => void;
}) {
  const [view, setView] = useState<InspectorView>("overview");
  return (
    <aside
      id="ontology-instance-inspector"
      class="ontology-instance-inspector"
      aria-label={t("ontology.instances.inspector") }
      hidden={hidden}
    >
      <nav aria-label={t("ontology.instances.inspectorViews") }>
        {(["overview", "relationships", "events", "sources"] as const).map((item) => (
          <button
            type="button"
            class={view === item ? "is-active" : undefined}
            aria-pressed={view === item}
            onClick={() => setView(item)}
          >
            {t(`ontology.instances.view.${item}`)}
          </button>
        ))}
        <Tooltip content={t("ontology.instances.hideInspector")}>
          <button
            type="button"
            class="ontology-instance-inspector-toggle"
            aria-label={t("ontology.instances.hideInspector")}
            aria-expanded={true}
            aria-controls="ontology-instance-inspector"
            onClick={onToggle}
          >
            <span class="ontology-instance-panel-icon is-open" aria-hidden="true" />
          </button>
        </Tooltip>
      </nav>
      {view === "overview" ? <InstanceOverview data={data} root={root} /> : null}
      {view === "relationships" ? <InstanceRelationships data={data} onSelect={onSelect} /> : null}
      {view === "events" ? <InstanceTimeline data={data} /> : null}
      {view === "sources" ? <InstanceSources data={data} /> : null}
    </aside>
  );
}

function InstanceOverview({
  data,
  root,
}: {
  readonly data: OntologyInstanceExploration;
  readonly root: OntologyInstanceResource;
}) {
  const capacityKind = ontologyInstanceCapacityKind(root.resource_type);
  const isModelDeployment = root.resource_type === "llm-model-deployment";
  const modelDeployment = root.model_deployment ?? null;
  return (
    <section class="ontology-instance-inspector-section">
      <span class="eyebrow">Resource</span>
      <h3>{root.name ?? root.resource_type}</h3>
      {root.states ? <RecordedStateFacts states={root.states} /> : <div class="ontology-instance-overview-status">
        <StatusPill
          kind={ontologyInstanceStatusTone(root.status)}
          label={root.status ?? t("ontology.instances.stateNotReported")}
        />
      </div>}
      <dl class="ontology-instance-facts">
        <div><dt>{t("ontology.instances.resourceType")}</dt><dd><code>{root.resource_type}</code></dd></div>
        {root.kubernetes_identity ? (
          <>
            <div><dt>{t("ontology.instances.kubernetesKind")}</dt><dd><code>{root.kubernetes_identity.kind}</code></dd></div>
            <div><dt>{t("ontology.instances.kubernetesNamespace")}</dt><dd><code>{root.kubernetes_identity.namespace ?? t("ontology.instances.notReported")}</code></dd></div>
            <div><dt>{t("ontology.instances.kubernetesUid")}</dt><dd><code>{root.kubernetes_identity.uid}</code></dd></div>
            <div><dt>{t("ontology.instances.kubernetesResourceVersion")}</dt><dd><code>{root.kubernetes_identity.resource_version}</code></dd></div>
          </>
        ) : null}
        {!isModelDeployment ? null : (
          <>
            <div>
              <dt>{t("ontology.instances.modelName")}</dt>
              <dd>{modelDeployment?.model_name
                ? <code>{modelDeployment.model_name}</code>
                : t("ontology.instances.notReported")}</dd>
            </div>
            <div>
              <dt>{t("ontology.instances.modelVersion")}</dt>
              <dd>{modelDeployment?.model_version
                ? <code>{modelDeployment.model_version}</code>
                : t("ontology.instances.notReported")}</dd>
            </div>
            <div>
              <dt>{t("ontology.instances.deploymentSku")}</dt>
              <dd>{modelDeployment?.sku_name
                ? <code>{modelDeployment.sku_name}</code>
                : t("ontology.instances.notReported")}</dd>
            </div>
            <div>
              <dt>{t("ontology.instances.tokensPerMinute")}</dt>
              <dd><strong>{modelDeployment?.capacity_tpm === null
                || modelDeployment?.capacity_tpm === undefined
                ? t("ontology.instances.notReported")
                : formatNumber(modelDeployment.capacity_tpm)}</strong></dd>
            </div>
          </>
        )}
        {root.capacity === null || root.capacity === undefined || capacityKind === null ? null : (
          <div>
            <dt>{t(capacityKind === "node"
              ? "ontology.instances.nodeCount"
              : "ontology.instances.instanceCount")}</dt>
            <dd><strong>{formatNumber(root.capacity)}</strong></dd>
          </div>
        )}
        <div><dt>{t("ontology.instances.location")}</dt><dd>{root.location ?? t("ontology.instances.notReported")}</dd></div>
        <div><dt>{t("ontology.instances.resourceGroup")}</dt><dd>{root.resource_group ?? t("ontology.instances.notReported")}</dd></div>
        <div><dt>{t("ontology.instances.lastSeen")}</dt><dd>{root.last_seen ? formatDateTime(root.last_seen) : t("ontology.instances.notObserved")}</dd></div>
        <div><dt>{t("ontology.instances.snapshot")}</dt><dd><code>{data.source_generation}</code></dd></div>
        <div><dt>{t("ontology.instances.cutoff")}</dt><dd>{formatDateTime(data.source_cutoff)}</dd></div>
      </dl>
      {root.kubernetes_identity ? (
        <AksDiagnosticEvidence receipt={root.aks_diagnostic_receipt ?? null} />
      ) : null}
      {root.kubernetes_diagnostics && Object.keys(root.kubernetes_diagnostics).length > 0 ? (
        <details class="ontology-instance-technical">
          <summary>{t("ontology.instances.kubernetesDiagnostics")}</summary>
          <dl class="ontology-instance-facts">
            {Object.entries(root.kubernetes_diagnostics).map(([key, value]) => (
              <div><dt><code>{key}</code></dt><dd><code>{formatDiagnosticValue(value)}</code></dd></div>
            ))}
          </dl>
        </details>
      ) : null}
      <details class="ontology-instance-technical">
        <summary>{t("ontology.instances.technicalDetails")}</summary>
        <code>{root.id}</code>
        <code>{data.ontology_release_digest}</code>
      </details>
      <a class="btn" href={routeHref("blast-radius", { params: { target: root.id } })}>
        {t("ontology.instances.openImpact")}
      </a>
    </section>
  );
}

function AksDiagnosticEvidence({
  receipt,
}: {
  readonly receipt: OntologyInstanceAksDiagnosticReceipt | null;
}) {
  if (receipt === null) {
    return (
      <section class="ontology-instance-diagnostic-receipt">
        <h4>{t("ontology.instances.diagnosticReceiptTitle")}</h4>
        <StatusPill kind="neutral" label={t("ontology.instances.diagnosticUnavailable")} />
        <p>{t("ontology.instances.diagnosticUnavailableHint")}</p>
      </section>
    );
  }
  const sources = Object.keys(receipt.source_cutoffs).sort();
  const statusTone = receipt.status === "no_failure_signal"
    ? "success"
    : receipt.status === "held"
    ? "warning"
    : "danger";
  return (
    <section class="ontology-instance-diagnostic-receipt">
      <h4>{t("ontology.instances.diagnosticReceiptTitle")}</h4>
      <StatusPill
        kind={statusTone}
        label={t(`ontology.instances.diagnosticStatus.${receipt.status}`)}
      />
      <dl class="ontology-instance-facts">
        <div>
          <dt>{t("ontology.instances.diagnosticCompleteness")}</dt>
          <dd>{t(receipt.complete
            ? "ontology.instances.diagnosticComplete"
            : "ontology.instances.diagnosticIncomplete")}</dd>
        </div>
        <div>
          <dt>{t("ontology.instances.diagnosticCutoff")}</dt>
          <dd>{formatDateTime(receipt.cutoff)}</dd>
        </div>
        <div>
          <dt>{t("ontology.instances.diagnosticSignals")}</dt>
          <dd>{receipt.signals.length === 0
            ? t("ontology.instances.diagnosticNone")
            : receipt.signals.map((signal) =>
              t(`ontology.instances.diagnosticStatus.${signal}`)).join(", ")}</dd>
        </div>
      </dl>
      <h5>{t("ontology.instances.diagnosticSources")}</h5>
      <dl class="ontology-instance-facts">
        {sources.map((source) => (
          <div>
            <dt><code>{source}</code></dt>
            <dd>
              {formatDateTime(receipt.source_cutoffs[source]!)}
              {" - "}
              <code>{receipt.source_revisions[source]}</code>
            </dd>
          </div>
        ))}
      </dl>
      <DiagnosticCodeList
        heading={t("ontology.instances.diagnosticGaps")}
        values={receipt.evidence_gaps}
      />
      <DiagnosticCodeList
        heading={t("ontology.instances.diagnosticConflicts")}
        values={receipt.conflicts}
      />
      <DiagnosticCodeList
        heading={t("ontology.instances.diagnosticEvidenceRefs")}
        values={receipt.evidence_refs}
      />
      <p>{t("ontology.instances.diagnosticNoAuthority")}</p>
    </section>
  );
}

function DiagnosticCodeList({
  heading,
  values,
}: {
  readonly heading: string;
  readonly values: readonly string[];
}) {
  return (
    <>
      <h5>{heading}</h5>
      {values.length === 0
        ? <p>{t("ontology.instances.diagnosticNone")}</p>
        : <ul>{values.map((value) => <li><code>{value}</code></li>)}</ul>}
    </>
  );
}

function formatDiagnosticValue(value: unknown): string {
  return typeof value === "string" ? value : JSON.stringify(value);
}

function InstanceRelationships({
  data,
  onSelect,
}: {
  readonly data: OntologyInstanceExploration;
  readonly onSelect: (resourceId: string | null) => void;
}) {
  const byId = new Map(data.resources.map((resource) => [resource.id, resource]));
  const groups = groupOntologyInstanceRelationships(
    ontologyInstancePresentationLinks(data),
    data.root_id,
  );
  const networkPaths = ontologyInstanceNetworkPaths(data);
  const directCount = groups.directIncoming.length
    + groups.directOutgoing.length
    + groups.verifiedIngress.length
    + groups.verifiedEgress.length
    + groups.runtimeCalls.length
    + groups.accessContext.length
    + groups.containmentContext.length;
  return (
    <section class="ontology-instance-inspector-section">
      <h3>{t("ontology.instances.relationshipsTitle")}</h3>
      <p>{t("ontology.instances.relationshipsHint")}</p>
      {networkPaths ? (
        <section class="ontology-instance-network-paths">
          <h4>{t("ontology.instances.networkPathsTitle")}</h4>
          <p>{t("ontology.instances.networkPathsHint")}</p>
          <NetworkPathDirection
            title={t("ontology.instances.networkPathIngress")}
            path={networkPaths.ingress}
            rootId={data.root_id}
            resources={byId}
            onSelect={onSelect}
          />
          <NetworkPathDirection
            title={t("ontology.instances.networkPathEgress")}
            path={networkPaths.egress}
            rootId={data.root_id}
            resources={byId}
            onSelect={onSelect}
          />
        </section>
      ) : null}
      {directCount === 0 ? <p>{t("ontology.instances.noRelationships")}</p> : null}
      <RelationshipGroup title={t("ontology.instances.verifiedIngress")} links={groups.verifiedIngress} rootId={data.root_id} resources={byId} onSelect={onSelect} />
      <RelationshipGroup title={t("ontology.instances.verifiedEgress")} links={groups.verifiedEgress} rootId={data.root_id} resources={byId} onSelect={onSelect} />
      <RelationshipGroup title={t("ontology.instances.runtimeContext")} links={groups.runtimeCalls} rootId={data.root_id} resources={byId} onSelect={onSelect} />
      <RelationshipGroup title={t("ontology.instances.directIncoming")} links={groups.directIncoming} rootId={data.root_id} resources={byId} onSelect={onSelect} />
      <RelationshipGroup title={t("ontology.instances.directOutgoing")} links={groups.directOutgoing} rootId={data.root_id} resources={byId} onSelect={onSelect} />
      <RelationshipGroup title={t("ontology.instances.accessContext")} links={groups.accessContext} rootId={data.root_id} resources={byId} onSelect={onSelect} />
      <RelationshipGroup title={t("ontology.instances.containmentContext")} links={groups.containmentContext} rootId={data.root_id} resources={byId} onSelect={onSelect} />
      {groups.path.length > 0 ? (
        <details class="ontology-instance-path-details">
          <summary>{t("ontology.instances.indirectRelationships")} ({groups.path.length})</summary>
          <PaginatedRelationshipList
            key={data.root_id}
            links={groups.path}
            rootId={data.root_id}
            resources={byId}
            onSelect={onSelect}
          />
        </details>
      ) : null}
    </section>
  );
}

function PaginatedRelationshipList({
  links,
  rootId,
  resources,
  onSelect,
}: {
  readonly links: readonly OntologyInstanceLink[];
  readonly rootId: string;
  readonly resources: ReadonlyMap<string, OntologyInstanceResource>;
  readonly onSelect: (resourceId: string | null) => void;
}) {
  const [visibleCount, setVisibleCount] = useState(INDIRECT_RELATIONSHIP_PAGE_SIZE);
  const boundedCount = Math.min(visibleCount, links.length);
  return (
    <>
      <p class="ontology-instance-relationship-page-status">
        {t("ontology.instances.relationshipPageStatus", {
          visible: String(boundedCount),
          total: String(links.length),
        })}
      </p>
      <RelationshipList
        links={links.slice(0, boundedCount)}
        rootId={rootId}
        resources={resources}
        onSelect={onSelect}
      />
      {boundedCount < links.length ? (
        <button
          type="button"
          class="btn ontology-instance-relationship-more"
          onClick={() => setVisibleCount((current) =>
            Math.min(current + INDIRECT_RELATIONSHIP_PAGE_SIZE, links.length))}
        >
          {t("ontology.instances.showMoreRelationships", {
            count: String(Math.min(INDIRECT_RELATIONSHIP_PAGE_SIZE, links.length - boundedCount)),
          })}
        </button>
      ) : null}
    </>
  );
}

function NetworkPathDirection({
  title,
  path,
  rootId,
  resources,
  onSelect,
}: {
  readonly title: string;
  readonly path: OntologyInstanceNetworkPath;
  readonly rootId: string;
  readonly resources: ReadonlyMap<string, OntologyInstanceResource>;
  readonly onSelect: (resourceId: string | null) => void;
}) {
  return (
    <div class={`ontology-instance-network-path is-${path.status}`}>
      <div>
        <strong>{title}</strong>
        <span>{t(`ontology.instances.networkPathStatus.${path.status}`)}</span>
      </div>
      {path.links.length === 0 ? (
        <p>{t(`ontology.instances.networkPathReason.${path.reason}`)}</p>
      ) : (
        <details>
          <summary>{t(`ontology.instances.networkPathKind.${path.kind}`, {
            count: String(path.links.length),
          })}</summary>
          <RelationshipList
            links={path.links}
            rootId={rootId}
            resources={resources}
            onSelect={onSelect}
          />
        </details>
      )}
    </div>
  );
}

function RelationshipGroup({
  title,
  links,
  rootId,
  resources,
  onSelect,
}: {
  readonly title: string;
  readonly links: readonly OntologyInstanceLink[];
  readonly rootId: string;
  readonly resources: ReadonlyMap<string, OntologyInstanceResource>;
  readonly onSelect: (resourceId: string | null) => void;
}) {
  if (links.length === 0) return null;
  return (
    <section class="ontology-instance-relationship-group">
      <h4>{title} <span>{links.length}</span></h4>
      <RelationshipList links={links} rootId={rootId} resources={resources} onSelect={onSelect} />
    </section>
  );
}

function RelationshipList({
  links,
  rootId,
  resources,
  onSelect,
}: {
  readonly links: readonly OntologyInstanceLink[];
  readonly rootId: string;
  readonly resources: ReadonlyMap<string, OntologyInstanceResource>;
  readonly onSelect: (resourceId: string | null) => void;
}) {
  return (
    <ul class="ontology-instance-relationship-list">
      {links.map((link) => {
        const trafficDirection = ontologyInstanceTrafficDirection(link, rootId);
        const rootDirection = link.source === rootId
          ? "outgoing"
          : link.target === rootId ? "incoming" : "path";
        const source = resources.get(link.source);
        const target = resources.get(link.target);
        return (
          <li key={`${link.source}:${link.link_type}:${link.target}`}>
            <span>{trafficDirection === null
              ? rootDirection === "outgoing"
                ? t("ontology.instances.graphOutgoing")
                : rootDirection === "incoming"
                  ? t("ontology.instances.graphIncoming")
                  : t("ontology.instances.indirectRelationship")
              : t(`ontology.instances.verified.${trafficDirection}`)}</span>
            <strong>{relationshipLabel(link.link_type)}</strong>
            <div class="ontology-instance-relationship-endpoints">
              <button type="button" onClick={() => onSelect(link.source)}>
                {source?.name ?? source?.resource_type ?? link.source}
              </button>
              <span>{t("ontology.instances.relationshipTo")}</span>
              <button type="button" onClick={() => onSelect(link.target)}>
                {target?.name ?? target?.resource_type ?? link.target}
              </button>
            </div>
            <RelationshipEvidence link={link} trafficDirection={trafficDirection} />
          </li>
        );
      })}
    </ul>
  );
}

function RelationshipEvidence({
  link,
  trafficDirection,
}: {
  readonly link: OntologyInstanceLink;
  readonly trafficDirection: "ingress" | "egress" | null;
}) {
  const evidence = link.evidence;
  if (evidence.status === "unavailable") {
    return (
      <dl class="ontology-instance-relationship-evidence is-unavailable">
        <div><dt>{t("ontology.instances.relationshipEvidence")}</dt><dd>{t("ontology.instances.unavailable")}</dd></div>
        <div><dt>{t("ontology.instances.reason")}</dt><dd><code>{evidence.reason}</code></dd></div>
      </dl>
    );
  }
  return (
    <dl class={`ontology-instance-relationship-evidence${evidence.status === "stale" ? " is-unavailable" : ""}`}>
      <div><dt>{t("ontology.instances.directionMeaning")}</dt><dd>{trafficDirection === null
        ? t("ontology.instances.graphDirectionOnly")
        : t(`ontology.instances.verified.${trafficDirection}`)}</dd></div>
      <div><dt>{t("ontology.instances.evidenceStatus")}</dt><dd>{t(`ontology.instances.evidenceStatusValue.${evidence.status}`)}</dd></div>
      <div><dt>{t("ontology.instances.verificationStatus")}</dt><dd>{t(`ontology.instances.verificationStatusValue.${evidence.verification_status}`)}</dd></div>
      <div><dt>{t("ontology.instances.relationshipSource")}</dt><dd>{evidence.source}</dd></div>
      <div><dt>{t("ontology.instances.evidenceKind")}</dt><dd>{t(`ontology.instances.evidenceKindValue.${evidence.evidence_kind}`)}</dd></div>
      <div><dt>{t("ontology.instances.cutoff")}</dt><dd>{formatDateTime(evidence.cutoff!)}</dd></div>
      <div><dt>{t("ontology.instances.completeness")}</dt><dd>{evidence.complete ? t("ontology.instances.complete") : t("ontology.instances.unavailable")}</dd></div>
      <div><dt>{t("ontology.instances.sourceProperty")}</dt><dd><code>{evidence.source_property_path}</code></dd></div>
      <div><dt>{t("ontology.instances.relationshipMapping")}</dt><dd><code>{evidence.mapping_id}</code></dd></div>
      {evidence.reason === null ? null : <div><dt>{t("ontology.instances.reason")}</dt><dd><code>{evidence.reason}</code></dd></div>}
    </dl>
  );
}

function InstanceTimeline({ data }: { readonly data: OntologyInstanceExploration }) {
  return (
    <section class="ontology-instance-inspector-section">
      <h3>{t("ontology.instances.timelineTitle")}</h3>
      <p>{t("ontology.instances.timelineHint")}</p>
      {data.timeline.items.length === 0 ? <p>{t("ontology.instances.noEvents")}</p> : (
        <ol class="ontology-instance-timeline">
          {data.timeline.items.map((item) => (
            <li key={item.sequence}>
              <time dateTime={item.recorded_at}>{formatDateTime(item.recorded_at)}</time>
              <strong>{activitySummary(item)}</strong>
              <span>{item.actor} - {item.action_kind}</span>
              <a href={routeHref("audit", {
                params: { from_seq: String(item.sequence), through_seq: String(item.sequence) },
              })}>{item.evidence_ref}</a>
            </li>
          ))}
        </ol>
      )}
      {!data.timeline.complete ? <p>{t("ontology.instances.timelineTruncated")}</p> : null}
    </section>
  );
}

function InstanceSources({ data }: { readonly data: OntologyInstanceExploration }) {
  return (
    <section class="ontology-instance-inspector-section">
      <h3>{t("ontology.instances.sourcesTitle")}</h3>
      <p>{t("ontology.instances.sourcesHint")}</p>
      {data.relationship_coverage ? (
        <dl class="ontology-instance-source-coverage-summary">
          <div>
            <dt>{t("ontology.instances.coverageCandidates")}</dt>
            <dd>{formatNumber(data.relationship_coverage.total_candidates)}</dd>
          </div>
          <div>
            <dt>{t("ontology.instances.coverageMaterialized")}</dt>
            <dd>{formatNumber(data.relationship_coverage.materialized)}</dd>
          </div>
          <div>
            <dt>{t("ontology.instances.coverageReviewedUnavailable")}</dt>
            <dd>{formatNumber(data.relationship_coverage.reviewed_unavailable)}</dd>
          </div>
          <div>
            <dt>{t("ontology.instances.coverageUnclassified")}</dt>
            <dd>{formatNumber(data.relationship_coverage.unclassified)}</dd>
          </div>
        </dl>
      ) : (
        <p class="ontology-instance-source-coverage-unavailable">
          {t("ontology.instances.coverageNotReported")}
        </p>
      )}
      {data.provider_scope_coverage ? (
        <>
          <h4>{t("ontology.instances.providerCoverageTitle")}</h4>
          <dl class="ontology-instance-source-coverage-summary">
            <div>
              <dt>{t("ontology.instances.providerObjects")}</dt>
              <dd>{formatNumber(data.provider_scope_coverage.provider_object_count)}</dd>
            </div>
            <div>
              <dt>{t("ontology.instances.providerMappedObjects")}</dt>
              <dd>{formatNumber(data.provider_scope_coverage.mapped_provider_object_count)}</dd>
            </div>
            <div>
              <dt>{t("ontology.instances.providerUnmappedObjects")}</dt>
              <dd>{formatNumber(data.provider_scope_coverage.unmapped_provider_object_count)}</dd>
            </div>
            <div>
              <dt>{t("ontology.instances.providerTypes")}</dt>
              <dd>{formatNumber(data.provider_scope_coverage.provider_type_count)}</dd>
            </div>
            <div>
              <dt>{t("ontology.instances.providerUnmappedTypes")}</dt>
              <dd>{formatNumber(data.provider_scope_coverage.unmapped_provider_type_count)}</dd>
            </div>
            <div>
              <dt>{t("ontology.instances.providerIdentity")}</dt>
              <dd>{data.provider_scope_coverage.provider_identity_complete
                ? t("ontology.instances.complete")
                : t("ontology.instances.unavailable")}</dd>
            </div>
          </dl>
          {data.provider_scope_coverage.unmapped_provider_types.length > 0 ? (
            <ul class="ontology-instance-source-list">
              {data.provider_scope_coverage.unmapped_provider_types.map((item) => (
                <li key={item.provider_type}>
                  <div>
                    <code>{item.provider_type}</code>
                    <span>{formatNumber(item.count)}</span>
                  </div>
                </li>
              ))}
            </ul>
          ) : null}
        </>
      ) : (
        <p class="ontology-instance-source-coverage-unavailable">
          {t("ontology.instances.providerCoverageNotReported")}
        </p>
      )}
      <ul class="ontology-instance-source-list">
        {data.sources.map((source) => (
          <li key={`${source.source}\u0000${source.scope_digest ?? ""}`}>
            <div><strong>{sourceLabel(source.source)}</strong><span>{source.status === "available" ? t("ontology.instances.available") : t("ontology.instances.unavailable")}</span></div>
            <p>
              {source.scope_digest ? <><code>{source.scope_digest}</code>{" - "}</> : null}
              {source.observed_at ? formatDateTime(source.observed_at) : t("ontology.instances.notObserved")}
              {source.reason ? ` - ${source.reason}` : null}
            </p>
          </li>
        ))}
      </ul>
      {data.relationship_drop_classifications.length > 0 ? (
        <section class="ontology-instance-coverage">
          <h4>{t("ontology.instances.coverageDetailsTitle")}</h4>
          <ul class="ontology-instance-coverage-list">
            {data.relationship_drop_classifications.map((item) => (
              <li key={`${item.reason}:${item.mapping_id}:${item.source_provider_type}:${item.target_provider_type}:${item.unavailable_reason}`}>
                <div><strong>{item.mapping_id}</strong><span>{item.count}</span></div>
                <p><code>{item.unavailable_reason}</code></p>
                <p>{item.source_provider_type} -&gt; {item.target_provider_type}</p>
                <code>{item.source_property_path}</code>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </section>
  );
}

function relationshipLabel(value: OntologyInstanceLink["link_type"]): string {
  return t(`ontology.instances.link.${value}`);
}

function sourceLabel(value: string): string {
  return t(`ontology.instances.source.${value}`);
}

function activitySummary(item: OntologyInstanceActivity): string {
  return item.facts.reason
    ?? item.facts.state
    ?? item.facts.verdict
    ?? item.facts.action_type
    ?? item.facts.outcome
    ?? item.action_kind;
}
