import type { ComponentChildren, JSX } from "preact";

import { architectureHref } from "../components/architecture-map.model";
import { Tooltip } from "../components/tooltip";
import {
  CopyButton,
  DataTable,
  EmptyState,
  StatusPill,
  UnavailableState,
  type Column,
  type PillKind,
} from "../components/ui";
import { routeHref } from "../router";
import { formatConsoleTimestamp } from "../time-format";
import {
  filterCoverageResources,
  type CoverageResourceControls,
} from "./detection-coverage-state";
import type {
  AnalyzerCoverageResourceTypeView,
  AnalyzerCoverageResourceView,
  AnalyzerCoverageView,
  AnalyzerEvaluationState,
  AnalyzerRunView,
} from "./detection-readiness.analyzer-run";
import { t } from "./i18n/detection-readiness";

export interface ParsedResourceRefDisplay {
  readonly fullRef: string;
  readonly shortName: string;
  readonly resourceGroup: string | null;
  readonly scopeId: string | null;
  readonly providerType: string | null;
  readonly hasStructuredScope: boolean;
}

/** Extract readable short name and scope segments from canonical Azure/scope resource refs. */
export function parseResourceRefDisplay(resourceRef: string): ParsedResourceRefDisplay {
  const scopeMatch = /^(scope-[^/]+)\/resource-group\/([^/]+)\/providers\/([^/]+\/[^/]+)\/(.+)$/i.exec(
    resourceRef,
  );
  if (scopeMatch) {
    const [, scopeId = "", resourceGroup = "", providerType = "", tail = ""] = scopeMatch;
    const segments = tail.split("/").filter(Boolean);
    const shortName = segments[segments.length - 1] ?? tail;
    return {
      fullRef: resourceRef,
      shortName,
      resourceGroup,
      scopeId,
      providerType,
      hasStructuredScope: true,
    };
  }
  const armMatch = /^\/?subscriptions\/([^/]+)\/resourcegroups\/([^/]+)\/providers\/([^/]+\/[^/]+)\/(.+)$/i.exec(
    resourceRef,
  );
  if (armMatch) {
    const [, scopeId = "", resourceGroup = "", providerType = "", tail = ""] = armMatch;
    const segments = tail.split("/").filter(Boolean);
    const shortName = segments[segments.length - 1] ?? tail;
    return {
      fullRef: resourceRef,
      shortName,
      resourceGroup,
      scopeId,
      providerType,
      hasStructuredScope: true,
    };
  }
  return {
    fullRef: resourceRef,
    shortName: resourceRef,
    resourceGroup: null,
    scopeId: null,
    providerType: null,
    hasStructuredScope: false,
  };
}

/** Render compact attempt context and drillable resource-type coverage. */
export function CoverageOverview({
  coverage,
  successfulRun,
  selectedResourceType,
  resourcesHref,
  findingsHref,
  onOpenResources,
  onOpenFindings,
  onSelectResourceType,
}: {
  readonly coverage: AnalyzerCoverageView;
  readonly successfulRun: AnalyzerRunView | null;
  readonly selectedResourceType?: string;
  readonly resourcesHref: string;
  readonly findingsHref: string;
  readonly onOpenResources: () => void;
  readonly onOpenFindings: () => void;
  readonly onSelectResourceType: (resourceType: string) => void;
}) {
  if (coverage.status === "unavailable") {
    return (
      <section
        id="detection-coverage-summary"
        class="stack-section"
        aria-labelledby="detection-coverage-title"
      >
        <h3 id="detection-coverage-title" class="section-title">{t("coverage.title")}</h3>
        <UnavailableState
          message={t("coverage.unavailableReason", {
            reason: coverage.unavailable_reason,
          })}
          evidenceState="not-measured"
        />
      </section>
    );
  }
  const columns: readonly Column<AnalyzerCoverageResourceTypeView>[] = [
    {
      key: "type",
      header: t("coverage.column.resourceType"),
      render: (row) => (
        <span class="coverage-type-name">
          <strong>{resourceTypeLabel(row.resource_type)}</strong>
          <small>{t("coverage.evaluationRate", {
            evaluated: row.evaluated_count,
            candidates: row.candidate_count,
            percent: coveragePercent(row),
          })}</small>
          <span
            class="coverage-type-progress coverage-table-progress"
            style={`--coverage-percent:${coveragePercent(row)}%`}
            aria-hidden="true"
          />
        </span>
      ),
    },
    {
      key: "candidates",
      header: t("coverage.column.candidates"),
      render: (row) => row.candidate_count,
      cellClass: "num",
    },
    {
      key: "selected",
      header: t("coverage.column.selected"),
      render: (row) => row.selected_count,
      cellClass: "num",
    },
    {
      key: "evaluated",
      header: t("coverage.column.evaluated"),
      render: (row) => row.evaluated_count,
      cellClass: "num",
    },
    {
      key: "held",
      header: t("coverage.column.held"),
      render: (row) => (
        <Tooltip content={heldReasonSummary(row)}>
          <span class="coverage-cell-stack">
            <span>{row.held_count}</span>
            {row.held_count > 0 ? (
              <small class="coverage-cell-detail">{heldReasonSummary(row)}</small>
            ) : null}
          </span>
        </Tooltip>
      ),
      cellClass: "num",
    },
    {
      key: "findings",
      header: t("coverage.column.findings"),
      render: (row) => row.finding_count,
      cellClass: "num",
    },
    {
      key: "errors",
      header: t("coverage.column.errors"),
      render: (row) => (
        <Tooltip content={errorCodeSummary(row.error_codes)}>
          <span class="coverage-cell-stack">
            <span>{row.error_count}</span>
            {row.error_count > 0 ? (
              <small class="coverage-cell-detail">{errorCodeSummary(row.error_codes)}</small>
            ) : null}
          </span>
        </Tooltip>
      ),
      cellClass: "num",
    },
  ];
  return (
    <section
      id="detection-coverage-summary"
      class="stack-section detection-coverage-overview"
      aria-labelledby="detection-coverage-title"
    >
      <div class="section-heading-row">
        <div>
          <h3 id="detection-coverage-title" class="section-title">{t("coverage.title")}</h3>
          <p class="section-description">{t("coverage.description")}</p>
        </div>
        <div class="coverage-heading-actions">
          <span class="coverage-freshness">
            {t("coverage.observed", { age: relativeAge(coverage.recorded_at) })}
          </span>
          <a class="btn secondary btn-sm" href={routeHref("rules", { params: { origin: "active" } })}>
            {t("coverage.openRulesCatalog")}
          </a>
        </div>
      </div>
      {coverage.unattributed_error_count > 0 ? (
        <p class="state-block state-unavailable" role="status">
          {t("coverage.unattributedErrors", {
            count: coverage.unattributed_error_count,
            codes: errorCodeSummary(coverage.unattributed_error_codes),
          })}
        </p>
      ) : null}
      <CoverageFunnel
        coverage={coverage}
        resourcesHref={resourcesHref}
        findingsHref={findingsHref}
        onOpenResources={onOpenResources}
        onOpenFindings={onOpenFindings}
      />
      <AttemptComparison coverage={coverage} successfulRun={successfulRun} />
      <div
        class="coverage-type-cards"
        role="group"
        aria-label={t("coverage.typeCaption")}
      >
        {coverage.resource_types.map((row) => (
          <button
            key={row.resource_type}
            type="button"
            class="coverage-type-card"
            onClick={() => onSelectResourceType(row.resource_type)}
          >
            <span class="coverage-type-card-head">
              <strong>{resourceTypeLabel(row.resource_type)}</strong>
              <span>{coveragePercent(row)}%</span>
            </span>
            <span
              class="coverage-type-progress"
              style={`--coverage-percent:${coveragePercent(row)}%`}
              aria-hidden="true"
            />
            <span class="coverage-type-card-counts">
              <span>{t("coverage.column.evaluated")} <strong>{row.evaluated_count}</strong></span>
              <span>{t("coverage.column.held")} <strong>{row.held_count}</strong></span>
              <span>{t("coverage.column.findings")} <strong>{row.finding_count}</strong></span>
              <span>{t("coverage.column.errors")} <strong>{row.error_count}</strong></span>
            </span>
            {row.held_count > 0 ? (
              <small>{t("coverage.holdReasons")}: {heldReasonSummary(row)}</small>
            ) : null}
          </button>
        ))}
      </div>
      <div class="coverage-type-table">
        <DataTable
          columns={columns}
          rows={coverage.resource_types}
          keyOf={(row) => row.resource_type}
          empty={t("coverage.emptyTypes")}
          caption={t("coverage.typeCaption")}
          onRowClick={(row) => onSelectResourceType(row.resource_type)}
          isRowActive={(row) => selectedResourceType === row.resource_type}
          rowActionLabel={(row) => t("coverage.openType", {
            resourceType: resourceTypeLabel(row.resource_type),
          })}
          rowActionControls="detection-resources"
        />
      </div>
      <details class="coverage-exact-table">
        <summary>{t("coverage.showExactTable")}</summary>
        <DataTable
          columns={columns}
          rows={coverage.resource_types}
          keyOf={(row) => row.resource_type}
          empty={t("coverage.emptyTypes")}
          caption={t("coverage.typeCaption")}
        />
      </details>
    </section>
  );
}

function CoverageFunnel({
  coverage,
  resourcesHref,
  findingsHref,
  onOpenResources,
  onOpenFindings,
}: {
  readonly coverage: Extract<AnalyzerCoverageView, { readonly status: "available" }>;
  readonly resourcesHref: string;
  readonly findingsHref: string;
  readonly onOpenResources: () => void;
  readonly onOpenFindings: () => void;
}) {
  const activate = (
    event: JSX.TargetedMouseEvent<HTMLAnchorElement>,
    onActivate: () => void,
  ) => {
    if (
      event.button !== 0
      || event.metaKey
      || event.ctrlKey
      || event.shiftKey
      || event.altKey
    ) return;
    event.preventDefault();
    onActivate();
  };
  const steps = [
    [t("coverage.candidates"), coverage.candidate_count, "#detection-coverage-summary", t("coverage.candidatesHint")],
    [t("coverage.selected"), coverage.selected_count, resourcesHref, null],
    [t("coverage.evaluated"), coverage.evaluated_count, resourcesHref, t("coverage.evaluatedHint")],
    [t("coverage.findings"), coverage.finding_count, findingsHref, t("coverage.findingsHint")],
  ] as const;
  return (
    <div class="coverage-funnel-shell">
      <ol class="coverage-funnel" aria-label={t("coverage.funnelLabel")}>
        {steps.map(([label, value, href, hint]) => {
          const onActivate = href === findingsHref
            ? onOpenFindings
            : href === resourcesHref
              ? onOpenResources
              : null;
          return (
            <li key={label}>
              <a
                href={href}
                onClick={onActivate === null
                  ? undefined
                  : (event) => activate(event, onActivate)}
              >
                <span class="coverage-funnel-copy">
                  <span>{label}</span>
                  {hint ? <small class="coverage-funnel-hint">{hint}</small> : null}
                </span>
                <strong>{value}</strong>
              </a>
            </li>
          );
        })}
      </ol>
      <div class="coverage-attention-summary">
        <Tooltip content={t("coverage.heldHint")}>
          <a href="#detection-coverage-summary">
            {t("coverage.held")} <strong>{coverage.held_count}</strong>
          </a>
        </Tooltip>
        <a
          href={resourcesHref}
          onClick={(event) => activate(event, onOpenResources)}
        >
          {t("coverage.errors")} <strong>{coverage.error_count}</strong>
        </a>
      </div>
    </div>
  );
}

function AttemptComparison({
  coverage,
  successfulRun,
}: {
  readonly coverage: Extract<AnalyzerCoverageView, { readonly status: "available" }>;
  readonly successfulRun: AnalyzerRunView | null;
}) {
  const attemptGap = successfulRun === null
    ? null
    : Math.max(
        0,
        Date.parse(coverage.recorded_at) - Date.parse(successfulRun.recorded_at),
      );
  return (
    <section class="detection-attempt-comparison" aria-labelledby="attempt-comparison-title">
      <div class="section-heading-row">
        <div>
          <h4 id="attempt-comparison-title">{t("successfulRun.comparisonTitle")}</h4>
          <p>{t("successfulRun.description")}</p>
        </div>
        {attemptGap !== null ? (
          <span class="muted small">
            {attemptGap === 0
              ? t("successfulRun.sameAttempt")
              : t("successfulRun.olderBy", { age: durationLabel(attemptGap) })}
          </span>
        ) : null}
      </div>
      <div class="detection-attempt-grid">
        <article>
          <span>{t("successfulRun.latestAttempt")}</span>
          <strong>{relativeAge(coverage.recorded_at)}</strong>
          <small>
            {t("coverage.selected")} {coverage.selected_count} / {t("coverage.held")} {coverage.held_count} / {t("coverage.errors")} {coverage.error_count}
          </small>
        </article>
        <article>
          <span>{t("successfulRun.title")}</span>
          {successfulRun === null ? (
            <strong>{t("successfulRun.unavailable")}</strong>
          ) : (
            <>
              <strong>{relativeAge(successfulRun.recorded_at)}</strong>
              <small>
                {t("successfulRun.targets")} {successfulRun.targets} / {t("successfulRun.findings")} {successfulRun.findings} / {t("successfulRun.sourceCompleteness")}: {successfulRun.source_complete ? t("successfulRun.complete") : t("successfulRun.incomplete")}
              </small>
            </>
          )}
        </article>
      </div>
      <details class="detection-technical-details">
        <summary>{t("coverage.technicalProvenance")}</summary>
        <dl>
          <div><dt>{t("coverage.latestAttemptSource")}</dt><dd><code>{coverage.source}</code></dd></div>
          <div><dt>{t("coverage.recordedAt")}</dt><dd>{formatConsoleTimestamp(coverage.recorded_at)}</dd></div>
          {successfulRun ? (
            <>
              <div><dt>{t("successfulRun.source")}</dt><dd><code>{successfulRun.source}</code></dd></div>
              <div><dt>{t("successfulRun.recordedAt")}</dt><dd>{formatConsoleTimestamp(successfulRun.recorded_at)}</dd></div>
            </>
          ) : null}
        </dl>
      </details>
    </section>
  );
}

/** Render URL-controlled resource filters, selection, and compact detail. */
export function CoverageResources({
  coverage,
  controls,
  onControlsChange,
  onOpenResourceFindings,
  renderPrimaryFindingDetail,
  renderResourceDetail,
  renderScopeDetail,
}: {
  readonly coverage: AnalyzerCoverageView;
  readonly controls: CoverageResourceControls;
  readonly onControlsChange: (
    controls: CoverageResourceControls,
    historyMode: "push" | "replace",
  ) => void;
  readonly onOpenResourceFindings?: (resourceRef: string) => void;
  readonly renderPrimaryFindingDetail?: (
    resource: AnalyzerCoverageResourceView,
  ) => ComponentChildren;
  readonly renderResourceDetail: (
    resource: AnalyzerCoverageResourceView,
  ) => ComponentChildren;
  readonly renderScopeDetail: (
    resource: AnalyzerCoverageResourceView,
  ) => ComponentChildren;
}) {
  if (coverage.status === "unavailable") {
    return (
      <section id="detection-resources" class="stack-section">
        <h3 class="section-title">{t("resources.title")}</h3>
        <UnavailableState
          message={t("coverage.unavailableReason", {
            reason: coverage.unavailable_reason,
          })}
          evidenceState="not-measured"
        />
      </section>
    );
  }
  const filtered = filterCoverageResources(coverage.resources, controls);
  const selected = coverage.resources.find(
    (resource) => resource.resource_ref === controls.selectedRef,
  ) ?? filtered[0] ?? null;
  const selectedOutsideFilters = selected !== null
    && !filtered.some((resource) => resource.resource_ref === selected.resource_ref);
  const resourceTypes = [...new Set(
    coverage.resources.map((resource) => resource.resource_type),
  )].sort();
  const update = (
    patch: Partial<CoverageResourceControls>,
    historyMode: "push" | "replace" = "push",
  ) => onControlsChange({ ...controls, ...patch }, historyMode);
  return (
    <section id="detection-resources" class="stack-section">
      <div class="section-heading-row">
        <div>
          <h3 class="section-title">{t("resources.title")}</h3>
          <p class="section-description">{t("resources.description")}</p>
        </div>
        <span class="filter-summary">
          <span>
            {t("resources.resultCount", {
              filtered: filtered.length,
              total: coverage.resources.length,
            })}
          </span>
        </span>
      </div>
      <div class="detection-resource-toolbar" role="group" aria-label={t("resources.filters")}>
        <label>
          <span>{t("resources.search")}</span>
          <input
            class="form-input"
            type="search"
            aria-label={t("resources.search")}
            value={controls.query}
            placeholder={t("resources.searchPlaceholder")}
            onInput={(event) => update(
              { query: event.currentTarget.value },
              "replace",
            )}
          />
        </label>
        <label>
          <span>{t("resources.resourceType")}</span>
          <select
            class="form-input"
            aria-label={t("resources.resourceType")}
            value={controls.resourceType}
            onChange={(event) => update({ resourceType: event.currentTarget.value })}
          >
            <option value="all">{t("resources.allTypes")}</option>
            {resourceTypes.map((resourceType) => (
              <option key={resourceType} value={resourceType}>
                {resourceTypeLabel(resourceType)}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>{t("resources.evaluation")}</span>
          <select
            class="form-input"
            aria-label={t("resources.evaluation")}
            value={controls.evaluation}
            onChange={(event) => update({
              evaluation: event.currentTarget.value as CoverageResourceControls["evaluation"],
            })}
          >
            <option value="all">{t("resources.allStates")}</option>
            {(["evaluation_error", "finding", "unsupported", "evaluated_no_finding"] as const)
              .map((state) => (
                <option key={state} value={state}>{t(`resources.state.${state}`)}</option>
              ))}
          </select>
        </label>
        <label>
          <span>{t("resources.sort")}</span>
          <select
            class="form-input"
            aria-label={t("resources.sort")}
            value={controls.sort}
            onChange={(event) => update({
              sort: event.currentTarget.value as CoverageResourceControls["sort"],
            })}
          >
            <option value="attention">{t("resources.sortAttention")}</option>
            <option value="resource_type">{t("resources.sortType")}</option>
            <option value="name">{t("resources.sortName")}</option>
          </select>
        </label>
        <button
          type="button"
          class="secondary"
          onClick={() => onControlsChange(
            {
              query: "",
              resourceType: "all",
              evaluation: "all",
              sort: "attention",
              selectedRef: controls.selectedRef,
            },
            "push",
          )}
        >
          {t("resources.clearFilters")}
        </button>
      </div>
      {filtered.length === 0 && selected === null ? (
        <EmptyState title={t("resources.noMatches")} body={t("resources.noMatchesBody")} />
      ) : (
        <>
          {selectedOutsideFilters ? (
            <p class="state-block state-unavailable">
              {t("resources.selectionOutsideFilters")}
            </p>
          ) : null}
          <div class="detection-record-workspace">
            <aside class="detection-record-list" aria-label={t("resources.listLabel")}>
              <h4>{t("resources.listTitle")}</h4>
              {filtered.length === 0 ? (
                <p class="muted small detection-list-empty">{t("resources.noMatches")}</p>
              ) : (
                <ul>
                  {filtered.map((resource, index) => {
                    const parsed = parseResourceRefDisplay(resource.resource_ref);
                    return (
                      <li key={resource.resource_ref}>
                        <button
                          type="button"
                          aria-pressed={selected?.resource_ref === resource.resource_ref}
                          aria-controls="detection-resource-detail"
                          onClick={() => update({ selectedRef: resource.resource_ref })}
                          onKeyDown={(event) => {
                            const nextIndex = event.key === "ArrowDown"
                              ? Math.min(index + 1, filtered.length - 1)
                              : event.key === "ArrowUp"
                                ? Math.max(index - 1, 0)
                                : event.key === "Home"
                                  ? 0
                                  : event.key === "End"
                                    ? filtered.length - 1
                                    : null;
                            if (nextIndex === null || nextIndex === index) return;
                            event.preventDefault();
                            const targetResource = filtered[nextIndex];
                            if (!targetResource) return;
                            update({ selectedRef: targetResource.resource_ref });
                            const list = event.currentTarget.closest("ul");
                            list?.querySelectorAll<HTMLButtonElement>("button")[nextIndex]?.focus();
                          }}
                        >
                          <span class="detection-resource-row-head">
                            <strong class="mono">
                              {parsed.hasStructuredScope ? parsed.shortName : resource.resource_ref}
                            </strong>
                            <StatusPill
                              kind={evaluationKind(resource.evaluation_state)}
                              label={t(`resources.state.${resource.evaluation_state}`)}
                            />
                          </span>
                          <span>
                            {resourceTypeLabel(resource.resource_type)}
                            {resource.finding_count > 0
                              ? ` / ${t("coverage.findings")} ${resource.finding_count}`
                              : ""}
                            {resource.error_count > 0
                              ? ` / ${t("coverage.errors")} ${resource.error_count}`
                              : ""}
                          </span>
                          {parsed.hasStructuredScope ? (
                            <small class="detection-resource-row-scope mono">
                              {parsed.resourceGroup} · {parsed.scopeId}
                              <span class="sr-only"> {resource.resource_ref}</span>
                            </small>
                          ) : null}
                        </button>
                      </li>
                    );
                  })}
                </ul>
              )}
            </aside>
            {selected ? (
              <ResourceDetail
                resource={selected}
                onOpenResourceFindings={onOpenResourceFindings}
                renderPrimaryFindingDetail={renderPrimaryFindingDetail}
                renderResourceDetail={renderResourceDetail}
              />
            ) : null}
          </div>
          {selected ? renderScopeDetail(selected) : null}
          <span class="sr-only" role="status" aria-live="polite">
            {selected ? t("resources.selectionChanged", {
              resource: selected.resource_ref,
            }) : ""}
          </span>
        </>
      )}
    </section>
  );
}

function ResourceDetail({
  resource,
  onOpenResourceFindings,
  renderPrimaryFindingDetail,
  renderResourceDetail,
}: {
  readonly resource: AnalyzerCoverageResourceView;
  readonly onOpenResourceFindings: ((resourceRef: string) => void) | undefined;
  readonly renderPrimaryFindingDetail: ((
    resource: AnalyzerCoverageResourceView,
  ) => ComponentChildren) | undefined;
  readonly renderResourceDetail: (
    resource: AnalyzerCoverageResourceView,
  ) => ComponentChildren;
}) {
  const parsed = parseResourceRefDisplay(resource.resource_ref);
  const primaryFindingDetail = renderPrimaryFindingDetail?.(resource) ?? null;
  const exactDetail = renderResourceDetail(resource);
  return (
    <article id="detection-resource-detail" class="detection-record-detail">
      <div class="detection-resource-detail-head">
        <div class="detection-resource-title-stack">
          {parsed.hasStructuredScope ? (
            <strong class="detection-resource-short-title mono">{parsed.shortName}</strong>
          ) : null}
          <h4 class="panel-title">
            <a class="mono" href={architectureHref(resource.resource_ref)}>
              {resource.resource_ref}
            </a>
          </h4>
          <span class="muted small">
            {resourceTypeLabel(resource.resource_type)}
            {resourceKindLabel(resource.resource_kind) !== resource.resource_kind
              ? ` · ${resourceKindLabel(resource.resource_kind)}`
              : ""}
          </span>
        </div>
        <div class="detection-resource-detail-actions">
          <StatusPill
            kind={evaluationKind(resource.evaluation_state)}
            label={t(`resources.state.${resource.evaluation_state}`)}
          />
          <CopyButton text={resource.resource_ref} label={t("resources.copyResourceId")} />
        </div>
      </div>
      <div class="detection-resource-quick-links">
        <a class="btn secondary btn-sm" href={architectureHref(resource.resource_ref)}>
          {t("resources.openArchitectureMap")}
        </a>
        <a class="btn secondary btn-sm" href={routeHref("rules", { params: { q: resource.resource_type } })}>
          {t("resources.openResourceRules", {
            resourceType: resourceTypeLabel(resource.resource_type),
          })}
        </a>
        {resource.finding_count > 0 && onOpenResourceFindings ? (
          <button
            type="button"
            class="btn secondary btn-sm"
            onClick={() => onOpenResourceFindings(resource.resource_ref)}
          >
            {t("resources.openResourceFindings", { count: resource.finding_count })}
          </button>
        ) : null}
      </div>
      <dl class="details-list">
        <div><dt>{t("coverage.findings")}</dt><dd>{resource.finding_count}</dd></div>
        <div><dt>{t("coverage.errors")}</dt><dd>{resource.error_count}</dd></div>
        <div><dt>{t("resources.delivery")}</dt><dd>{publicationSummary(resource)}</dd></div>
        {parsed.hasStructuredScope && parsed.resourceGroup ? (
          <div><dt>{t("resources.resourceGroup")}</dt><dd><code class="mono">{parsed.resourceGroup}</code></dd></div>
        ) : null}
        {parsed.hasStructuredScope && parsed.scopeId ? (
          <div><dt>{t("resources.scope")}</dt><dd><code class="mono">{parsed.scopeId}</code></dd></div>
        ) : null}
      </dl>
      {resource.error_codes.length > 0 ? (
        <div class="detection-error-codes">
          <strong>{t("resources.errorReasons")}</strong>
          <ul>{resource.error_codes.map((code) => (
            <li key={code}>{errorCodeLabel(code)}</li>
          ))}</ul>
        </div>
      ) : null}
      {resource.evaluation_state === "evaluated_no_finding" ? (
        <p class="muted small">{t("resources.noHealthClaim")}</p>
      ) : null}
      {primaryFindingDetail}
      <details class="detection-technical-details">
        <summary>{t("resources.technicalDetails")}</summary>
        <dl>
          <div>
            <dt>{t("resources.kind")}</dt>
            <dd>
              {resourceKindLabel(resource.resource_kind) !== resource.resource_kind ? (
                <span>{resourceKindLabel(resource.resource_kind)} </span>
              ) : null}
              <code>{resource.resource_kind}</code>
            </dd>
          </div>
          <div>
            <dt>{t("resources.canonicalType")}</dt>
            <dd>
              {resourceTypeLabel(resource.resource_type) !== resource.resource_type ? (
                <span>{resourceTypeLabel(resource.resource_type)} </span>
              ) : null}
              <code>{resource.resource_type}</code>
            </dd>
          </div>
          {parsed.hasStructuredScope && parsed.providerType ? (
            <div>
              <dt>{t("resources.providerType")}</dt>
              <dd><code>{parsed.providerType}</code></dd>
            </div>
          ) : null}
        </dl>
      </details>
      {exactDetail ? (
        <details class="detection-resource-extension">
          <summary>{t("resources.showResourceEvidence")}</summary>
          {exactDetail}
        </details>
      ) : null}
    </article>
  );
}

/** Return a localized label while preserving unknown canonical resource types. */
export function resourceTypeLabel(resourceType: string): string {
  const keys: Readonly<Record<string, string>> = {
    "api-gateway": "apiGateway",
    "kubernetes-cluster": "kubernetesCluster",
    "kubernetes-node-pool": "kubernetesNodePool",
    "llm-endpoint": "llmEndpoint",
    "mysql-server": "mysqlServer",
    "postgresql-server": "postgresqlServer",
    "sql-database": "sqlDatabase",
    "network.application-gateway": "applicationGateway",
    "compute.vm-scale-set": "computeVmScaleSet",
    "compute.vm": "computeVm",
    "object-storage": "objectStorage",
    "secret-store": "secretStore",
    cache: "cache",
    disk: "disk",
    "managed-identity": "managedIdentity",
    "network.nsg": "networkNsg",
    "network.vnet": "networkVnet",
    "resource-group": "resourceGroup",
    subscription: "subscription",
    unclassified: "unclassified",
  };
  const key = keys[resourceType];
  return key === undefined ? resourceType : t(`resourceType.${key}`);
}

export function resourceKindLabel(resourceKind: string): string {
  const known = new Set([
    "virtual_machine_scale_set",
    "virtual_machine",
    "aks_cluster",
    "kubernetes_pod",
    "api_management",
    "mysql_flexible_server",
    "llm_endpoint",
    "application_gateway",
  ]);
  return known.has(resourceKind) ? t(`resourceKind.${resourceKind}`) : resourceKind;
}

export function heldReasonSummary(row: AnalyzerCoverageResourceTypeView): string {
  const reasons = Object.entries(row.held_reason_counts)
    .map(([reason, count]) => `${heldReasonLabel(reason)} ${count}`);
  return reasons.length > 0 ? reasons.join(", ") : t("coverage.noHoldReason");
}

export function errorCodeSummary(errorCodes: readonly string[]): string {
  return errorCodes.length > 0
    ? errorCodes.map(errorCodeLabel).join(", ")
    : t("coverage.noErrors");
}

function publicationSummary(resource: AnalyzerCoverageResourceView): string {
  const states = Object.entries(resource.publication_counts)
    .filter(([, count]) => count > 0)
    .map(([state, count]) => `${t(`analyzerLifecycle.publication.${state}`)} ${count}`);
  return states.length > 0 ? states.join(", ") : t("resources.noPublication");
}

function heldReasonLabel(reason: string): string {
  const known = new Set([
    "stale_state_fact",
    "unusable_state_fact",
    "unverified_state_fact",
    "selection_limit",
    "duplicate_candidate",
    "not_selected",
    "unmapped_resource_type",
    "malformed_resource",
    "legacy_unspecified",
  ]);
  return known.has(reason) ? t(`coverage.holdReason.${reason}`) : reason;
}

function errorCodeLabel(code: string): string {
  const known = new Set([
    "analyzer_timeout",
    "analyzer_failure",
    "publication_failure",
    "receipt_persistence_failure",
    "legacy_unspecified",
  ]);
  return known.has(code) ? t(`resources.errorCode.${code}`) : code;
}

function evaluationKind(state: AnalyzerEvaluationState): PillKind {
  if (state === "finding") return "warning";
  if (state === "evaluation_error") return "danger";
  if (state === "unsupported") return "neutral";
  return "info";
}

function coveragePercent(row: AnalyzerCoverageResourceTypeView): number {
  return row.candidate_count === 0
    ? 0
    : Math.round((100 * row.evaluated_count) / row.candidate_count);
}

function relativeAge(timestamp: string, now = Date.now()): string {
  const difference = Math.max(0, now - Date.parse(timestamp));
  return t("coverage.ageAgo", { age: durationLabel(difference) });
}

function durationLabel(milliseconds: number): string {
  const seconds = Math.round(milliseconds / 1_000);
  if (seconds < 60) return t("coverage.ageSeconds", { count: seconds });
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return t("coverage.ageMinutes", { count: minutes });
  const hours = Math.round(minutes / 60);
  if (hours < 24) return t("coverage.ageHours", { count: hours });
  return t("coverage.ageDays", { count: Math.round(hours / 24) });
}
