import type { ComponentChildren } from "preact";
import type { AutonomyPayload } from "../types";
import {
  KpiCard,
  KpiGrid,
  StatusPill,
  UnavailableState,
  kpiEvidenceLabel,
} from "../components/ui";
import { routeHref } from "../router";
import { t } from "./i18n/analytics";
import type { AnalyticsData } from "./analytics-data";
import {
  auditSampleParams,
  controlOutcomeGroup,
  distributionRows,
  formatShare,
  overviewHealth,
} from "./dashboard.model";

export function guardDisplayState(
  synthetic: boolean,
  ok: boolean,
): "simulated" | "passing" | "blocked" {
  if (synthetic) return "simulated";
  return ok ? "passing" : "blocked";
}

export function measuredFailedGuardCount(autonomy: AutonomyPayload | null): number | null {
  if (autonomy === null || autonomy.synthetic) return null;
  return autonomy.guards.filter((guard) => !guard.ok).length;
}

export function meterPercent(value: number): number {
  return Math.max(0, Math.min(100, value * 100));
}

export function assuranceSectionHref(
  section: "promotion-guards" | "required-attention",
  context: Readonly<Record<string, string>> = {},
): string {
  return `${routeHref("control-assurance", { params: context })}#${section}`;
}

export function assurancePostureHref(
  attention: {
    readonly policyEscapes: number | null;
    readonly failedGuardKey: string | null;
    readonly pendingApprovals: number;
    readonly blockedCapabilities: number | null;
    readonly shadowShare: number;
    readonly window: string | undefined;
  },
  context: Readonly<Record<string, string>> = {},
): string {
  if (attention.policyEscapes !== null && attention.policyEscapes > 0) {
    return routeHref("promotion-gates", { params: { ...context, status: "blocked" } });
  }
  if (attention.failedGuardKey !== null) {
    return assuranceSectionHref("promotion-guards", {
      ...context,
      guard: attention.failedGuardKey,
    });
  }
  if (attention.pendingApprovals > 0) return routeHref("hil-queue", { params: context });
  if (attention.blockedCapabilities !== null && attention.blockedCapabilities > 0) {
    return routeHref("promotion-gates", { params: { ...context, status: "blocked" } });
  }
  if (attention.shadowShare < 0.95) {
    return routeHref("audit", {
      params: { ...context, window: attention.window, mode: "shadow" },
    });
  }
  return assuranceSectionHref("required-attention", context);
}

interface Props {
  readonly data: AnalyticsData;
  readonly evidence: ComponentChildren;
  readonly guardKey: string | null;
  readonly context: Readonly<Record<string, string>>;
}

export function ControlAssuranceBody({ data, evidence, guardKey, context }: Props) {
  const autonomy = data.autonomy;
  const escapes = data.gates?.rows.reduce((sum, row) => sum + row.policy_escapes, 0) ?? null;
  const health = overviewHealth(data.kpi, escapes, autonomy);
  const failedGuards = measuredFailedGuardCount(autonomy);
  const window = autonomy ? `${autonomy.window_days}d` : context["window"];
  const failedGuardKey = autonomy !== null && !autonomy.synthetic
    ? autonomy.guards.find((guard) => !guard.ok)?.key ?? null
    : null;
  const postureHref = assurancePostureHref({
    policyEscapes: escapes,
    failedGuardKey,
    pendingApprovals: data.kpi.hil_pending,
    blockedCapabilities: data.gates?.blocked_count ?? null,
    shadowShare: data.kpi.shadow_share,
    window,
  }, context);
  return (
    <div class="control-assurance stack">
      <AssuranceBanner
        health={health}
        failedGuards={failedGuards}
        policyEscapes={escapes}
        pendingApprovals={data.kpi.hil_pending}
      />
      {evidence}
      <KpiGrid>
        <KpiCard
          href={postureHref}
          label={t("analytics.assurance.posture")}
          value={t(`analytics.health.${health}`)}
          tone={health === "healthy" ? "positive" : health === "attention" ? "warning" : "default"}
        />
        <KpiCard
          evidenceState={escapes === null ? "not-measured" : "measured"}
          href={routeHref("promotion-gates", { params: { ...context, status: "blocked" } })}
          label={t("analytics.assurance.escapes")}
          value={escapes ?? kpiEvidenceLabel("not-measured")}
          hint={escapes === null ? t("analytics.notMeasuredHint") : t("analytics.assurance.escapeHint")}
          tone={escapes === null ? "default" : escapes === 0 ? "positive" : "warning"}
        />
        <KpiCard
          href={routeHref("audit", { params: { ...context, window, mode: "shadow" } })}
          label={t("analytics.assurance.shadow")}
          value={formatShare(data.kpi.shadow_share)}
          hint={t("analytics.assurance.shadowHint")}
        />
        <KpiCard
          evidenceState={data.gates ? "measured" : "not-connected"}
          href={routeHref("promotion-gates", { params: { ...context, status: "ready" } })}
          label={t("analytics.assurance.ready")}
          value={data.gates ? `${data.gates.ready_count}/${data.gates.rows.length}` : kpiEvidenceLabel("not-connected")}
          hint={data.gates ? t("analytics.assurance.readyHint", { blocked: data.gates.blocked_count }) : t("analytics.notConnectedHint")}
        />
      </KpiGrid>
      <GuardSection autonomy={autonomy} guardKey={guardKey} context={context} />
      <section class="assurance-lower-grid">
        <ControlPath data={data} />
        <RequiredAttention
          data={data}
          failedGuards={failedGuards}
          policyEscapes={escapes}
        />
      </section>
      <nav class="analytics-links" aria-label={t("analytics.relatedEvidence")}>
        <a href={routeHref("promotion-gates", { params: { ...context, status: "blocked" } })}>{t("analytics.viewPromotion")}</a>
        <a href={routeHref("hil-queue", { params: context })}>{t("analytics.viewApprovals")}</a>
        <a href={routeHref("audit", { params: { ...context, mode: "shadow" } })}>{t("analytics.viewShadowAudit")}</a>
      </nav>
    </div>
  );
}

function AssuranceBanner({
  health,
  failedGuards,
  policyEscapes,
  pendingApprovals,
}: {
  readonly health: "healthy" | "attention" | "unknown";
  readonly failedGuards: number | null;
  readonly policyEscapes: number | null;
  readonly pendingApprovals: number;
}) {
  return (
    <section class={`assurance-banner is-${health}`} aria-live="polite">
      <strong>{t(`analytics.assurance.banner.${health}Title`)}</strong>
      <span>{t(`analytics.assurance.banner.${health}Body`, {
        approvals: pendingApprovals,
        escapes: policyEscapes ?? t("analytics.unavailable"),
        guards: failedGuards ?? t("analytics.unavailable"),
      })}</span>
    </section>
  );
}

function GuardSection({
  autonomy,
  guardKey,
  context,
}: {
  readonly autonomy: AutonomyPayload | null;
  readonly guardKey: string | null;
  readonly context: Readonly<Record<string, string>>;
}) {
  const rows = guardKey === null
    ? autonomy?.guards ?? []
    : autonomy?.guards.filter((guard) => guard.key === guardKey) ?? [];
  return (
    <section class="assurance-section" id="promotion-guards">
      <header class="assurance-section-head">
        <div>
          <h3>{t("analytics.assurance.guardsTitle")}</h3>
          <p>{t("analytics.assurance.guardsSubtitle")}</p>
        </div>
        <span>{t("analytics.assurance.guardsMeta")}</span>
      </header>
      {autonomy === null ? (
        <UnavailableState message={t("analytics.autonomyUnavailable")} evidenceState="not-connected" />
      ) : rows.length === 0 ? (
        <UnavailableState message={guardKey === null ? t("analytics.assurance.guardsUnavailable") : t("analytics.invalidGuard")} />
      ) : (
        <div class="assurance-guard-list">
          {rows.map((guard) => {
            const state = guardDisplayState(autonomy.synthetic, guard.ok);
            return (
              <a
                class="assurance-guard"
                href={routeHref("control-assurance", { params: { ...context, guard: guard.key } })}
                key={guard.key}
              >
                <span class="assurance-guard-name">
                  <strong>{t(`overview.guardFull.${guard.key}`)}</strong>
                  <small>{t("analytics.assurance.guardBaseline", { value: formatPercent(guard.baseline) })}</small>
                </span>
                <span class="assurance-meter-column">
                  <span
                    class={`assurance-meter is-${state}`}
                    role="progressbar"
                    aria-label={t(`overview.guardFull.${guard.key}`)}
                    aria-valuemin={0}
                    aria-valuemax={100}
                    aria-valuenow={Math.round(meterPercent(guard.value))}
                  >
                    <span style={{ width: `${meterPercent(guard.value)}%` }} />
                  </span>
                  <span class="assurance-meter-meta">
                    <strong>{formatPercent(guard.value)}</strong>
                    <span>{t("analytics.assurance.guardThreshold", { value: formatPercent(guard.threshold) })}</span>
                  </span>
                </span>
                {state === "simulated" ? (
                  <StatusPill kind="neutral" label={t("analytics.simulatedStatus")} />
                ) : (
                  <StatusPill kind={state === "passing" ? "success" : "danger"} label={t(`analytics.${state}`)} />
                )}
              </a>
            );
          })}
        </div>
      )}
    </section>
  );
}

function ControlPath({ data }: { readonly data: AnalyticsData }) {
  const rows = distributionRows(data.kpi.by_outcome);
  const sampleParams = auditSampleParams(data.kpi);
  return (
    <section class="assurance-panel">
      <header class="assurance-panel-head">
        <div><h3>{t("analytics.assurance.controlPath")}</h3><p>{t("analytics.assurance.controlPathSubtitle")}</p></div>
        <span>{t("analytics.samples", { count: data.kpi.event_count })}</span>
      </header>
      {rows.length === 0 ? (
        <a class="assurance-panel-unavailable" href={routeHref("audit", { params: sampleParams })}>{t("analytics.unavailable")}</a>
      ) : (
        <>
          <div class="overview-distribution-bar">
            {rows.map((row) => (
              <a
                key={row.key}
                href={routeHref("audit", { params: { ...sampleParams, outcome: row.key } })}
                class={`overview-distribution-segment tone-${controlOutcomeGroup(row.key)}`}
                style={{ width: `${row.share * 100}%` }}
                aria-label={`${t(`overview.routing.outcome.${controlOutcomeGroup(row.key)}`)} ${Math.round(row.share * 100)}%`}
              />
            ))}
          </div>
          <div class="assurance-path-legend">
            {rows.map((row) => (
              <a key={row.key} href={routeHref("audit", { params: { ...sampleParams, outcome: row.key } })}>
                <span class={`overview-distribution-dot tone-${controlOutcomeGroup(row.key)}`} aria-hidden="true" />
                <strong>{Math.round(row.share * 100)}%</strong>
                <span>{t(`overview.routing.outcome.${controlOutcomeGroup(row.key)}`)}</span>
                <small>{row.count}</small>
              </a>
            ))}
          </div>
        </>
      )}
    </section>
  );
}

function RequiredAttention({
  data,
  failedGuards,
  policyEscapes,
}: {
  readonly data: AnalyticsData;
  readonly failedGuards: number | null;
  readonly policyEscapes: number | null;
}) {
  const rows = [
    [t("analytics.assurance.failedGuards"), failedGuards, assuranceSectionHref("promotion-guards")],
    [t("analytics.assurance.pendingApprovals"), data.kpi.hil_pending, routeHref("hil-queue")],
    [t("analytics.assurance.blockedCapabilities"), data.gates?.blocked_count ?? null, routeHref("promotion-gates", { params: { status: "blocked" } })],
    [t("analytics.assurance.policyEscapes"), policyEscapes, routeHref("promotion-gates", { params: { status: "blocked" } })],
  ] as const;
  return (
    <section class="assurance-panel" id="required-attention">
      <header class="assurance-panel-head">
        <div><h3>{t("analytics.assurance.attentionTitle")}</h3><p>{t("analytics.assurance.attentionSubtitle")}</p></div>
      </header>
      <div class="assurance-attention-list">
        {rows.map(([label, value, href]) => (
          <a href={href} key={label}>
            <span>{label}</span>
            <strong class={value === null ? "is-unavailable" : undefined}>{value ?? t("analytics.unavailable")}</strong>
          </a>
        ))}
      </div>
    </section>
  );
}

function formatPercent(value: number): string {
  return `${(value * 100).toFixed(1)}%`;
}
