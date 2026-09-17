import type {
  CostGovernanceProjection,
  CostResourceCandidate,
} from "../api-cost-governance";
import {
  costLocale,
  formatCostAmount,
  formatCurrency,
  formatNullablePercent,
} from "./cost-governance-format";
import {
  costReadiness,
  type CostGovernanceRow,
} from "./cost-governance.view-model";
import { t } from "./i18n/cost-governance";

export function ServiceSummaryTable({
  rows,
  projection,
}: {
  readonly rows: readonly CostGovernanceRow[];
  readonly projection: CostGovernanceProjection;
}) {
  if (rows.length === 0) {
    return <div class="cost-empty">{t("costGovernance.resource.noServiceSummaries")}</div>;
  }
  const observationReadiness = costReadiness(projection, "observations");
  const latestSourceAt = projection.evidence?.latest_source_at
    ?? projection.analytics?.observed_at
    ?? null;
  const disclosure = projection.evidence?.disclosure ?? projection.disclosure;
  return (
    <div class="cost-resource-table-wrap">
      <table class="cost-resource-table cost-service-summary-table">
        <thead><tr>
          <th>{t("costGovernance.columns.service")}</th>
          <th>{t("costGovernance.resource.disclosedCost")}</th>
          <th>{t("costGovernance.resource.observations")}</th>
          <th>{t("costGovernance.evidence.completeness")}</th>
          <th>{t("costGovernance.resource.latestEvidence")}</th>
        </tr></thead>
        <tbody>{rows.map((row) => (
          <tr key={row.id}>
            <th scope="row"><strong>{row.label}</strong></th>
            <td class="number">
              <strong>{formatCostAmount(row, disclosure)}</strong>
              {row.positiveBelowRoundingIncrement ? (
                <small>{t("costGovernance.metrics.belowRoundingExplanation")}</small>
              ) : null}
            </td>
            <td class="number">{row.recordCount.toLocaleString(costLocale())}</td>
            <td>
              <span class={`cost-evidence ${
                observationReadiness?.state === "complete" || (
                  observationReadiness === null && projection.complete
                )
                  ? "ready"
                  : "limited"
              }`}>
                {observationReadiness
                  ? t(`costGovernance.evidence.states.${observationReadiness.state}`)
                  : projection.complete
                  ? t("costGovernance.summary.complete")
                  : t("costGovernance.summary.incomplete")}
              </span>
            </td>
            <td>{formatTimestamp(latestSourceAt)}</td>
          </tr>
        ))}</tbody>
      </table>
    </div>
  );
}

export function ResourceCandidateTable({
  candidates,
  selectedId,
  onSelect,
}: {
  readonly candidates: readonly CostResourceCandidate[];
  readonly selectedId: string;
  readonly onSelect: (id: string) => void;
}) {
  if (candidates.length === 0) {
    return <div class="cost-empty">{t("costGovernance.resource.noCandidates")}</div>;
  }
  return (
    <div class="cost-resource-table-wrap">
      <table class="cost-resource-table cost-candidate-table">
        <thead><tr>
          <th>{t("costGovernance.columns.identity")}</th>
          <th>{t("costGovernance.resource.currentConfiguration")}</th>
          <th>{t("costGovernance.resource.proposedConfiguration")}</th>
          <th>{t("costGovernance.resource.utilization")}</th>
          <th>{t("costGovernance.resource.projectedChange")}</th>
          <th>{t("costGovernance.columns.evidence")}</th>
        </tr></thead>
        <tbody>{candidates.map((candidate) => (
          <tr
            class={candidate.recommendation_ref === selectedId ? "selected" : ""}
            key={candidate.recommendation_ref}
          >
            <td>
              <button type="button" onClick={() => onSelect(candidate.recommendation_ref)}>
                <strong>{candidate.resource}</strong>
                <small>{candidate.resource_type}</small>
              </button>
            </td>
            <td><strong>{candidate.current_configuration}</strong></td>
            <td><strong>{candidate.proposed_configuration}</strong></td>
            <td>
              <strong>{formatNullablePercent(candidate.utilization_percent / 100)}</strong>
              <small>{candidate.utilization_metric}</small>
            </td>
            <td class="number">
              {formatCurrency(
                candidate.projected_monthly_savings,
                candidate.currency ?? "",
              )}
              <small>{t("costGovernance.resource.monthlyCandidateEstimate")}</small>
            </td>
            <td>
              <span class="cost-evidence ready">{t("costGovernance.resource.candidateEvidence")}</span>
            </td>
          </tr>
        ))}</tbody>
      </table>
    </div>
  );
}

export function ResourceCandidateInspector({
  candidate,
}: {
  readonly candidate: CostResourceCandidate;
}) {
  return (
    <aside
      class="cost-inspector"
      aria-live="polite"
      aria-label={t("costGovernance.resource.inspectorLabel")}
    >
      <header>
        <div>
          <span>{t("costGovernance.resource.selectedCandidate")}</span>
          <h2>{candidate.resource}</h2>
          <p>{candidate.resource_type}</p>
        </div>
        <span class="cost-case-mode">{t("costGovernance.resource.candidateOnly")}</span>
      </header>
      <section class="cost-recommendation">
        <span>{t("costGovernance.resource.providerRecommendation")}</span>
        <div>
          <strong>{candidate.current_configuration}</strong>
          <span aria-hidden="true">-&gt;</span>
          <strong>{candidate.proposed_configuration}</strong>
        </div>
        <p>{t("costGovernance.resource.candidateAuthorityBoundary")}</p>
      </section>
      <section class="cost-candidate-evidence">
        <h3>{t("costGovernance.resource.candidateEvidenceTitle")}</h3>
        <dl>
          <div>
            <dt>{t("costGovernance.resource.utilization")}</dt>
            <dd>{formatNullablePercent(candidate.utilization_percent / 100)}</dd>
          </div>
          <div>
            <dt>{t("costGovernance.resource.utilizationMetric")}</dt>
            <dd>{candidate.utilization_metric}</dd>
          </div>
          <div>
            <dt>{t("costGovernance.resource.projectedChange")}</dt>
            <dd>{formatCurrency(
              candidate.projected_monthly_savings,
              candidate.currency ?? "",
            )}</dd>
          </div>
          <div>
            <dt>{t("costGovernance.evidence.source")}</dt>
            <dd>{candidate.source_authority}</dd>
          </div>
          <div>
            <dt>{t("costGovernance.columns.observed")}</dt>
            <dd>{formatTimestamp(candidate.observed_at)}</dd>
          </div>
        </dl>
      </section>
      <footer><span>{t("costGovernance.resource.noChangesApplied")}</span></footer>
    </aside>
  );
}

function formatTimestamp(value: string | null): string {
  if (!value) return t("costGovernance.evidence.notReported");
  const instant = new Date(value);
  return Number.isNaN(instant.valueOf())
    ? t("costGovernance.evidence.notReported")
    : new Intl.DateTimeFormat(costLocale(), {
      year: "numeric",
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      timeZoneName: "short",
    }).format(instant);
}
