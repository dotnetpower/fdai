import type { AuditItem, IncidentOutcomeCohort, IncidentOutcomeMetrics, IncidentSummary } from "../types";
import { StatusPill, type PillKind } from "../components/ui";
import { routeHref } from "../router";
import { formatConsoleTimestamp } from "../time-format";
import { t } from "./i18n/evidence";
import { incidentMilestones, type IncidentMilestoneStatus } from "./incidents.milestones";
import { incidentTimelinePresentation } from "./incidents.timeline";

const OUTCOME_COHORTS: readonly IncidentOutcomeCohort[] = [
  "agent_mitigated",
  "agent_assisted",
  "human_mitigated",
  "pending",
  "integrity_excluded",
];

export function IncidentOutcomeAnalytics({ metrics }: { readonly metrics: IncidentOutcomeMetrics }) {
  return (
    <section class="incident-outcome-analytics" aria-labelledby="incident-outcome-title">
      <header>
        <div>
          <span class="incident-section-label">{t("incidents.analytics.label")}</span>
          <h2 id="incident-outcome-title">{t("incidents.analytics.title")}</h2>
        </div>
        <span>{t(metrics.truncated ? "incidents.analytics.truncated" : "incidents.analytics.complete")}</span>
      </header>
      <dl class="incident-analytics-provenance">
        <div><dt>{t("incidents.analytics.source")}</dt><dd class="mono">{metrics.source}</dd></div>
        <div><dt>{t("incidents.analytics.snapshot")}</dt><dd>{metrics.snapshot_seq}</dd></div>
        <div><dt>{t("incidents.analytics.denominator")}</dt><dd>{metrics.denominator}</dd></div>
        <div><dt>{t("incidents.analytics.window")}</dt><dd>{metrics.window_from && metrics.window_to ? `${formatConsoleTimestamp(metrics.window_from)} - ${formatConsoleTimestamp(metrics.window_to)}` : t("incidents.none")}</dd></div>
        <div><dt>{t("incidents.analytics.medianTtm")}</dt><dd>{metrics.median_time_to_mitigate_seconds === null ? t("incidents.none") : t("incidents.analytics.seconds", { count: metrics.median_time_to_mitigate_seconds })}</dd></div>
        <div><dt>{t("incidents.analytics.ttmSample")}</dt><dd>{metrics.time_to_mitigate_sample_size}</dd></div>
        <div><dt>{t("incidents.analytics.terminalRule")}</dt><dd class="mono">{metrics.terminal_rule}</dd></div>
      </dl>
      <div class="incident-cohort-grid">
        {OUTCOME_COHORTS.map((cohort) => (
          <details key={cohort} class="incident-cohort">
            <summary>
              <span>{t(`incidents.analytics.cohort.${cohort}`)}</span>
              <strong>{metrics.cohorts[cohort]}</strong>
            </summary>
            {metrics.drilldown[cohort].length > 0 ? (
              <ul>{metrics.drilldown[cohort].map((correlation) => (
                <li key={correlation}><a href={routeHref("incidents", { params: { correlation } })}>{correlation}</a></li>
              ))}</ul>
            ) : <p>{t("incidents.analytics.noDrilldown")}</p>}
            {metrics.drilldown_truncated[cohort] ? (
              <p>{t("incidents.analytics.drilldownTruncated", {
                shown: metrics.drilldown[cohort].length,
                total: metrics.cohorts[cohort],
              })}</p>
            ) : null}
          </details>
        ))}
      </div>
    </section>
  );
}

export function IncidentMilestones({ items }: { readonly items: readonly AuditItem[] }) {
  const milestones = incidentMilestones(items);
  if (milestones.length === 0) {
    return (
      <section class="incident-milestones" aria-labelledby="incident-milestones-title">
        <h3 id="incident-milestones-title">{t("incidents.milestones.title")}</h3>
        <p>{t("incidents.milestones.empty")}</p>
      </section>
    );
  }
  return (
    <section class="incident-milestones" aria-labelledby="incident-milestones-title">
      <header>
        <h3 id="incident-milestones-title">{t("incidents.milestones.title")}</h3>
        <span>{t("incidents.milestones.count", { count: milestones.length })}</span>
      </header>
      <ol>
        {milestones.map((milestone) => {
          const presentation = incidentTimelinePresentation(milestone.item);
          return (
            <li key={milestone.item.seq}>
              <div class="incident-milestone-heading">
                <StatusPill kind={milestonePill(milestone.status)} label={t(`incidents.milestones.status.${milestone.status}`)} />
                <strong>{presentation.title}</strong>
                <time dateTime={milestone.item.recorded_at}>{formatConsoleTimestamp(milestone.item.recorded_at)}</time>
              </div>
              <p>{presentation.description}</p>
              {milestone.evidenceRefs.length > 0 ? <div><b>{t("incidents.milestones.evidence")}</b> {milestone.evidenceRefs.join(", ")}</div> : null}
              {milestone.evidenceRefsTruncated ? <div>{t("incidents.milestones.moreEvidence")}</div> : null}
              {milestone.gaps.length > 0 ? <div><b>{t("incidents.milestones.gaps")}</b> {milestone.gaps.join(", ")}</div> : null}
              {milestone.gapsTruncated ? <div>{t("incidents.milestones.moreGaps")}</div> : null}
              {milestone.evaluationReceipt ? <div><b>{t("incidents.milestones.evaluation")}</b> <span class="mono">{milestone.evaluationReceipt}</span></div> : null}
              {milestone.learningCandidate ? <div><b>{t("incidents.milestones.learning")}</b> <span class="mono">{milestone.learningCandidate}</span></div> : null}
            </li>
          );
        })}
      </ol>
    </section>
  );
}

export function IncidentSourceContext({ incident }: { readonly incident: IncidentSummary }) {
  const source = incident.source;
  const plan = incident.response_plan;
  if (source === null && plan === null) return null;
  return (
    <section class="incident-source-context" aria-labelledby="incident-source-context-title">
      <h3 id="incident-source-context-title">{t("incidents.source.title")}</h3>
      {source?.description ? <p>{source.description}</p> : null}
      <dl>
        {source?.platform ? <div><dt>{t("incidents.source.platform")}</dt><dd>{source.platform}</dd></div> : null}
        {source?.incident_id ? <div><dt>{t("incidents.source.id")}</dt><dd class="mono">{source.incident_id}</dd></div> : null}
        {source?.status ? <div><dt>{t("incidents.source.status")}</dt><dd>{source.status}</dd></div> : null}
        {source?.fired_at ? <div><dt>{t("incidents.source.firedAt")}</dt><dd>{formatConsoleTimestamp(source.fired_at)}</dd></div> : null}
        {plan?.id ? <div><dt>{t("incidents.source.plan")}</dt><dd>{plan.id}</dd></div> : null}
        {plan?.revision ? <div><dt>{t("incidents.source.planRevision")}</dt><dd class="mono">{plan.revision}</dd></div> : null}
        {plan?.enabled !== null && plan?.enabled !== undefined ? <div><dt>{t("incidents.source.planState")}</dt><dd>{t(plan.enabled ? "incidents.source.enabled" : "incidents.source.disabled")}</dd></div> : null}
        {plan?.historical_match_count !== null && plan?.historical_match_count !== undefined ? <div><dt>{t("incidents.source.historicalMatches")}</dt><dd>{plan.historical_match_count}</dd></div> : null}
        {plan?.reinvestigation_cooldown_seconds !== null && plan?.reinvestigation_cooldown_seconds !== undefined ? <div><dt>{t("incidents.source.cooldown")}</dt><dd>{t("incidents.source.seconds", { count: plan.reinvestigation_cooldown_seconds })}</dd></div> : null}
        {plan?.deduplication_key ? <div><dt>{t("incidents.source.deduplicationKey")}</dt><dd class="mono">{plan.deduplication_key}</dd></div> : null}
      </dl>
      {source?.url ? <a href={source.url} target="_blank" rel="noopener noreferrer">{t("incidents.source.openExternal")}</a> : null}
    </section>
  );
}

function milestonePill(status: IncidentMilestoneStatus): PillKind {
  if (status === "resolved" || status === "success") return "success";
  if (status === "issue") return "danger";
  if (status === "initial") return "hil";
  return "info";
}
