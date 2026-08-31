import type { CostGovernanceRecommendation } from "../api-cost-governance";
import {
  costLocale,
  formatCurrency,
  formatNullablePercent,
} from "./cost-governance-format";
import {
  costShare,
  type CostGovernanceRow,
} from "./cost-governance.view-model";
import { t } from "./i18n/cost-governance";

export function ResourceTable({
  rows,
  selectedId,
  totals,
  complete,
  onSelect,
}: {
  readonly rows: readonly CostGovernanceRow[];
  readonly selectedId: string;
  readonly totals: Readonly<Record<string, number>>;
  readonly complete: boolean;
  readonly onSelect: (id: string) => void;
}) {
  if (rows.length === 0) {
    return <div class="cost-empty">{t("costGovernance.resource.noMatches")}</div>;
  }
  return (
    <div class="cost-resource-table-wrap">
      <table class="cost-resource-table">
        <thead><tr>
          <th>{t("costGovernance.columns.identity")}</th>
          <th>{t("costGovernance.resource.currentSku")}</th>
          <th>{t("costGovernance.resource.utilization")}</th>
          <th>{t("costGovernance.resource.decision")}</th>
          <th>{t("costGovernance.columns.amount")}</th>
          <th>{t("costGovernance.resource.projectedChange")}</th>
          <th>{t("costGovernance.columns.evidence")}</th>
        </tr></thead>
        <tbody>{rows.map((row) => {
          const rowComplete = row.completeness === null ? complete : row.completeness >= 1;
          return (
            <tr class={row.id === selectedId ? "selected" : ""} key={row.id}>
              <td><button type="button" onClick={() => onSelect(row.id)}><strong>{row.label}</strong><small>{row.service}</small></button></td>
              <td><strong>-</strong><small>{t("costGovernance.resource.skuUnavailable")}</small></td>
              <td><strong>-</strong><small>{t("costGovernance.resource.utilizationUnavailable")}</small></td>
              <td><span class="cost-status review">{t("costGovernance.resource.reviewRequired")}</span></td>
              <td class="number">{formatCurrency(row.amount, row.currency, row.amountLabel)}<small>{formatNullablePercent(costShare(row, totals))}</small></td>
              <td class="number">-<small>{t("costGovernance.resource.noRecommendation")}</small></td>
              <td><span class={rowComplete ? "cost-evidence ready" : "cost-evidence limited"}>{rowComplete ? t("costGovernance.summary.complete") : t("costGovernance.summary.incomplete")}</span></td>
            </tr>
          );
        })}</tbody>
      </table>
    </div>
  );
}

export function RecommendationTable({
  recommendations,
  selectedId,
  onSelect,
}: {
  readonly recommendations: readonly CostGovernanceRecommendation[];
  readonly selectedId: string;
  readonly onSelect: (id: string) => void;
}) {
  if (recommendations.length === 0) {
    return <div class="cost-empty">{t("costGovernance.resource.noMatches")}</div>;
  }
  return (
    <div class="cost-resource-table-wrap">
      <table class="cost-resource-table">
        <thead><tr>
          <th>{t("costGovernance.columns.identity")}</th>
          <th>{t("costGovernance.resource.currentSku")}</th>
          <th>{t("costGovernance.resource.utilization")}</th>
          <th>{t("costGovernance.resource.decision")}</th>
          <th>{t("costGovernance.resource.projectedChange")}</th>
          <th>{t("costGovernance.resource.impact")}</th>
          <th>{t("costGovernance.columns.evidence")}</th>
        </tr></thead>
        <tbody>{recommendations.map((item) => (
          <tr class={item.recommendation_ref === selectedId ? "selected" : ""} key={item.recommendation_ref}>
            <td><button type="button" onClick={() => onSelect(item.recommendation_ref)}><strong>{item.resource_ref ?? t("costGovernance.resource.subscriptionScope")}</strong><small>{item.resource_type}</small></button></td>
            <td><strong>{item.current_sku ?? "-"}</strong><small>{item.target_sku ? t("costGovernance.resource.targetSku", { sku: item.target_sku }) : t("costGovernance.resource.targetUnavailable")}</small></td>
            <td><strong>{item.utilization_percent === null ? "-" : formatNullablePercent(item.utilization_percent / 100)}</strong><small>{item.utilization_metric ?? t("costGovernance.resource.utilizationUnavailable")}</small></td>
            <td><span class="cost-status review">{t("costGovernance.resource.candidateOnly")}</span></td>
            <td class="number">{formatCurrency(item.monthly_savings, item.currency ?? "")}<small>{t("costGovernance.resource.monthlyAdvisorEstimate")}</small></td>
            <td>{item.impact}</td>
            <td><span class="cost-evidence ready">{t("costGovernance.resource.advisorEvidence")}</span></td>
          </tr>
        ))}</tbody>
      </table>
    </div>
  );
}

export function ResourceInspector({
  row,
  complete,
}: {
  readonly row: CostGovernanceRow | null;
  readonly complete: boolean;
}) {
  const evidenceComplete = row?.completeness === null || row?.completeness === undefined
    ? complete
    : row.completeness >= 1;
  return (
    <aside class="cost-inspector" aria-live="polite" aria-label={t("costGovernance.resource.inspectorLabel")}>
      <header><div><span>{t("costGovernance.resource.selectedEvidence")}</span><h2>{row?.label ?? "-"}</h2><p>{row?.service ?? t("costGovernance.resource.noSelection")}</p></div><span class="cost-case-mode">{t("costGovernance.resource.observationMode")}</span></header>
      <section class="cost-recommendation">
        <span>{t("costGovernance.resource.recommendedOption")}</span>
        <div><strong>-</strong><span aria-hidden="true">-&gt;</span><strong>-</strong></div>
        <p>{t("costGovernance.resource.recommendationUnavailable")}</p>
      </section>
      <section class="cost-agent-evidence">
        <h3>{t("costGovernance.resource.agentEvidence")}</h3>
        <div><span>Njord</span><p>{row ? t("costGovernance.resource.njordEvidence", { amount: formatCurrency(row.amount, row.currency, row.amountLabel) }) : "-"}</p><strong>{t("costGovernance.resource.cost")}</strong></div>
        <div><span>Freyr</span><p>{t("costGovernance.resource.freyrUnavailable")}</p><strong>{t("costGovernance.resource.capacity")}</strong></div>
        <div><span>Forseti</span><p>{t("costGovernance.resource.forsetiUnavailable")}</p><strong>{t("costGovernance.resource.judgment")}</strong></div>
      </section>
      <section class="cost-gates">
        <h3>{t("costGovernance.resource.eligibility")}</h3>
        <ul>
          <li><span>{t("costGovernance.resource.gates.mapping")}</span><strong>{t("costGovernance.resource.unknown")}</strong></li>
          <li><span>{t("costGovernance.resource.gates.slo")}</span><strong>{t("costGovernance.resource.unknown")}</strong></li>
          <li><span>{t("costGovernance.resource.gates.coverage")}</span><strong>{evidenceComplete ? t("costGovernance.summary.complete") : t("costGovernance.summary.incomplete")}</strong></li>
          <li><span>{t("costGovernance.resource.gates.rollback")}</span><strong>{t("costGovernance.resource.notEvaluated")}</strong></li>
        </ul>
      </section>
      <footer><span>{t("costGovernance.resource.noChangesApplied")}</span></footer>
    </aside>
  );
}

export function RecommendationInspector({
  recommendation,
}: {
  readonly recommendation: CostGovernanceRecommendation;
}) {
  return (
    <aside class="cost-inspector" aria-live="polite" aria-label={t("costGovernance.resource.inspectorLabel")}>
      <header>
        <div><span>{t("costGovernance.resource.selectedCandidate")}</span><h2>{recommendation.resource_ref ?? t("costGovernance.resource.subscriptionScope")}</h2><p>{recommendation.resource_type}</p></div>
        <span class="cost-case-mode">{t("costGovernance.resource.candidateOnly")}</span>
      </header>
      <section class="cost-recommendation">
        <span>{t("costGovernance.resource.providerRecommendation")}</span>
        <div><strong>{recommendation.current_sku ?? "-"}</strong><span aria-hidden="true">-&gt;</span><strong>{recommendation.target_sku ?? "-"}</strong></div>
        <p>{recommendation.solution}</p>
      </section>
      <section class="cost-agent-evidence">
        <h3>{t("costGovernance.resource.agentEvidence")}</h3>
        <div><span>Azure Advisor</span><p>{recommendation.problem}</p><strong>{recommendation.impact}</strong></div>
        <div><span>Njord</span><p>{recommendation.monthly_savings === null ? t("costGovernance.resource.savingsUnavailable") : t("costGovernance.resource.projectedMonthlySavings", { amount: formatCurrency(recommendation.monthly_savings, recommendation.currency ?? "") })}</p><strong>{t("costGovernance.resource.cost")}</strong></div>
        <div><span>Freyr</span><p>{recommendation.utilization_percent === null ? t("costGovernance.resource.freyrUnavailable") : t("costGovernance.resource.utilizationEvidence", { value: formatNullablePercent(recommendation.utilization_percent / 100) })}</p><strong>{t("costGovernance.resource.capacity")}</strong></div>
        <div><span>Forseti</span><p>{t("costGovernance.resource.forsetiUnavailable")}</p><strong>{t("costGovernance.resource.judgment")}</strong></div>
      </section>
      <section class="cost-gates">
        <h3>{t("costGovernance.resource.eligibility")}</h3>
        <ul>
          <li><span>{t("costGovernance.resource.gates.mapping")}</span><strong>{t("costGovernance.resource.unknown")}</strong></li>
          <li><span>{t("costGovernance.resource.gates.slo")}</span><strong>{t("costGovernance.resource.unknown")}</strong></li>
          <li><span>{t("costGovernance.resource.gates.coverage")}</span><strong>{t("costGovernance.resource.advisorEvidence")}</strong></li>
          <li><span>{t("costGovernance.resource.gates.rollback")}</span><strong>{t("costGovernance.resource.notEvaluated")}</strong></li>
        </ul>
      </section>
      <footer><span>{t("costGovernance.resource.noChangesApplied")}</span></footer>
    </aside>
  );
}
