import type { ComponentChildren } from "preact";
import { useMemo, useState } from "preact/hooks";
import type {
  CostGovernanceAnalytics,
  CostGovernanceProjection,
  CostResourceCandidate,
  CostGovernanceTrendPoint,
} from "../api-cost-governance";
import { routeHref } from "../router";
import {
  costLocale,
  formatCostAmount,
  formatCurrency,
  formatKnownTotal,
  formatNullablePercent,
  formatSignedPercent,
  totalHint,
} from "./cost-governance-format";
import {
  CostEvidenceSummary,
  readinessUnavailableText,
} from "./cost-governance-evidence";
import {
  canPlotResourceCandidates,
  costDecisionCases,
  costReadiness,
  costShare,
  costSettlementOutcomes,
  incompleteSettlementLineageCount,
  resourceEfficiencyView,
  summarizeCostGovernance,
  summarizeSettlements,
  type CostGovernanceRow,
  type CostGovernanceSummary,
} from "./cost-governance.view-model";
import {
  CaseReadiness,
  DecisionCaseRows,
  DecisionFunnel,
  SettlementGrid,
  SettlementStatus,
  UnavailableUnitChart,
} from "./cost-governance-lifecycle-widgets";
import {
  ResourceCandidateInspector,
  ResourceCandidateTable,
  ServiceSummaryTable,
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
      <CostEvidenceSummary projection={projection} summary={summary} />
      {projection.surface === "overview" ? (
        <Overview projection={projection} summary={summary} analytics={projection.analytics ?? null} />
      ) : projection.surface === "resource-efficiency" ? (
        <ResourceEfficiency projection={projection} summary={summary} />
      ) : projection.surface === "optimization-cases" ? (
        <OptimizationCases projection={projection} summary={summary} />
      ) : (
        <Outcomes projection={projection} />
      )}
    </section>
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
          <a class="cost-text-action" href={routeHref("cost-governance", { segments: ["resource-efficiency"] })}>{t("costGovernance.overview.openTrendDetail")} <span aria-hidden="true">{"->"}</span></a>
        </article>

        <article class="cost-visual-card cost-spend-flow-card">
          <CardHeader
            eyebrow={t("costGovernance.overview.flowEyebrow")}
            title={t("costGovernance.overview.flowTitle")}
            description={t("costGovernance.overview.flowDescription")}
            value={formatKnownTotal(summary)}
            valueLabel={t("costGovernance.metrics.observedCost")}
          />
          <SpendFlow
            summary={summary}
            disclosure={projection.evidence?.disclosure ?? projection.disclosure}
          />
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
          <a class="cost-text-action" href={routeHref("cost-governance", { segments: ["optimization-cases"] })}>{t("costGovernance.overview.openDriversDetail")} <span aria-hidden="true">{"->"}</span></a>
        </article>
        <AttentionPanel projection={projection} summary={summary} />
      </div>
    </>
  );
}

function ResourceEfficiency({
  projection,
  summary,
}: {
  readonly projection: CostGovernanceProjection;
  readonly summary: CostGovernanceSummary;
}) {
  const view = resourceEfficiencyView(projection);
  const [query, setQuery] = useState("");
  const [selectedId, setSelectedId] = useState(
    view.candidates[0]?.recommendation_ref ?? "",
  );
  const filteredServices = useMemo(() => {
    const normalized = query.trim().toLocaleLowerCase(costLocale());
    return normalized
      ? view.serviceRows.filter((row) =>
        `${row.label} ${row.service}`.toLocaleLowerCase(costLocale()).includes(normalized)
      )
      : view.serviceRows;
  }, [query, view.serviceRows]);
  const filteredCandidates = useMemo(() => {
    const normalized = query.trim().toLocaleLowerCase(costLocale());
    return normalized
      ? view.candidates.filter((item) =>
        `${item.resource} ${item.resource_type} ${item.current_configuration} ${item.proposed_configuration}`
          .toLocaleLowerCase(costLocale())
          .includes(normalized)
      )
      : view.candidates;
  }, [query, view.candidates]);
  const selectedCandidate = filteredCandidates.find(
    (item) => item.recommendation_ref === selectedId,
  ) ?? filteredCandidates[0] ?? null;
  const candidateSavings = summarizeCandidateSavings(view.candidates);
  const canPlotCandidates = canPlotResourceCandidates(view.candidates);
  const candidateReadiness = costReadiness(projection, "resource-candidates");
  const observationReadiness = costReadiness(projection, "observations");

  if (view.mode === "service_summary") {
    return (
      <>
        <ResourceModeNotice
          mode="service_summary"
          state={observationReadiness?.state ?? (projection.complete ? "complete" : "partial")}
          reason={readinessUnavailableText(projection, "resource-candidates")}
        />
        <div class="cost-kpi-grid">
          <Metric
            label={t("costGovernance.resource.runRate")}
            value={formatKnownTotal(summary)}
            hint={totalHint(summary)}
          />
          <Metric
            label={t("costGovernance.metrics.services")}
            value={view.serviceRows.length.toLocaleString(costLocale())}
            hint={t("costGovernance.resource.serviceSummaryMode")}
          />
          <Metric
            label={t("costGovernance.metrics.sourceRecords")}
            value={summary.sourceRecordCount.toLocaleString(costLocale())}
            hint={t("costGovernance.metrics.retainedObservations")}
          />
          <Metric
            label={t("costGovernance.resource.resourceCandidates")}
            value={candidateReadiness?.record_count
              ? candidateReadiness.record_count.toLocaleString(costLocale())
              : "-"}
            hint={readinessUnavailableText(projection, "resource-candidates")}
          />
        </div>
        <section class="cost-resource-region">
          <header class="cost-section-head">
            <div>
              <h2>{t("costGovernance.resource.serviceTableTitle")}</h2>
              <p>{t("costGovernance.resource.serviceTableDescription")}</p>
            </div>
            <label class="cost-search">
              <span class="sr-only">{t("costGovernance.resource.searchService")}</span>
              <input
                type="search"
                value={query}
                placeholder={t("costGovernance.resource.searchService")}
                onInput={(event) => setQuery(event.currentTarget.value)}
              />
            </label>
          </header>
          <ServiceSummaryTable rows={filteredServices} projection={projection} />
          <footer class="cost-table-foot">
            <span>{t("costGovernance.resource.visibleServices", {
              count: filteredServices.length,
              total: view.serviceRows.length,
            })}</span>
          </footer>
        </section>
      </>
    );
  }

  return (
    <>
      <ResourceModeNotice
        mode="resource_candidate"
        state={candidateReadiness?.state ?? (view.candidates.length ? "complete" : "unavailable")}
        reason={candidateReadiness?.reason
          ? readinessUnavailableText(projection, "resource-candidates")
          : null}
      />
      <div class="cost-kpi-grid">
        <Metric label={t("costGovernance.resource.resourceCandidates")} value={String(view.candidates.length)} hint={t("costGovernance.resource.candidateCount", { count: view.candidates.length })} />
        <Metric label={t("costGovernance.resource.opportunity")} value={candidateSavings.total === null ? "-" : formatCurrency(candidateSavings.total, candidateSavings.currency)} hint={candidateSavings.total === null ? t("costGovernance.resource.opportunityUnavailable") : t("costGovernance.resource.candidateOnly")} />
        <Metric label={t("costGovernance.resource.utilizationCoverage")} value={String(view.candidates.length)} hint={t("costGovernance.resource.candidateMetrics")} />
        <Metric label={t("costGovernance.metrics.verifiedSavings")} value="-" hint={t("costGovernance.metrics.savingsUnavailable")} />
      </div>
      <article class="cost-visual-card cost-efficiency-map">
        <CardHeader
          eyebrow={t("costGovernance.resource.mapEyebrow")}
          title={t("costGovernance.resource.recommendationMapTitle")}
          description={t("costGovernance.resource.recommendationMapDescription")}
          value={String(view.candidates.length)}
          valueLabel={t("costGovernance.resource.candidateRecommendations")}
        />
        {canPlotCandidates ? (
          <CandidateMap
            candidates={view.candidates}
            onSelect={setSelectedId}
            selectedId={selectedCandidate?.recommendation_ref ?? ""}
          />
        ) : (
          <UnavailablePanel
            title={view.candidates.length
              ? t("costGovernance.resource.mapUnavailableTitle")
              : t("costGovernance.resource.candidatesUnavailableTitle")}
            body={view.candidates.length
              ? t("costGovernance.resource.mapUnavailableBody")
              : readinessUnavailableText(projection, "resource-candidates")}
          />
        )}
        <a class="cost-text-action" href="#cost-resource-table">{t("costGovernance.resource.openMapDetail")} <span aria-hidden="true">{"->"}</span></a>
      </article>
      <div class="cost-resource-workspace">
        <section class="cost-resource-region" id="cost-resource-table">
          <header class="cost-section-head">
            <div>
              <h2>{t("costGovernance.resource.candidateTableTitle")}</h2>
              <p>{t("costGovernance.resource.candidateTableDescription")}</p>
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
          <ResourceCandidateTable
            candidates={filteredCandidates}
            selectedId={selectedCandidate?.recommendation_ref ?? ""}
            onSelect={setSelectedId}
          />
          <footer class="cost-table-foot">
            <span>{t("costGovernance.resource.visibleCandidates", {
              count: filteredCandidates.length,
              total: view.candidates.length,
            })}</span>
          </footer>
        </section>
        {selectedCandidate
          ? <ResourceCandidateInspector candidate={selectedCandidate} />
          : null}
      </div>
    </>
  );
}

function OptimizationCases({
  projection,
  summary,
}: {
  readonly projection: CostGovernanceProjection;
  readonly summary: CostGovernanceSummary;
}) {
  const cases = costDecisionCases(projection);
  const readiness = costReadiness(projection, "decision-cases");
  const observationCount = costReadiness(projection, "observations")?.record_count
    ?? summary.sourceRecordCount;
  return (
    <>
      <div class="cost-kpi-grid">
        <Metric label={t("costGovernance.cases.openCases")} value={cases.length ? String(cases.length) : "-"} hint={cases.length ? t("costGovernance.cases.ownedCases") : readinessUnavailableText(projection, "decision-cases")} />
        <Metric label={t("costGovernance.cases.heldCases")} value={cases.length ? String(cases.filter((item) => item.verdict === "hold").length) : "-"} hint={t("costGovernance.cases.observationOnly")} />
        <Metric label={t("costGovernance.cases.options")} value={cases.length ? String(cases.reduce((count, item) => count + item.option_ids.length, 0)) : "-"} hint={t("costGovernance.cases.ownedOptions")} />
        <Metric label={t("costGovernance.cases.observations")} value={observationCount ? observationCount.toLocaleString(costLocale()) : "-"} hint={t("costGovernance.cases.retainedEvidence")} />
      </div>
      <div class="cost-case-grid">
        <article class="cost-visual-card">
          <CardHeader eyebrow={t("costGovernance.cases.readinessEyebrow")} title={t("costGovernance.cases.readinessTitle")} description={t("costGovernance.cases.readinessDescription")} />
          <CaseReadiness projection={projection} readiness={readiness} />
          <a class="cost-text-action" href="#cost-case-list">{t("costGovernance.cases.openFlowDetail")} <span aria-hidden="true">{"->"}</span></a>
        </article>
        <article class="cost-visual-card">
          <CardHeader eyebrow={t("costGovernance.cases.flowEyebrow")} title={t("costGovernance.cases.flowTitle")} description={t("costGovernance.cases.flowDescription")} />
          <DecisionFunnel projection={projection} observationCount={observationCount} cases={cases} />
          <a class="cost-text-action" href="#cost-case-list">{t("costGovernance.cases.openFlowDetail")} <span aria-hidden="true">{"->"}</span></a>
        </article>
      </div>
      <article class="cost-visual-card cost-case-list" id="cost-case-list">
        <CardHeader eyebrow={t("costGovernance.cases.listEyebrow")} title={t("costGovernance.cases.listTitle")} description={t("costGovernance.cases.listDescription")} />
        {cases.length > 0
          ? <DecisionCaseRows cases={cases} />
          : <UnavailablePanel
            title={t("costGovernance.cases.unavailableTitle")}
            body={readinessUnavailableText(projection, "decision-cases")}
          />}
        <a class="cost-text-action" href={routeHref("cost-governance", { segments: ["resource-efficiency"] })}>{t("costGovernance.cases.openListDetail")} <span aria-hidden="true">{"->"}</span></a>
      </article>
    </>
  );
}

function Outcomes({
  projection,
}: {
  readonly projection: CostGovernanceProjection;
}) {
  const outcomes = costSettlementOutcomes(projection);
  const incompleteLineageCount = incompleteSettlementLineageCount(projection);
  const unavailableReason = incompleteLineageCount
    ? t("costGovernance.outcomes.actionLineageUnavailable", {
      count: incompleteLineageCount,
    })
    : readinessUnavailableText(projection, "settlements");
  const settlements = summarizeSettlements(outcomes);
  const readiness = costReadiness(projection, "settlements");
  const affectedServiceFailures = outcomes.reduce(
    (count, outcome) => count + outcome.effects.filter(
      (effect) => effect.kind === "service" && effect.status === "failed",
    ).length,
    0,
  );
  return (
    <>
      <div class="cost-kpi-grid">
        <Metric label={t("costGovernance.outcomes.verifiedSavings")} value={settlements.verifiedSavings === null ? "-" : formatCurrency(settlements.verifiedSavings, settlements.currency)} hint={settlements.verifiedSavings === null ? unavailableReason : t("costGovernance.outcomes.independentlySettled")} />
        <Metric label={t("costGovernance.outcomes.verifiedOutcomes")} value={outcomes.length ? String(settlements.verifiedCount) : "-"} hint={t("costGovernance.outcomes.ownedOutcomes")} />
        <Metric label={t("costGovernance.outcomes.sloRegression")} value={outcomes.length ? String(affectedServiceFailures) : "-"} hint={outcomes.length ? t("costGovernance.outcomes.failedServiceEffects") : t("costGovernance.outcomes.effectUnavailable")} />
        <Metric label={t("costGovernance.outcomes.unresolved")} value={outcomes.length ? String(settlements.pendingCount + settlements.censoredCount + settlements.unscorableCount + settlements.rollbackCount) : "-"} hint={t("costGovernance.outcomes.unresolvedHint")} />
      </div>
      <div class="cost-outcome-grid">
        <article class="cost-visual-card">
          <CardHeader eyebrow={t("costGovernance.outcomes.statusEyebrow")} title={t("costGovernance.outcomes.statusTitle")} description={t("costGovernance.outcomes.statusDescription")} />
          {outcomes.length
            ? <SettlementStatus summary={settlements} />
            : <UnavailablePanel
              title={t("costGovernance.outcomes.unavailableTitle")}
              body={unavailableReason}
            />}
          <a class="cost-text-action" href="#cost-effect-list">{t("costGovernance.outcomes.openWaterfallDetail")} <span aria-hidden="true">{"->"}</span></a>
        </article>
        <article class="cost-visual-card">
          <CardHeader eyebrow={t("costGovernance.outcomes.unitEyebrow")} title={t("costGovernance.outcomes.unitTitle")} description={t("costGovernance.outcomes.unitDescription")} value="-" valueLabel={t("costGovernance.outcomes.unitUnavailable")} />
          <UnavailableUnitChart />
          <a class="cost-text-action" href="#cost-effect-list">{t("costGovernance.outcomes.openUnitDetail")} <span aria-hidden="true">{"->"}</span></a>
        </article>
      </div>
      <article class="cost-visual-card" id="cost-effect-list">
        <CardHeader eyebrow={t("costGovernance.outcomes.effectEyebrow")} title={t("costGovernance.outcomes.effectTitle")} description={t("costGovernance.outcomes.effectDescription")} />
        {incompleteLineageCount ? (
          <p class="cost-inline-warning">{t(
            "costGovernance.outcomes.actionLineageUnavailable",
            { count: incompleteLineageCount },
          )}</p>
        ) : null}
        {outcomes.length > 0
          ? <SettlementGrid outcomes={outcomes} />
          : <UnavailablePanel
            title={t("costGovernance.outcomes.unavailableTitle")}
            body={unavailableReason}
          />}
        <a class="cost-text-action" href={routeHref("cost-governance", { segments: ["optimization-cases"] })}>{t("costGovernance.outcomes.openEffectDetail")} <span aria-hidden="true">{"->"}</span></a>
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

function SpendFlow({
  summary,
  disclosure,
}: {
  readonly summary: CostGovernanceSummary;
  readonly disclosure: CostGovernanceProjection["disclosure"];
}) {
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
            <strong>{formatCostAmount(row, disclosure)}</strong>
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

function CandidateMap({
  candidates,
  onSelect,
  selectedId,
}: {
  readonly candidates: readonly CostResourceCandidate[];
  readonly onSelect: (id: string) => void;
  readonly selectedId: string;
}) {
  const maximum = Math.max(
    ...candidates.map((item) => item.projected_monthly_savings ?? 0),
    1,
  );
  return (
    <div class="cost-scatter-shell">
      <div class="cost-scatter-y">
        <span>{formatCurrency(maximum, candidates[0]?.currency ?? "")}</span>
        <span>{formatCurrency(maximum / 2, candidates[0]?.currency ?? "")}</span>
        <span>{formatCurrency(0, candidates[0]?.currency ?? "")}</span>
      </div>
      <div class="cost-scatter recommendations">
        {candidates.slice(0, 12).map((item) => {
          const y = 88 - ((item.projected_monthly_savings ?? 0) / maximum) * 72;
          const x = 10 + (Math.max(0, Math.min(100, item.utilization_percent)) * .8);
          return (
            <button
              key={item.recommendation_ref}
              type="button"
              class={item.recommendation_ref === selectedId ? "selected" : ""}
              style={{ "--x": `${x}%`, "--y": `${y}%`, "--size": `${18 + Math.min((item.projected_monthly_savings ?? 0) / maximum * 22, 22)}px` }}
              onClick={() => onSelect(item.recommendation_ref)}
              aria-label={`${item.resource}, ${formatCurrency(item.projected_monthly_savings, item.currency ?? "")}, ${formatNullablePercent(item.utilization_percent / 100)}`}
            ><span>{item.resource}</span></button>
          );
        })}
      </div>
      <div class="cost-scatter-x"><span>{t("costGovernance.resource.utilizationAxis")}</span></div>
    </div>
  );
}

function ResourceModeNotice({
  mode,
  state,
  reason,
}: {
  readonly mode: "service_summary" | "resource_candidate";
  readonly state: "complete" | "partial" | "unavailable";
  readonly reason: string | null;
}) {
  return (
    <section class="cost-resource-mode" aria-label={t("costGovernance.resource.modeLabel")}>
      <div>
        <span>{t("costGovernance.resource.modeLabel")}</span>
        <h2>{t(`costGovernance.resource.modes.${mode}.title`)}</h2>
        <p>{t(`costGovernance.resource.modes.${mode}.description`)}</p>
      </div>
      <span class={`cost-evidence ${state === "complete" ? "ready" : "limited"}`}>
        {t(`costGovernance.evidence.states.${state}`)}
      </span>
      {reason ? <small>{reason}</small> : null}
    </section>
  );
}

function summarizeCandidateSavings(
  candidates: readonly CostResourceCandidate[],
): { readonly total: number | null; readonly currency: string } {
  const currencies = new Set(
    candidates.map((item) => item.currency).filter((value): value is string => Boolean(value)),
  );
  if (
    candidates.length === 0
    || currencies.size !== 1
    || candidates.some((item) =>
      item.projected_monthly_savings === null || item.currency === null
    )
  ) {
    return { total: null, currency: "" };
  }
  return {
    total: candidates.reduce(
      (total, item) => total + (item.projected_monthly_savings ?? 0),
      0,
    ),
    currency: candidates[0]?.currency ?? "",
  };
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
