import type {
  CostDecisionCase,
  CostGovernanceProjection,
  CostSurfaceReadiness,
} from "../api-cost-governance";
import { costLocale, formatCurrency } from "./cost-governance-format";
import { readinessUnavailableText } from "./cost-governance-evidence";
import {
  costReadiness,
  settlementState,
  type CompleteCostSettlementOutcome,
  type CostSettlementSummary,
} from "./cost-governance.view-model";
import { t } from "./i18n/cost-governance";

export function CaseReadiness({
  projection,
  readiness,
}: {
  readonly projection: CostGovernanceProjection;
  readonly readiness: CostSurfaceReadiness | null;
}) {
  const state = readiness?.state ?? "unavailable";
  return (
    <div class="cost-case-readiness">
      <span class={`cost-evidence ${state === "complete" ? "ready" : "limited"}`}>
        {t(`costGovernance.evidence.states.${state}`)}
      </span>
      <strong>{readiness
        ? t("costGovernance.evidence.readinessCount", { count: readiness.record_count })
        : t("costGovernance.evidence.readinessNotReported")}</strong>
      <p>{readiness?.state === "complete"
        ? t("costGovernance.cases.readyOwnedRecords")
        : readinessUnavailableText(projection, "decision-cases")}</p>
      {readiness?.reason ? <code>{readiness.reason}</code> : null}
    </div>
  );
}

export function DecisionFunnel({
  projection,
  observationCount,
  cases,
}: {
  readonly projection: CostGovernanceProjection;
  readonly observationCount: number;
  readonly cases: readonly CostDecisionCase[];
}) {
  const candidateCount = costReadiness(projection, "resource-candidates")?.record_count ?? 0;
  const settlementCount = costReadiness(projection, "settlements")?.record_count ?? 0;
  return (
    <ol class="cost-decision-funnel">
      <li style={{ "--width": "100%", "--tone": "9%" }}>
        <span>{t("costGovernance.cases.observations")}</span>
        <strong>{observationCount}</strong>
        <small>{t("costGovernance.cases.retainedEvidence")}</small>
      </li>
      <li class={candidateCount ? "" : "unavailable"} style={{ "--width": "82%", "--tone": "12%" }}>
        <span>{t("costGovernance.cases.candidates")}</span>
        <strong>{candidateCount || "-"}</strong>
        <small>{readinessUnavailableText(projection, "resource-candidates")}</small>
      </li>
      <li class={cases.length ? "" : "unavailable"} style={{ "--width": "64%", "--tone": "6%" }}>
        <span>{t("costGovernance.cases.decisionCases")}</span>
        <strong>{cases.length || "-"}</strong>
        <small>{cases.length
          ? t("costGovernance.cases.projectedCases")
          : t("costGovernance.cases.noCases")}</small>
      </li>
      <li class={settlementCount ? "" : "unavailable"} style={{ "--width": "46%", "--tone": "6%" }}>
        <span>{t("costGovernance.outcomes.state")}</span>
        <strong>{settlementCount || "-"}</strong>
        <small>{readinessUnavailableText(projection, "settlements")}</small>
      </li>
    </ol>
  );
}

export function DecisionCaseRows({
  cases,
}: {
  readonly cases: readonly CostDecisionCase[];
}) {
  return (
    <div class="cost-case-rows">{cases.map((item) => (
      <div key={`${item.case_ref}:${item.revision}`}>
        <span class="cost-status review">{t("costGovernance.cases.held")}</span>
        <strong>{t("costGovernance.cases.caseRevision", {
          case: item.case_ref,
          revision: item.revision,
        })}</strong>
        <span>{item.selected_option_id ?? t("costGovernance.cases.noSelectedOption")}</span>
        <b>{t("costGovernance.cases.optionCount", { count: item.option_ids.length })}</b>
        <small>{t("costGovernance.cases.caseEvidence", {
          time: formatTimestamp(item.evidence_cutoff),
          count: item.evidence_refs.length,
          source: item.source_authority,
        })}</small>
        <small class="cost-record-reason">
          {t("costGovernance.cases.reason", { reason: item.reason })}
        </small>
        <details class="cost-record-lineage">
          <summary>{t("costGovernance.cases.showLineage")}</summary>
          <dl>
            <LineageFact
              label={t("costGovernance.cases.targets")}
              value={item.target_refs.join(", ")}
            />
            <LineageFact
              label={t("costGovernance.cases.decisionFrame")}
              value={item.decision_frame_digest}
            />
            <LineageFact
              label={t("costGovernance.cases.options")}
              value={item.option_ids.join(", ")}
            />
            <LineageFact
              label={t("costGovernance.cases.evidenceReferences")}
              value={item.evidence_refs.join(", ")}
            />
            <LineageFact
              label={t("costGovernance.cases.evidenceSources")}
              value={item.evidence_sources.join(", ")}
            />
          </dl>
        </details>
      </div>
    ))}</div>
  );
}

export function SettlementStatus({
  summary,
}: {
  readonly summary: CostSettlementSummary;
}) {
  const statuses = [
    ["verified", summary.verifiedCount],
    ["failed", summary.failedCount],
    ["censored", summary.censoredCount],
    ["unscorable", summary.unscorableCount],
    ["rollback", summary.rollbackCount],
    ["pending", summary.pendingCount],
  ] as const;
  return (
    <ul class="cost-settlement-status">
      {statuses.map(([status, count]) => (
        <li key={status}>
          <span>{t(`costGovernance.outcomes.statuses.${status}`)}</span>
          <strong>{count}</strong>
        </li>
      ))}
    </ul>
  );
}

export function UnavailableUnitChart() {
  return (
    <div
      class="cost-unit-chart unavailable"
      role="img"
      aria-label={t("costGovernance.outcomes.unitUnavailable")}
    >
      <div aria-hidden="true" />
      <strong>{t("costGovernance.outcomes.unitUnavailable")}</strong>
      <small>{t("costGovernance.outcomes.unitUnavailableBody")}</small>
    </div>
  );
}

export function SettlementGrid({
  outcomes,
}: {
  readonly outcomes: readonly CompleteCostSettlementOutcome[];
}) {
  return (
    <div class="cost-settlement-grid">{outcomes.map((outcome) => {
      const state = settlementState(outcome);
      return (
        <article key={`${outcome.case_ref}:${outcome.revision}`}>
          <span class={`is-${state}`}>{t(`costGovernance.outcomes.statuses.${state}`)}</span>
          <strong>{t("costGovernance.outcomes.caseRevision", {
            case: outcome.case_ref,
            revision: outcome.revision,
          })}</strong>
          <small>{t("costGovernance.outcomes.actionRevision", {
            action: outcome.action_ref,
            revision: outcome.action_revision,
          })}</small>
          <small>{formatTimestamp(outcome.settled_at)}</small>
          <b>{state === "verified" && outcome.verified_savings !== null && outcome.currency
            ? formatCurrency(outcome.verified_savings, outcome.currency)
            : "-"}</b>
          <ul>
            {outcome.effects.map((effect) => (
              <li key={effect.effect_id}>
                <span>{t(`costGovernance.outcomes.effectKinds.${effect.kind}`)}</span>
                <strong>{t(`costGovernance.outcomes.statuses.${effect.status}`)}</strong>
                <small>{effect.reason}</small>
                {effect.observation_digest && effect.completeness_digest ? (
                  <code>{t("costGovernance.outcomes.effectEvidence", {
                    observation: effect.observation_digest,
                    completeness: effect.completeness_digest,
                  })}</code>
                ) : null}
              </li>
            ))}
          </ul>
          {outcome.rollback_requested ? (
            <p>{outcome.recovery_observed
              ? t("costGovernance.outcomes.rollbackObserved")
              : t("costGovernance.outcomes.rollbackPending")}</p>
          ) : null}
        </article>
      );
    })}</div>
  );
}

function LineageFact({ label, value }: { readonly label: string; readonly value: string }) {
  return <div><dt>{label}</dt><dd>{value}</dd></div>;
}

function formatTimestamp(value: string): string {
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
