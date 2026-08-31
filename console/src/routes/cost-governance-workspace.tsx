import type { ComponentChildren } from "preact";
import { useMemo, useState } from "preact/hooks";
import type {
  CostGovernanceAnalytics,
  CostGovernanceProjection,
  CostGovernanceRecommendation,
  CostGovernanceTrendPoint,
} from "../api-cost-governance";
import { routeHref } from "../router";
import {
  costLocale,
  formatCompact,
  formatCurrency,
  formatKnownTotal,
  formatNullablePercent,
  formatSignedPercent,
  recommendationSavings,
  totalHint,
} from "./cost-governance-format";
import {
  costShare,
  summarizeCostGovernance,
  type CostGovernanceRow,
  type CostGovernanceSummary,
} from "./cost-governance.view-model";
import {
  RecommendationInspector,
  RecommendationTable,
  ResourceInspector,
  ResourceTable,
} from "./cost-governance-resource-widgets";
import { t } from "./i18n/cost-governance";

export function CostGovernanceWorkspace({
  projection,
}: {
  readonly projection: CostGovernanceProjection;
}) {
  const summary = summarizeCostGovernance(projection);
  return (
    <section class="cost-governance-workspace" aria-live="polite">
      <EvidenceToolbar projection={projection} summary={summary} />
      {projection.surface === "overview" ? (
        <Overview projection={projection} summary={summary} analytics={projection.analytics ?? null} />
      ) : projection.surface === "resource-efficiency" ? (
        <ResourceEfficiency projection={projection} summary={summary} analytics={projection.analytics ?? null} />
      ) : projection.surface === "optimization-cases" ? (
        <OptimizationCases summary={summary} analytics={projection.analytics ?? null} />
      ) : (
        <Outcomes summary={summary} />
      )}
    </section>
  );
}

function EvidenceToolbar({
  projection,
  summary,
}: {
  readonly projection: CostGovernanceProjection;
  readonly summary: CostGovernanceSummary;
}) {
  return (
    <div class="cost-evidence-toolbar">
      <div>
        <span>{t("costGovernance.evidence.scope")}</span>
        <strong>{t("costGovernance.evidence.currentScope")}</strong>
      </div>
      <div>
        <span>{t("costGovernance.evidence.source")}</span>
        <strong>{projection.source_authority}</strong>
      </div>
      <div>
        <span>{t("costGovernance.evidence.period")}</span>
        <strong>{t("costGovernance.evidence.retainedWindow")}</strong>
      </div>
      <div class="cost-evidence-state">
        <span>{t("costGovernance.evidence.coverage")}</span>
        <strong>{projection.complete
          ? t("costGovernance.summary.complete")
          : t("costGovernance.summary.incomplete")}</strong>
        <i class={projection.complete ? "complete" : "partial"} aria-hidden="true" />
        <small>{t("costGovernance.evidence.records", { count: summary.sourceRecordCount })}</small>
      </div>
    </div>
  );
}

function Overview({
  projection,
  summary,
  analytics,
}: {
  readonly projection: CostGovernanceProjection;
  readonly summary: CostGovernanceSummary;
  readonly analytics: CostGovernanceAnalytics | null;
}) {
  const [budgetRef, setBudgetRef] = useState(analytics?.budgets[0]?.budget_ref ?? "");
  const budget = analytics?.budgets.find((item) => item.budget_ref === budgetRef)
    ?? analytics?.budgets[0]
    ?? null;
  const drivers = summary.rows.filter((row) => row.relativeChange !== null);
  return (
    <>
      <div class="cost-overview-grid">
        <article class="cost-visual-card cost-hero-card">
          <CardHeader
            eyebrow={t("costGovernance.overview.trendEyebrow")}
            title={t("costGovernance.overview.trendTitle")}
            description={t("costGovernance.overview.trendDescription")}
            action={analytics && analytics.budgets.length > 1 ? (
              <label class="cost-budget-select">
                <span>{t("costGovernance.overview.budget")}</span>
                <select value={budget?.budget_ref ?? ""} onChange={(event) => setBudgetRef(event.currentTarget.value)}>
                  {analytics.budgets.map((item, index) => (
                    <option value={item.budget_ref} key={item.budget_ref}>
                      {t("costGovernance.overview.budgetOption", { index: index + 1, amount: formatCurrency(item.amount, item.currency) })}
                    </option>
                  ))}
                </select>
              </label>
            ) : null}
          />
          <div class="cost-metric-rail">
            <Metric primary label={t("costGovernance.metrics.observedCost")} value={budget ? formatCurrency(budget.current_spend, budget.currency) : formatKnownTotal(summary)} hint={budget ? t("costGovernance.metrics.budgetCurrentSpend") : totalHint(summary)} />
            <Metric label={t("costGovernance.metrics.forecast")} value={budget?.forecast_spend === null || budget?.forecast_spend === undefined ? "-" : formatCurrency(budget.forecast_spend, budget.currency)} hint={budget?.forecast_spend === null || budget?.forecast_spend === undefined ? t("costGovernance.metrics.forecastUnavailable") : t("costGovernance.metrics.providerForecast")} />
            <Metric label={t("costGovernance.metrics.budget")} value={budget ? formatNullablePercent(budget.current_spend / budget.amount) : "-"} hint={budget ? t("costGovernance.metrics.budgetOf", { amount: formatCurrency(budget.amount, budget.currency) }) : t("costGovernance.metrics.budgetUnavailable")} />
            <Metric label={t("costGovernance.metrics.verifiedSavings")} value="-" hint={t("costGovernance.metrics.savingsUnavailable")} saving />
          </div>
          <TrendChart rows={analytics?.trend ?? []} />
          <UnavailableContribution />
          <CardFooter projection={projection} />
        </article>

        <article class="cost-visual-card cost-spend-flow-card">
          <CardHeader
            eyebrow={t("costGovernance.overview.flowEyebrow")}
            title={t("costGovernance.overview.flowTitle")}
            description={t("costGovernance.overview.flowDescription")}
            value={formatKnownTotal(summary)}
            valueLabel={t("costGovernance.metrics.observedCost")}
          />
          <SpendFlow summary={summary} />
          <div class="cost-flow-summary">
            <span><strong>{summary.rows.length}</strong>{t("costGovernance.metrics.serviceGroups")}</span>
            <span><strong>{summary.sourceRecordCount}</strong>{t("costGovernance.metrics.retainedObservations")}</span>
            <span><strong>-</strong>{t("costGovernance.overview.resourceDetailUnavailable")}</span>
          </div>
          <a class="cost-text-action" href={routeHref("cost-governance", { segments: ["resource-efficiency"] })}>
            {t("costGovernance.overview.openResourceEfficiency")} <span aria-hidden="true">-&gt;</span>
          </a>
        </article>
      </div>

      <div class="cost-overview-grid lower">
        <article class="cost-visual-card">
          <CardHeader
            eyebrow={t("costGovernance.overview.driversEyebrow")}
            title={t("costGovernance.overview.driversTitle")}
            description={t("costGovernance.overview.driversDescription")}
          />
          {drivers.length > 0 ? <CostDrivers rows={drivers} /> : (
            <UnavailablePanel
              title={t("costGovernance.overview.driversUnavailableTitle")}
              body={t("costGovernance.overview.driversUnavailableBody")}
            />
          )}
        </article>
        <AttentionPanel projection={projection} summary={summary} />
      </div>
    </>
  );
}

function ResourceEfficiency({
  projection,
  summary,
  analytics,
}: {
  readonly projection: CostGovernanceProjection;
  readonly summary: CostGovernanceSummary;
  readonly analytics: CostGovernanceAnalytics | null;
}) {
  const recommendations = analytics?.recommendations ?? [];
  const savings = recommendationSavings(recommendations);
  const utilizationComplete = recommendations.length > 0
    && recommendations.every((item) => item.utilization_percent !== null);
  const [query, setQuery] = useState("");
  const [selectedId, setSelectedId] = useState(
    recommendations[0]?.recommendation_ref ?? summary.rows[0]?.id ?? "",
  );
  const filtered = useMemo(() => {
    const normalized = query.trim().toLocaleLowerCase(costLocale());
    return normalized
      ? summary.rows.filter((row) =>
        `${row.label} ${row.service}`.toLocaleLowerCase(costLocale()).includes(normalized)
      )
      : summary.rows;
  }, [query, summary.rows]);
  const filteredRecommendations = useMemo(() => {
    const normalized = query.trim().toLocaleLowerCase(costLocale());
    return normalized
      ? recommendations.filter((item) =>
        `${item.problem} ${item.solution} ${item.resource_type}`.toLocaleLowerCase(costLocale())
          .includes(normalized)
      )
      : recommendations;
  }, [query, recommendations]);
  const selected = summary.rows.find((row) => row.id === selectedId) ?? filtered[0] ?? null;
  const selectedRecommendation = recommendations.find(
    (item) => item.recommendation_ref === selectedId,
  ) ?? filteredRecommendations[0] ?? null;
  return (
    <>
      <div class="cost-kpi-grid">
        <Metric label={t("costGovernance.resource.runRate")} value={formatKnownTotal(summary)} hint={totalHint(summary)} />
        <Metric label={t("costGovernance.resource.opportunity")} value={savings.total === null ? "-" : formatCurrency(savings.total, savings.currency)} hint={recommendations.length ? t("costGovernance.resource.candidateCount", { count: recommendations.length }) : t("costGovernance.resource.opportunityUnavailable")} />
        <Metric label={t("costGovernance.resource.capacityRisk")} value={utilizationComplete ? String(recommendations.filter((item) => item.utilization_percent! >= 80).length) : "-"} hint={utilizationComplete ? t("costGovernance.resource.hourlyP95") : t("costGovernance.resource.utilizationUnavailable")} />
        <Metric label={t("costGovernance.metrics.verifiedSavings")} value="-" hint={t("costGovernance.metrics.savingsUnavailable")} />
      </div>
      <article class="cost-visual-card cost-efficiency-map">
        <CardHeader
          eyebrow={t("costGovernance.resource.mapEyebrow")}
          title={recommendations.length ? t("costGovernance.resource.recommendationMapTitle") : t("costGovernance.resource.mapTitle")}
          description={recommendations.length ? t("costGovernance.resource.recommendationMapDescription") : t("costGovernance.resource.mapDescription")}
          value={String(recommendations.length || summary.rows.length)}
          valueLabel={recommendations.length ? t("costGovernance.resource.candidateRecommendations") : t("costGovernance.resource.analyzedGroups")}
        />
        {recommendations.length > 0 ? (
          <RecommendationMap recommendations={recommendations} onSelect={setSelectedId} selectedId={selectedRecommendation?.recommendation_ref ?? ""} />
        ) : (
          <CostUtilizationMap rows={summary.rows} totals={summary.totalsByCurrency} onSelect={setSelectedId} selectedId={selected?.id ?? ""} />
        )}
      </article>
      <DecisionStrip count={recommendations.length || summary.rows.length} />
      <div class="cost-resource-workspace">
        <section class="cost-resource-region">
          <header class="cost-section-head">
            <div>
              <h2>{t("costGovernance.resource.tableTitle")}</h2>
              <p>{t("costGovernance.resource.tableDescription")}</p>
            </div>
            <label class="cost-search">
              <span class="sr-only">{t("costGovernance.resource.search")}</span>
              <input
                type="search"
                value={query}
                placeholder={t("costGovernance.resource.search")}
                onInput={(event) => setQuery(event.currentTarget.value)}
              />
            </label>
          </header>
          {recommendations.length > 0 ? (
            <RecommendationTable
              recommendations={filteredRecommendations}
              selectedId={selectedRecommendation?.recommendation_ref ?? ""}
              onSelect={setSelectedId}
            />
          ) : (
            <ResourceTable rows={filtered} selectedId={selected?.id ?? ""} totals={summary.totalsByCurrency} complete={projection.complete} onSelect={setSelectedId} />
          )}
          <footer class="cost-table-foot">
            <span>{t("costGovernance.resource.visibleRows", { count: recommendations.length ? filteredRecommendations.length : filtered.length, total: recommendations.length || summary.rows.length })}</span>
          </footer>
        </section>
        {selectedRecommendation ? (
          <RecommendationInspector recommendation={selectedRecommendation} />
        ) : (
          <ResourceInspector row={selected} complete={projection.complete} />
        )}
      </div>
    </>
  );
}

function OptimizationCases({
  summary,
  analytics,
}: {
  readonly summary: CostGovernanceSummary;
  readonly analytics: CostGovernanceAnalytics | null;
}) {
  const cases = summary.rows.filter((row) => row.kind === "optimization_case");
  const recommendations = analytics?.recommendations ?? [];
  const savings = recommendationSavings(recommendations);
  return (
    <>
      <div class="cost-kpi-grid">
        <Metric label={t("costGovernance.cases.openCases")} value={cases.length ? String(cases.length) : "-"} hint={cases.length ? t("costGovernance.cases.projectedCases") : t("costGovernance.cases.noCases")} />
        <Metric label={t("costGovernance.resource.opportunity")} value={savings.total === null ? "-" : formatCurrency(savings.total, savings.currency)} hint={recommendations.length ? t("costGovernance.cases.candidateOnly", { count: recommendations.length }) : t("costGovernance.resource.opportunityUnavailable")} />
        <Metric label={t("costGovernance.cases.pendingApproval")} value="-" hint={t("costGovernance.cases.approvalUnavailable")} />
        <Metric label={t("costGovernance.cases.capacityProtection")} value="-" hint={t("costGovernance.resource.utilizationUnavailable")} />
      </div>
      <div class="cost-case-grid">
        <article class="cost-visual-card">
          <CardHeader eyebrow={t("costGovernance.cases.mixEyebrow")} title={t("costGovernance.cases.mixTitle")} description={t("costGovernance.cases.mixDescription")} />
          <OpportunityBars recommendations={recommendations} />
          <CardFooterText label={t("costGovernance.cases.netEffect")} value="-" />
        </article>
        <article class="cost-visual-card">
          <CardHeader eyebrow={t("costGovernance.cases.flowEyebrow")} title={t("costGovernance.cases.flowTitle")} description={t("costGovernance.cases.flowDescription")} />
          <DecisionFunnel summary={summary} cases={cases} recommendations={recommendations} />
        </article>
      </div>
      <article class="cost-visual-card cost-case-list">
        <CardHeader eyebrow={t("costGovernance.cases.listEyebrow")} title={t("costGovernance.cases.listTitle")} description={t("costGovernance.cases.listDescription")} />
        {cases.length > 0 ? <CaseRows rows={cases} /> : recommendations.length > 0 ? (
          <CandidateRows recommendations={recommendations} />
        ) : (
          <UnavailablePanel title={t("costGovernance.cases.unavailableTitle")} body={t("costGovernance.cases.unavailableBody")} />
        )}
      </article>
    </>
  );
}

function Outcomes({ summary }: { readonly summary: CostGovernanceSummary }) {
  const outcomes = summary.rows.filter((row) => row.kind === "outcome");
  return (
    <>
      <div class="cost-kpi-grid">
        <Metric label={t("costGovernance.outcomes.verifiedSavings")} value="-" hint={t("costGovernance.outcomes.noSettlement")} />
        <Metric label={t("costGovernance.outcomes.realization")} value="-" hint={t("costGovernance.outcomes.noSettlement")} />
        <Metric label={t("costGovernance.outcomes.sloRegression")} value="-" hint={t("costGovernance.outcomes.effectUnavailable")} />
        <Metric label={t("costGovernance.outcomes.pendingSettlement")} value="-" hint={t("costGovernance.outcomes.noSettlement")} />
      </div>
      <div class="cost-outcome-grid">
        <article class="cost-visual-card">
          <CardHeader eyebrow={t("costGovernance.outcomes.waterfallEyebrow")} title={t("costGovernance.outcomes.waterfallTitle")} description={t("costGovernance.outcomes.waterfallDescription")} />
          <UnavailableWaterfall />
        </article>
        <article class="cost-visual-card">
          <CardHeader eyebrow={t("costGovernance.outcomes.unitEyebrow")} title={t("costGovernance.outcomes.unitTitle")} description={t("costGovernance.outcomes.unitDescription")} value="-" valueLabel={t("costGovernance.outcomes.unitUnavailable")} />
          <UnavailableUnitChart />
        </article>
      </div>
      <article class="cost-visual-card">
        <CardHeader eyebrow={t("costGovernance.outcomes.effectEyebrow")} title={t("costGovernance.outcomes.effectTitle")} description={t("costGovernance.outcomes.effectDescription")} />
        {outcomes.length > 0 ? <SettlementGrid rows={outcomes} /> : (
          <UnavailablePanel title={t("costGovernance.outcomes.unavailableTitle")} body={t("costGovernance.outcomes.unavailableBody")} />
        )}
      </article>
    </>
  );
}

function TrendChart({ rows }: { readonly rows: readonly CostGovernanceTrendPoint[] }) {
  const currencies = new Set(rows.map((row) => row.currency).filter(Boolean));
  const pointsInTime = [...rows].sort(
    (left, right) => Date.parse(left.observed_on) - Date.parse(right.observed_on),
  );
  if (
    pointsInTime.length < 2
    || currencies.size !== 1
  ) {
    return (
      <div class="cost-chart-placeholder" role="img" aria-label={t("costGovernance.overview.trendUnavailableTitle")}>
        <div class="cost-chart-grid" aria-hidden="true" />
        <span>{t("costGovernance.overview.trendUnavailableTitle")}</span>
        <small>{t("costGovernance.overview.trendUnavailableBody")}</small>
      </div>
    );
  }
  const values = pointsInTime.map((row) => row.amount);
  const maximum = Math.max(...values, 1);
  const points = values.map((value, index) => {
    const x = 42 + (index / (values.length - 1)) * 676;
    const y = 250 - (value / maximum) * 205;
    return `${x},${y}`;
  }).join(" ");
  return (
    <svg class="cost-trend-chart" viewBox="0 0 760 280" role="img" aria-label={t("costGovernance.overview.trendTitle")}>
      <path class="grid" d="M42 45H720M42 95H720M42 145H720M42 195H720M42 245H720" />
      <polyline points={points} />
      <desc>{pointsInTime.map((row) =>
        `${row.observed_on}: ${formatCurrency(row.amount, row.currency)}`
      ).join("; ")}</desc>
      {pointsInTime.map((row, index) => (
        <circle key={`${row.observed_on}-${row.currency}`} cx={42 + (index / (rows.length - 1)) * 676} cy={250 - (row.amount / maximum) * 205} r="4">
          <title>{row.observed_on}: {formatCurrency(row.amount, row.currency)}</title>
        </circle>
      ))}
    </svg>
  );
}

function UnavailableContribution() {
  return (
    <div class="cost-contribution unavailable">
      <div><span>{t("costGovernance.metrics.verifiedSavings")}</span><strong>-</strong></div>
      <i aria-hidden="true" />
      <small>{t("costGovernance.metrics.savingsUnavailable")}</small>
    </div>
  );
}

function SpendFlow({ summary }: { readonly summary: CostGovernanceSummary }) {
  const rows = summary.rows.slice(0, 6);
  return (
    <div class="cost-flow" role="group" aria-label={t("costGovernance.overview.flowTitle")}>
      <div class="cost-flow-head"><span>{t("costGovernance.overview.subscription")}</span><span>{t("costGovernance.overview.serviceType")}</span><span>{t("costGovernance.overview.resourceDetail")}</span></div>
      <div class="cost-flow-source">
        <i />
        <strong>{t("costGovernance.evidence.currentScope")}</strong>
        <small>{formatKnownTotal(summary)}</small>
      </div>
      <ol>{rows.map((row) => {
        const share = costShare(row, summary.totalsByCurrency);
        return (
          <li key={row.id}>
            <i style={{ width: `${Math.max((share ?? 0) * 100, share === null ? 0 : 3)}%` }} />
            <span>{row.label}</span>
            <strong>{formatCurrency(row.amount, row.currency, row.amountLabel)}</strong>
          </li>
        );
      })}</ol>
      <div class="cost-flow-unavailable">
        <i />
        <strong>{t("costGovernance.overview.resourceDetailUnavailable")}</strong>
        <small>{t("costGovernance.overview.resourceDetailReason")}</small>
      </div>
    </div>
  );
}

function CostDrivers({ rows }: { readonly rows: readonly CostGovernanceRow[] }) {
  const maximum = Math.max(...rows.map((row) => Math.abs(row.relativeChange ?? 0)), 1);
  return (
    <ol class="cost-driver-list">{rows.slice(0, 5).map((row) => (
      <li key={row.id}>
        <span><strong>{row.label}</strong><small>{row.status}</small></span>
        <i><b style={{ width: `${Math.abs(row.relativeChange ?? 0) / maximum * 100}%` }} /></i>
        <strong>{formatSignedPercent(row.relativeChange)}</strong>
      </li>
    ))}</ol>
  );
}

function AttentionPanel({
  projection,
  summary,
}: {
  readonly projection: CostGovernanceProjection;
  readonly summary: CostGovernanceSummary;
}) {
  const cases = summary.rows.filter((row) => row.kind === "optimization_case").length;
  const outcomes = summary.rows.filter((row) => row.kind === "outcome").length;
  return (
    <article class="cost-visual-card">
      <CardHeader eyebrow={t("costGovernance.attention.eyebrow")} title={t("costGovernance.attention.title")} description={t("costGovernance.attention.description")} />
      <div class="cost-attention-list">
        <a href={routeHref("cost-governance", { segments: ["optimization-cases"] })}><span>{cases || "-"}</span><strong>{t("costGovernance.cases.openCases")}</strong><small>{cases ? t("costGovernance.cases.projectedCases") : t("costGovernance.cases.noCases")}</small></a>
        <a href={routeHref("cost-governance", { segments: ["resource-efficiency"] })}><span>{summary.rows.length}</span><strong>{t("costGovernance.resource.reviewRequired")}</strong><small>{t("costGovernance.resource.costOnlyEvidence")}</small></a>
        <a href={routeHref("cost-governance", { segments: ["outcomes"] })}><span>{outcomes || "-"}</span><strong>{t("costGovernance.outcomes.pendingSettlement")}</strong><small>{outcomes ? t("costGovernance.outcomes.projectedRecords", { count: outcomes }) : t("costGovernance.outcomes.noSettlement")}</small></a>
      </div>
      {!projection.complete ? <p class="cost-inline-warning">{t("costGovernance.incomplete")}</p> : null}
    </article>
  );
}

function CostUtilizationMap({
  rows,
  totals,
  onSelect,
  selectedId,
}: {
  readonly rows: readonly CostGovernanceRow[];
  readonly totals: Readonly<Record<string, number>>;
  readonly onSelect: (id: string) => void;
  readonly selectedId: string;
}) {
  const currencies = new Set(rows.map((row) => row.currency).filter(Boolean));
  if (currencies.size !== 1 || rows.some((row) => row.amount === null)) {
    return (
      <UnavailablePanel
        title={t("costGovernance.resource.mapUnavailableTitle")}
        body={t("costGovernance.resource.mapUnavailableBody")}
      />
    );
  }

  const maximum = Math.max(...rows.map((row) => row.amount ?? 0), 1);
  return (
    <div class="cost-scatter-shell">
      <div class="cost-scatter-y"><span>{formatCompact(maximum)}</span><span>{formatCompact(maximum / 2)}</span><span>0</span></div>
      <div class="cost-scatter">
        <span class="cost-scatter-banner">{t("costGovernance.resource.utilizationAxisUnavailable")}</span>
        {rows.slice(0, 8).map((row, index) => {
          const y = 88 - ((row.amount ?? 0) / maximum) * 72;
          const x = 13 + (index % 4) * 24;
          return (
            <button
              key={row.id}
              type="button"
              class={row.id === selectedId ? "selected" : ""}
              style={{ "--x": `${x}%`, "--y": `${y}%`, "--size": `${18 + Math.max((costShare(row, totals) ?? 0) * 24, 0)}px` }}
              onClick={() => onSelect(row.id)}
              aria-label={`${row.label}, ${formatCurrency(row.amount, row.currency, row.amountLabel)}`}
            ><span>{row.label}</span></button>
          );
        })}
      </div>
      <div class="cost-scatter-x"><span>{t("costGovernance.resource.utilizationUnavailable")}</span></div>
    </div>
  );
}

function RecommendationMap({
  recommendations,
  onSelect,
  selectedId,
}: {
  readonly recommendations: readonly CostGovernanceRecommendation[];
  readonly onSelect: (id: string) => void;
  readonly selectedId: string;
}) {
  const maximum = Math.max(...recommendations.map((item) => item.monthly_savings ?? 0), 1);
  return (
    <div class="cost-scatter-shell">
      <div class="cost-scatter-y">
        <span>{formatCompact(maximum)}</span><span>{formatCompact(maximum / 2)}</span><span>0</span>
      </div>
      <div class="cost-scatter recommendations">
        <span class="cost-scatter-banner">{t("costGovernance.resource.recommendationMapBanner")}</span>
        {recommendations.slice(0, 12).map((item, index) => {
          const y = 88 - ((item.monthly_savings ?? 0) / maximum) * 72;
          const knownUtilization = item.utilization_percent !== null;
          const x = knownUtilization ? item.utilization_percent! : 8 + (index % 4) * 9;
          return (
            <button
              key={item.recommendation_ref}
              type="button"
              class={`${item.recommendation_ref === selectedId ? "selected " : ""}${knownUtilization ? "" : "unknown"}`}
              style={{ "--x": `${x}%`, "--y": `${y}%`, "--size": `${18 + Math.min((item.monthly_savings ?? 0) / maximum * 22, 22)}px` }}
              onClick={() => onSelect(item.recommendation_ref)}
              aria-label={`${item.problem}, ${formatCurrency(item.monthly_savings, item.currency ?? "")}, ${knownUtilization ? formatNullablePercent(item.utilization_percent! / 100) : t("costGovernance.resource.utilizationUnavailable")}`}
            ><span>{item.resource_ref ?? item.resource_type}</span></button>
          );
        })}
      </div>
      <div class="cost-scatter-x"><span>{t("costGovernance.resource.utilizationAxis")}</span></div>
    </div>
  );
}

function DecisionStrip({ count }: { readonly count: number }) {
  const items = [
    ["all", count, false],
    ["downsize", 0, true],
    ["keep", 0, true],
    ["upsize", 0, true],
    ["schedule", 0, true],
    ["retire", 0, true],
    ["review", count, false],
  ] as const;
  return (
    <div class="cost-decision-strip" aria-label={t("costGovernance.resource.decisionClasses")}>
      {items.map(([key, value, disabled], index) => (
        <button type="button" class={index === 0 ? "active" : ""} disabled={disabled} key={key}>
          <span>{t(`costGovernance.resource.decisions.${key}`)}</span><strong>{value}</strong>
        </button>
      ))}
    </div>
  );
}

function OpportunityBars({
  recommendations,
}: {
  readonly recommendations: readonly CostGovernanceRecommendation[];
}) {
  const known = recommendations.filter(
    (item): item is CostGovernanceRecommendation & { readonly monthly_savings: number } =>
      item.monthly_savings !== null,
  );
  if (known.length === 0) {
    return <UnavailablePanel title={t("costGovernance.cases.effectsUnavailableTitle")} body={t("costGovernance.cases.effectsUnavailableBody")} />;
  }
  const maximum = Math.max(...known.map((item) => item.monthly_savings), 1);
  return (
    <div class="cost-opportunity-bars">{known.slice(0, 4).map((item) => (
      <div key={item.recommendation_ref}><span>{item.problem}</span><i><b style={{ width: `${item.monthly_savings / maximum * 100}%` }} /></i><strong>{formatCurrency(item.monthly_savings, item.currency ?? "")}</strong></div>
    ))}</div>
  );
}

function DecisionFunnel({
  summary,
  cases,
  recommendations,
}: {
  readonly summary: CostGovernanceSummary;
  readonly cases: readonly CostGovernanceRow[];
  readonly recommendations: readonly CostGovernanceRecommendation[];
}) {
  return (
    <ol class="cost-decision-funnel">
      <li style={{ "--width": "100%", "--tone": "9%" }}><span>{t("costGovernance.cases.observations")}</span><strong>{summary.sourceRecordCount}</strong><small>{t("costGovernance.cases.retainedEvidence")}</small></li>
      <li style={{ "--width": "82%", "--tone": "12%" }}><span>{t("costGovernance.cases.candidates")}</span><strong>{recommendations.length}</strong><small>{t("costGovernance.cases.advisorCandidates")}</small></li>
      <li class={cases.length ? "" : "unavailable"} style={{ "--width": "64%", "--tone": "6%" }}><span>{t("costGovernance.cases.decisionCases")}</span><strong>{cases.length || "-"}</strong><small>{cases.length ? t("costGovernance.cases.projectedCases") : t("costGovernance.cases.noCases")}</small></li>
      <li class="unavailable" style={{ "--width": "48%", "--tone": "6%" }}><span>{t("costGovernance.cases.pendingApproval")}</span><strong>-</strong><small>{t("costGovernance.cases.approvalUnavailable")}</small></li>
      <li class="unavailable" style={{ "--width": "36%", "--tone": "6%" }}><span>{t("costGovernance.outcomes.state")}</span><strong>-</strong><small>{t("costGovernance.outcomes.noSettlement")}</small></li>
    </ol>
  );
}

function CaseRows({ rows }: { readonly rows: readonly CostGovernanceRow[] }) {
  return (
    <div class="cost-case-rows">{rows.map((row) => (
      <div key={row.id}>
        <span class="cost-status review">{t("costGovernance.resource.reviewRequired")}</span>
        <strong>{row.label}</strong>
        <span>{row.status}</span>
        <b>{formatCurrency(row.amount, row.currency, row.amountLabel)}</b>
        <small>{row.observedAt ? new Date(row.observedAt).toLocaleString(costLocale()) : "-"}</small>
      </div>
    ))}</div>
  );
}

function CandidateRows({
  recommendations,
}: {
  readonly recommendations: readonly CostGovernanceRecommendation[];
}) {
  return (
    <div class="cost-case-rows">{recommendations.slice(0, 12).map((item) => (
      <div key={item.recommendation_ref}>
        <span class="cost-status review">{t("costGovernance.resource.candidateOnly")}</span>
        <strong>{item.resource_ref ?? t("costGovernance.resource.subscriptionScope")}</strong>
        <span>{item.problem}</span>
        <b>{formatCurrency(item.monthly_savings, item.currency ?? "")}</b>
        <small>{t("costGovernance.cases.notDecisionCase")}</small>
      </div>
    ))}</div>
  );
}

function UnavailableWaterfall() {
  return (
    <div class="cost-waterfall unavailable" role="img" aria-label={t("costGovernance.outcomes.waterfallUnavailable")}>
      {["projected", "deduplicated", "protected", "pending", "unrealized", "verified"].map((key) => (
        <div key={key}><strong>-</strong><i /><span>{t(`costGovernance.outcomes.waterfall.${key}`)}</span></div>
      ))}
    </div>
  );
}

function UnavailableUnitChart() {
  return (
    <div class="cost-unit-chart unavailable" role="img" aria-label={t("costGovernance.outcomes.unitUnavailable")}>
      <div aria-hidden="true" />
      <strong>{t("costGovernance.outcomes.unitUnavailable")}</strong>
      <small>{t("costGovernance.outcomes.unitUnavailableBody")}</small>
    </div>
  );
}

function SettlementGrid({ rows }: { readonly rows: readonly CostGovernanceRow[] }) {
  return (
    <div class="cost-settlement-grid">{rows.map((row) => (
      <div key={row.id}>
        <span>{row.status}</span>
        <strong>{row.label}</strong>
        <small>{row.observedAt ? new Date(row.observedAt).toLocaleString(costLocale()) : "-"}</small>
      </div>
    ))}</div>
  );
}

function CardHeader({
  eyebrow,
  title,
  description,
  value,
  valueLabel,
  action,
}: {
  readonly eyebrow: string;
  readonly title: string;
  readonly description: string;
  readonly value?: string;
  readonly valueLabel?: string;
  readonly action?: ComponentChildren;
}) {
  return (
    <header class="cost-card-header">
      <div><span>{eyebrow}</span><h2>{title}</h2><p>{description}</p></div>
      {action ?? (value ? <div class="cost-chart-value"><strong>{value}</strong><span>{valueLabel}</span></div> : null)}
    </header>
  );
}

function CardFooter({ projection }: { readonly projection: CostGovernanceProjection }) {
  return (
    <footer class="cost-card-footer"><span>{t("costGovernance.evidence.source")}: {projection.source_authority}</span><strong>{projection.complete ? t("costGovernance.summary.complete") : t("costGovernance.summary.incomplete")}</strong></footer>
  );
}

function CardFooterText({ label, value }: { readonly label: string; readonly value: string }) {
  return <footer class="cost-card-footer"><span>{label}</span><strong>{value}</strong></footer>;
}

function Metric({
  label,
  value,
  hint,
  primary = false,
  saving = false,
}: {
  readonly label: string;
  readonly value: string;
  readonly hint: string;
  readonly primary?: boolean;
  readonly saving?: boolean;
}) {
  return <div class={`${primary ? "primary " : ""}${saving ? "saving" : ""}`}><span>{label}</span><strong>{value}</strong><small>{hint}</small></div>;
}

function UnavailablePanel({ title, body }: { readonly title: string; readonly body: string }) {
  return <div class="cost-unavailable-panel"><span aria-hidden="true">-</span><div><strong>{title}</strong><p>{body}</p></div></div>;
}
