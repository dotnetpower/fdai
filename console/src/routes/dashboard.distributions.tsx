import type { AutonomyPayload, DashboardKpi } from "../types";
import { t } from "../i18n";
import { routeHref } from "../router";
import { tDashboard } from "./i18n/dashboard-essential";
import { EvidenceLoading, EvidenceSummary } from "./dashboard.evidence";
import {
  auditSampleParams,
  controlGapSummary,
  controlOutcomeGroup,
  dashboardEvidenceGaps,
  distributionEvidence,
  distributionRows,
  formatShare,
  routingSampleParams,
  type DistributionRow,
  type GatesSummary,
} from "./dashboard.model";

interface Props {
  readonly kpi: DashboardKpi;
  readonly autonomy: AutonomyPayload | null;
  readonly gates: GatesSummary | null;
  readonly policyEscapes: number | null;
  readonly compact?: boolean;
  readonly optionalPending?: boolean;
}

export function RoutingControl({ kpi, compact = false }: Pick<Props, "kpi" | "compact">) {
  const sampleParams = routingSampleParams(kpi);
  const modeSampleParams = auditSampleParams(kpi);
  const routingCount = kpi.routing_sample?.row_count ?? kpi.event_count;
  const tierEvidence = distributionEvidence(kpi.by_tier, routingCount);
  const outcomeEvidence = distributionEvidence(kpi.by_outcome, routingCount);
  const tiers = tierEvidence.rows;
  const outcomes = outcomeEvidence.rows;
  const shadowCount = Math.round(kpi.event_count * kpi.shadow_share);
  const modes = distributionRows({
    shadow: shadowCount,
    enforce: Math.max(0, kpi.event_count - shadowCount),
  });
  const outcomeTotal = outcomes.reduce((sum, row) => sum + row.count, 0);
  const summary = compact && tiers.length === 0 && outcomes.length === 0;
  return (
    <section class={`overview-routing-grid${summary ? " is-summary" : ""}`} aria-label={t("overview.routing.groupLabel")}>
      {compact && tierEvidence.state !== "available" ? (
        <EvidenceSummary
          label={t("overview.routing.tierTitle")}
          href={routeHref("trust-routing")}
          state={tierEvidence.state}
        />
      ) : <DistributionPanel
        kicker={t("overview.routing.tierKicker")}
        heading={t("overview.routing.tierTitle")}
        rows={tiers}
        total={tiers.reduce((sum, row) => sum + row.count, 0)}
        hrefFor={(row) => routeHref("trust-routing", { segments: [row.key] })}
        labelFor={(row) => row.key.toUpperCase()}
        toneFor={(row) => row.key}
        unavailableHref={routeHref("trust-routing")}
        compact={compact}
      />}
      {compact && outcomeEvidence.state !== "available" ? (
        <EvidenceSummary
          label={tDashboard("controlOutcomes")}
          href={routeHref("audit", { params: sampleParams })}
          state={outcomeEvidence.state}
        />
      ) : <article class="overview-distribution-panel">
        <a class="overview-distribution-head" href={routeHref("audit", { params: sampleParams })}>
          <span>
            {!compact && <span class="overview-panel-kicker">{t("overview.routing.controlKicker")}</span>}
            <strong>{compact ? tDashboard("controlOutcomes") : t("overview.routing.controlTitle")}</strong>
          </span>
          {!compact && <small>{t("overview.routing.decisions", { count: outcomeTotal })}</small>}
        </a>
        <DistributionBlock
          heading={t("overview.routing.outcomeTitle")}
          rows={outcomes}
          hrefFor={(row) => routeHref("audit", {
            params: { ...sampleParams, outcome: row.key },
          })}
          labelFor={(row) => t(`overview.routing.outcome.${controlOutcomeGroup(row.key)}`)}
          toneFor={(row) => controlOutcomeGroup(row.key)}
          unavailableHref={routeHref("audit", { params: sampleParams })}
        />
        {!compact && <DistributionBlock
          heading={t("overview.routing.modeTitle")}
          rows={modes}
          hrefFor={(row) => routeHref("audit", {
            params: { ...modeSampleParams, mode: row.key },
          })}
          labelFor={(row) => t(`overview.routing.mode.${row.key}`)}
          toneFor={(row) => row.key}
          unavailableHref={routeHref("audit", { params: modeSampleParams })}
        />}
      </article>}
    </section>
  );
}

export function RequiredAttention({
  kpi,
  autonomy,
  gates,
  policyEscapes,
  compact = false,
  optionalPending = false,
}: Props) {
  const evidenceGaps = dashboardEvidenceGaps(autonomy);
  const controlGaps = controlGapSummary(kpi, policyEscapes, gates, autonomy);
  return (
    <section class="overview-attention-cards" aria-label={t("overview.attention.groupLabel")}>
      <AttentionCard
        compact={compact}
        summary={tDashboard("pendingCount", { count: kpi.hil_pending })}
        href={routeHref("hil-queue")}
        kicker={t("overview.attention.approvalKicker")}
        heading={t("overview.attention.approvalTitle")}
        state={kpi.hil_pending > 0 ? "attention" : "clear"}
        value={String(kpi.hil_pending)}
        facts={[
          [t("overview.attention.queueState"), kpi.hil_pending > 0
            ? t("overview.attention.hilTitle", { count: kpi.hil_pending })
            : t("overview.attention.approvalClear")],
        ]}
      />
      <AttentionCard
        compact={compact}
        loading={optionalPending}
        summary={controlGaps.measured
          ? tDashboard("controlGapCount", { count: controlGaps.count })
          : t("overview.evidence.unavailable")}
        href={routeHref("control-assurance")}
        kicker={t("overview.attention.controlKicker")}
        heading={t("overview.attention.controlTitle")}
        state={controlGaps.state}
        value={controlGaps.measured
          ? t("overview.attention.gapCount", { count: controlGaps.count })
          : t("overview.evidence.unavailable")}
        facts={[
          [t("overview.assurance.shadow"), formatShare(kpi.shadow_share)],
          [t("overview.assurance.promotion"), gates
            ? t("overview.guards.ready", { ready: gates.ready_count, total: gates.rows.length })
            : t("overview.evidence.unavailable")],
          [t("overview.assurance.escapes"), policyEscapes === null
            ? t("overview.evidence.unavailable")
            : String(policyEscapes)],
        ]}
      />
      <AttentionCard
        compact={compact}
        loading={optionalPending}
        summary={tDashboard("missingCount", { count: evidenceGaps.length })}
        href={routeHref("operating-outcomes")}
        kicker={t("overview.attention.evidenceKicker")}
        heading={t("overview.attention.evidenceTitle")}
        state={evidenceGaps.length > 0 ? "unknown" : "clear"}
        value={t("overview.attention.fieldCount", { count: evidenceGaps.length })}
        facts={evidenceGaps.length > 0
          ? evidenceGaps.slice(0, 3).map((gap) => [
              t(`overview.attention.evidenceGap.${gap}`),
              t("overview.attention.notConnected"),
            ] as const)
          : [[t("overview.attention.evidenceComplete"), t("overview.evidence.measured")]]}
      />
    </section>
  );
}

function DistributionPanel({
  kicker,
  heading,
  rows,
  total,
  hrefFor,
  labelFor,
  toneFor,
  unavailableHref,
  compact,
}: {
  readonly kicker: string;
  readonly heading: string;
  readonly rows: readonly DistributionRow[];
  readonly total: number;
  readonly hrefFor: (row: DistributionRow) => string;
  readonly labelFor: (row: DistributionRow) => string;
  readonly toneFor: (row: DistributionRow) => string;
  readonly unavailableHref: string;
  readonly compact: boolean;
}) {
  return (
    <article class="overview-distribution-panel">
      <a class="overview-distribution-head" href={unavailableHref}>
        <span>
          {!compact && <span class="overview-panel-kicker">{kicker}</span>}
          <strong>{heading}</strong>
        </span>
        {!compact && <small>{t("overview.routing.classified", { count: total })}</small>}
      </a>
      <DistributionBlock
        heading={heading}
        rows={rows}
        hrefFor={hrefFor}
        labelFor={labelFor}
        toneFor={toneFor}
        unavailableHref={unavailableHref}
      />
    </article>
  );
}

function DistributionBlock({
  heading,
  rows,
  hrefFor,
  labelFor,
  toneFor,
  unavailableHref,
}: {
  readonly heading: string;
  readonly rows: readonly DistributionRow[];
  readonly hrefFor: (row: DistributionRow) => string;
  readonly labelFor: (row: DistributionRow) => string;
  readonly toneFor: (row: DistributionRow) => string;
  readonly unavailableHref: string;
}) {
  if (rows.length === 0) {
    return (
      <a class="overview-distribution-unavailable" href={unavailableHref}>
        {t("overview.evidence.unavailable")}
      </a>
    );
  }
  return (
    <div class="overview-distribution-block">
      <span class="sr-only">{heading}</span>
      <div class="overview-distribution-bar">
        {rows.map((row) => (
          <a
            key={row.key}
            href={hrefFor(row)}
            aria-label={`${labelFor(row)} ${row.percentage}%`}
            class={`overview-distribution-segment tone-${toneFor(row)}`}
            style={{ width: `${row.share * 100}%` }}
          />
        ))}
      </div>
      <div class="overview-distribution-legend">
        {rows.map((row) => (
          <a key={row.key} href={hrefFor(row)}>
            <span class={`overview-distribution-dot tone-${toneFor(row)}`} aria-hidden="true" />
            <strong>{row.percentage}%</strong>
            <span>{labelFor(row)}</span>
            <small>{row.count}</small>
          </a>
        ))}
      </div>
    </div>
  );
}

function AttentionCard({
  href,
  kicker,
  heading,
  state,
  value,
  facts,
  compact,
  summary,
  loading = false,
}: {
  readonly href: string;
  readonly kicker: string;
  readonly heading: string;
  readonly state: "attention" | "clear" | "unknown";
  readonly value: string;
  readonly facts: readonly (readonly [string, string])[];
  readonly compact: boolean;
  readonly summary: string;
  readonly loading?: boolean;
}) {
  return (
    <a class="overview-attention-card" href={href}>
      <span class="overview-attention-card-head">
        <span>
          <span class="overview-panel-kicker">{kicker}</span>
          {!compact && <strong>{heading}</strong>}
        </span>
        {!loading && <span class={`overview-attention-state ${state}`}>
          {t(`overview.attention.state.${state}`)}
        </span>}
      </span>
      {loading ? <EvidenceLoading label={kicker} /> : <b class="overview-attention-value">{compact ? summary : value}</b>}
      {!compact && !loading && <dl>
        {facts.map(([label, fact]) => (
          <div key={label}><dt>{label}</dt><dd>{fact}</dd></div>
        ))}
      </dl>}
    </a>
  );
}
