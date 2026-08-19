import { useEffect, useState } from "preact/hooks";
import { isOptionalOperatorApiUnavailable } from "../api";
import type { OperatorApiClient } from "../api";
import { OntologyGraph } from "../components/ontology-graph";
import {
  AsyncBoundary,
  PageHeader,
  UnavailableState,
  type AsyncState,
} from "../components/ui";
import { navigate } from "../router";
import { t } from "./i18n/ontology";
import { ontologyReleaseHref } from "./ontology-release-detail";
import {
  compactRecord,
  decodeOntologyDependents,
  decodeOntologyEvidenceHealth,
  decodeOntologyGraphResponse,
  decodeOntologyObjectTypeDetail,
  decodeOntologyReleaseDiff,
  formatUnknown,
  type OntologyGraphResponse,
  type OntologyDependentsResponse,
  type OntologyEvidenceHealthResponse,
  type OntologyObjectTypeDetailResponse,
  type OntologyReleaseDiffResponse,
  type UnknownRecord,
} from "./ontology.types";

interface Props {
  readonly client: OperatorApiClient;
  readonly name: string;
}

interface WorkbenchData {
  readonly summary: OntologyGraphResponse;
  readonly detail: OntologyObjectTypeDetailResponse;
  readonly dependents: OntologyDependentsResponse;
  readonly evidenceHealth: OntologyEvidenceHealthResponse | null;
  readonly releaseDiff: OntologyReleaseDiffResponse | null;
}

export function ontologyDeclarationHref(
  kind: "object-types" | "link-types" | "action-types",
  name: string,
): string {
  const identity = encodeURIComponent(name).replaceAll("_", "%5F");
  return `/ontology/${kind}/${identity}`;
}

export function OntologyObjectTypeDetailRoute({ client, name }: Props) {
  const [state, setState] = useState<AsyncState<WorkbenchData>>({ status: "loading" });

  useEffect(() => {
    let cancelled = false;
    setState({ status: "loading" });
    (async () => {
      try {
        const [summaryPayload, detailPayload, dependentsPayload] = await Promise.all([
          client.panel<unknown>("/ontology/graph"),
          client.panel<unknown>(
            `/ontology/declarations/object-types/${encodeURIComponent(name)}`,
          ),
          client.panel<unknown>(
            `/ontology/declarations/object-types/${encodeURIComponent(name)}/dependents`,
          ),
        ]);
        const summary = decodeOntologyGraphResponse(summaryPayload);
        const detail = decodeOntologyObjectTypeDetail(
          detailPayload,
          summary.ontology_release_digest,
        );
        const dependents = decodeOntologyDependents(
          dependentsPayload,
          summary.ontology_release_digest,
          name,
        );
        let releaseDiff: OntologyReleaseDiffResponse | null = null;
        let evidenceHealth: OntologyEvidenceHealthResponse | null = null;
        try {
          const evidencePayload = await client.panel<unknown>(
            `/ontology/object-types/${encodeURIComponent(name)}/evidence-health`,
          );
          evidenceHealth = decodeOntologyEvidenceHealth(
            evidencePayload,
            summary.ontology_release_digest,
            name,
          );
        } catch (error) {
          if (!isOptionalOperatorApiUnavailable(error)) throw error;
        }
        try {
          const releasePayload = await client.panel<unknown>(
            `/ontology/releases/${summary.ontology_release_digest}/diff`,
          );
          releaseDiff = decodeOntologyReleaseDiff(
            releasePayload,
            summary.ontology_release_digest,
          );
        } catch (error) {
          if (!isOptionalOperatorApiUnavailable(error)) throw error;
        }
        if (!cancelled) {
          setState({
            status: "ready",
            data: { summary, detail, dependents, evidenceHealth, releaseDiff },
          });
        }
      } catch (error) {
        if (cancelled) return;
        if (isOptionalOperatorApiUnavailable(error)) {
          setState({
            status: "unavailable",
            message: t("ontology.detail.notFound", { name }),
          });
        } else {
          setState({
            status: "error",
            message: error instanceof Error ? error.message : String(error),
          });
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [client, name]);

  return (
    <div class="stack governance-route ontology-route ontology-detail-route">
      <PageHeader
        title={name}
        subtitle={t("ontology.detail.subtitle")}
        actions={(
          <a class="button button-secondary" href="/ontology?view=objects">
            {t("ontology.detail.back")}
          </a>
        )}
      />
      <AsyncBoundary
        state={state}
        resourceLabel={t("ontology.detail.loadingLabel")}
        loading={<OntologyDetailSkeleton />}
      >
        {(data) => <OntologyObjectTypeWorkbench data={data} />}
      </AsyncBoundary>
    </div>
  );
}

function OntologyDetailSkeleton() {
  return (
    <div class="ontology-detail-skeleton" role="status" aria-busy="true">
      <span class="sr-only">{t("ontology.detail.loadingLabel")}</span>
      <span class="skeleton-shimmer ontology-detail-skeleton-lead" aria-hidden="true" />
      <span class="skeleton-shimmer ontology-detail-skeleton-table" aria-hidden="true" />
      <span class="skeleton-shimmer ontology-detail-skeleton-graph" aria-hidden="true" />
    </div>
  );
}

function OntologyObjectTypeWorkbench({ data }: { readonly data: WorkbenchData }) {
  const { dependents, detail, evidenceHealth, releaseDiff, summary } = data;
  const declaration = detail.declaration;
  const lifecycle = declaration.lifecycle;
  const provenance = declaration.provenance;
  const properties = Object.entries(declaration.properties);
  const graphAvailable = summary.nodes !== undefined && summary.edges !== undefined;
  return (
    <article class="ontology-detail-workbench">
      <section class="ontology-detail-identity" aria-labelledby="ontology-detail-identity-title">
        <div>
          <span class="eyebrow">ObjectType</span>
          <h3 id="ontology-detail-identity-title"><code>{declaration.name}</code></h3>
          <p>{declaration.description ?? t("ontology.common.noDescription")}</p>
        </div>
        <dl class="ontology-detail-summary">
          <div><dt>{t("ontology.detail.version")}</dt><dd>{declaration.version}</dd></div>
          <div><dt>{t("ontology.detail.key")}</dt><dd><code>{declaration.key}</code></dd></div>
          <div>
            <dt>{t("ontology.detail.lifecycleOwner")}</dt>
            <dd>{recordString(lifecycle, "owner") ?? t("ontology.detail.noLifecycle")}</dd>
          </div>
          <div><dt>{t("ontology.detail.authority")}</dt><dd>{t("ontology.detail.readOnly")}</dd></div>
        </dl>
      </section>

      <DetailSection title={t("ontology.detail.identityAuthority")}>
        <div class="ontology-detail-two-column">
          <div>
            <h4>{t("ontology.detail.lifecycle")}</h4>
            {lifecycle ? <LifecycleDetail lifecycle={lifecycle} /> : (
              <UnavailableState message={t("ontology.detail.noLifecycleDeclared")} />
            )}
          </div>
          <div>
            <h4>{t("ontology.detail.provenance")}</h4>
            {provenance ? <RecordDefinitionList record={provenance} /> : (
              <UnavailableState message={t("ontology.detail.noProvenance")} />
            )}
          </div>
        </div>
      </DetailSection>

      <DetailSection title={t("ontology.detail.propertiesTitle", { count: properties.length })}>
        {detail.redaction.redacted_field_count > 0 ? (
          <div class="state-block state-unavailable" role="status">
            {t("ontology.detail.redactedProperties", {
              count: detail.redaction.redacted_field_count,
            })}
          </div>
        ) : null}
        <div class="ontology-detail-table-wrap">
          <table class="ontology-detail-table">
            <thead><tr>
              <th>{t("ontology.detail.property")}</th>
              <th>{t("ontology.detail.type")}</th>
              <th>{t("ontology.detail.required")}</th>
              <th>{t("ontology.detail.access")}</th>
              <th>{t("ontology.detail.purpose")}</th>
              <th>{t("ontology.detail.description")}</th>
            </tr></thead>
            <tbody>{properties.map(([propertyName, property]) => (
              <tr key={propertyName}>
                <td data-label={t("ontology.detail.property")}>
                  <code>{propertyName}</code>
                  {propertyName === declaration.key ? (
                    <span class="ontology-key-marker">{t("ontology.detail.keyMarker")}</span>
                  ) : null}
                </td>
                <td data-label={t("ontology.detail.type")}><code>{property.type}</code></td>
                <td data-label={t("ontology.detail.required")}>
                  {t(property.required ? "ontology.common.yes" : "ontology.common.no")}
                </td>
                <td data-label={t("ontology.detail.access")}><code>{property.access_scope}</code></td>
                <td data-label={t("ontology.detail.purpose")}>
                  {property.purpose_binding.join(", ") || t("ontology.detail.roleOnly")}
                </td>
                <td data-label={t("ontology.detail.description")}>
                  {property.description ?? t("ontology.common.noDescription")}
                </td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      </DetailSection>

      <DetailSection title={t("ontology.detail.relationshipsTitle")}>
        {graphAvailable ? (
          <OntologyGraph
            key={declaration.name}
            nodes={summary.nodes ?? []}
            edges={summary.edges ?? []}
            initialName={declaration.name}
            onFocusChange={(selected) => {
              if (selected !== null) navigate(ontologyDeclarationHref("object-types", selected));
            }}
            onLinkSelect={(selected) => navigate(ontologyDeclarationHref("link-types", selected))}
          />
        ) : null}
        <div class="ontology-detail-table-wrap">
          <table class="ontology-detail-table ontology-relationship-table">
            <thead><tr>
              <th>{t("ontology.detail.direction")}</th>
              <th>LinkType</th>
              <th>{t("ontology.links.fromObject")}</th>
              <th>{t("ontology.links.toObject")}</th>
              <th>{t("ontology.links.cardinality")}</th>
              <th>{t("ontology.detail.flags")}</th>
            </tr></thead>
            <tbody>{detail.relationships.map((relationship) => (
              <tr key={relationship.name}>
                <td data-label={t("ontology.detail.direction")}>
                  {t(`ontology.common.${relationship.selected_type_direction}`)}
                </td>
                <td data-label="LinkType">
                  <a href={ontologyDeclarationHref("link-types", relationship.name)}>
                    <code>{relationship.name}</code>
                  </a>
                </td>
                <td data-label={t("ontology.links.fromObject")}><code>{relationship.from_type}</code></td>
                <td data-label={t("ontology.links.toObject")}><code>{relationship.to_type}</code></td>
                <td data-label={t("ontology.links.cardinality")}><code>{relationship.cardinality}</code></td>
                <td data-label={t("ontology.detail.flags")}>{relationshipFlags(relationship)}</td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      </DetailSection>

      <DetailSection title={t("ontology.detail.actionsTitle")}>
        {!detail.complete ? (
          <div class="state-block state-unavailable" role="status">
            {t("ontology.detail.actionCoverageIncomplete")}
          </div>
        ) : null}
        {detail.related_actions.length === 0 ? (
          <p class="muted">{t("ontology.detail.noRelatedActions")}</p>
        ) : (
          <ul class="ontology-related-actions">
            {detail.related_actions.map((action) => (
              <li key={action.name}>
                <a href={ontologyDeclarationHref("action-types", action.name)}>
                  <code>{action.name}</code>
                </a>
                <span>{action.category ?? "-"} / {action.operation} / {action.default_mode}</span>
                <span>{action.execution_path ?? "-"} / {action.rollback_contract}</span>
              </li>
            ))}
          </ul>
        )}
      </DetailSection>

      <DetailSection title={t("ontology.detail.evidenceHealthTitle")}>
        {evidenceHealth === null || evidenceHealth.availability === "unavailable" ? (
          <UnavailableState message={t("ontology.detail.evidenceUnavailable", {
            reason: evidenceHealth?.unavailable_reason ?? "source_not_connected",
          })} />
        ) : (
          <dl class="ontology-detail-summary ontology-evidence-summary">
            <div><dt>{t("ontology.detail.source")}</dt><dd>{formatUnknown(evidenceHealth.source)}</dd></div>
            <div><dt>{t("ontology.detail.freshness")}</dt><dd>{evidenceHealth.freshness_state}</dd></div>
            <div><dt>{t("ontology.detail.completeness")}</dt><dd>{t(evidenceHealth.complete ? "ontology.common.yes" : "ontology.common.no")}</dd></div>
            <div><dt>{t("ontology.detail.synthetic")}</dt><dd>{t(evidenceHealth.synthetic ? "ontology.common.yes" : "ontology.common.no")}</dd></div>
            <div>
              <dt>{t("ontology.detail.instances")}</dt>
              <dd><a href={`/architecture?type=${encodeURIComponent(declaration.name)}`}>{evidenceHealth.visible_instance_count}</a></dd>
            </div>
            <div>
              <dt>{t("ontology.detail.runtimeLinks")}</dt>
              <dd><a href={`/architecture?type=${encodeURIComponent(declaration.name)}`}>{evidenceHealth.visible_link_count}</a></dd>
            </div>
            <div><dt>{t("ontology.detail.conflicts")}</dt><dd>{evidenceHealth.conflicts.join(", ") || "-"}</dd></div>
            <div><dt>{t("ontology.detail.dropReasons")}</dt><dd>{evidenceHealth.drop_reasons.join(", ") || "-"}</dd></div>
          </dl>
        )}
      </DetailSection>

      <DetailSection title={t("ontology.detail.dependentsTitle")}>
        {dependents.truncated ? (
          <div class="state-block state-unavailable" role="status">
            {t("ontology.detail.dependentsTruncated")}
          </div>
        ) : null}
        {dependents.dependents.length === 0 ? (
          <p class="muted">{t("ontology.detail.noDependents")}</p>
        ) : (
          <div class="ontology-detail-table-wrap">
            <table class="ontology-detail-table">
              <thead><tr>
                <th>{t("ontology.detail.dependent")}</th>
                <th>{t("ontology.detail.dependentKind")}</th>
                <th>{t("ontology.detail.reference")}</th>
                <th>{t("ontology.detail.evidenceRef")}</th>
              </tr></thead>
              <tbody>{dependents.dependents.map((dependent) => (
                <tr key={`${dependent.kind}:${dependent.name}:${dependent.relationship}`}>
                  <td data-label={t("ontology.detail.dependent")}>
                    <a href={dependentHref(dependent.kind, dependent.name)}>
                      <code>{dependent.name}</code>
                    </a>
                  </td>
                  <td data-label={t("ontology.detail.dependentKind")}><code>{dependent.kind}</code></td>
                  <td data-label={t("ontology.detail.reference")}><code>{dependent.relationship}</code></td>
                  <td data-label={t("ontology.detail.evidenceRef")}><code>{dependent.evidence_ref}</code></td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        )}
        <div class="ontology-release-summary">
          <h4>{t("ontology.detail.releaseCompatibility")}</h4>
          {releaseDiff === null ? (
            <UnavailableState message={t("ontology.detail.noPreviousRelease")} />
          ) : (
            <>
              <dl class="ontology-detail-summary">
                <div><dt>{t("ontology.detail.verdict")}</dt><dd>{releaseDiff.compatibility_verdict}</dd></div>
                <div><dt>{t("ontology.detail.added")}</dt><dd>{releaseDiff.added.length}</dd></div>
                <div><dt>{t("ontology.detail.changed")}</dt><dd>{releaseDiff.changed.length}</dd></div>
                <div><dt>{t("ontology.detail.removed")}</dt><dd>{releaseDiff.removed.length}</dd></div>
              </dl>
              <p class="muted ontology-release-boundary">
                {t("ontology.detail.declarationRefsOnly")}
              </p>
            </>
          )}
        </div>
      </DetailSection>

      <details class="governance-source-details ontology-technical-details">
        <summary class="details-summary">{t("ontology.detail.technicalDetails")}</summary>
        <dl>
          <div>
            <dt>{t("ontology.semantic.release")}</dt>
            <dd><a href={ontologyReleaseHref(detail.ontology_release_digest)}><code>{detail.ontology_release_digest}</code></a></dd>
          </div>
          <div><dt>{t("ontology.semantic.projection")}</dt><dd><code>{detail._revision}</code></dd></div>
          <div><dt>{t("ontology.semantic.mutationAuthority")}</dt><dd><code>false</code></dd></div>
        </dl>
      </details>
    </article>
  );
}

function DetailSection({ title, children }: { readonly title: string; readonly children: preact.ComponentChildren }) {
  return <section class="ontology-detail-section"><h3>{title}</h3>{children}</section>;
}

function LifecycleDetail({ lifecycle }: { readonly lifecycle: UnknownRecord }) {
  return (
    <dl class="ontology-detail-facts">
      <dt>{t("ontology.detail.lifecycleOwner")}</dt><dd>{recordString(lifecycle, "owner") ?? "-"}</dd>
      <dt>{t("ontology.detail.creation")}</dt><dd>{formatUnknown(lifecycle.creation)}</dd>
      <dt>{t("ontology.detail.deduplication")}</dt><dd>{formatUnknown(lifecycle.deduplication)}</dd>
      <dt>{t("ontology.detail.closure")}</dt><dd>{formatUnknown(lifecycle.closure)}</dd>
      <dt>{t("ontology.detail.authorityRefs")}</dt><dd>{formatUnknown(lifecycle.authority_refs)}</dd>
    </dl>
  );
}

function RecordDefinitionList({ record }: { readonly record: UnknownRecord }) {
  return <dl class="ontology-detail-facts">{Object.entries(record).map(([key, value]) => (
    <><dt key={`${key}-key`}>{key.replaceAll("_", " ")}</dt><dd key={`${key}-value`}>{formatUnknown(value)}</dd></>
  ))}</dl>;
}

function recordString(record: UnknownRecord | undefined, key: string): string | null {
  const value = record?.[key];
  return typeof value === "string" && value ? value : null;
}

function relationshipFlags(relationship: UnknownRecord): string {
  const flags = [
    relationship.is_causal === true ? t("ontology.semantic.causal") : null,
    relationship.is_transitive === true ? t("ontology.semantic.transitive") : null,
    relationship.temporal_order === true ? t("ontology.semantic.temporal") : null,
  ].filter((value): value is string => value !== null);
  return flags.join(", ") || "-";
}

function dependentHref(kind: string, name: string): string {
  if (kind === "link_type") return ontologyDeclarationHref("link-types", name);
  if (kind === "action_type") return ontologyDeclarationHref("action-types", name);
  if (kind === "agent") return `/agents/${encodeURIComponent(name)}`;
  return "/ontology?view=topology";
}
