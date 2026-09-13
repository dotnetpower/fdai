import type { ComponentChildren } from "preact";
import type { AutonomyPayload, DashboardKpi } from "../types";
import { t } from "../i18n";
import { routeHref } from "../router";
import { auditSampleParams, formatShare } from "./dashboard.model";
import { tDashboard } from "./i18n/dashboard-essential";
import { EvidenceLoading, EvidenceSummary } from "./dashboard.evidence";

/** Presents observed posture without converting absent measurements into zero. */
export function CurrentPosture({ kpi, autonomy, policyEscapes, pending = false }: {
  readonly kpi: DashboardKpi;
  readonly autonomy: AutonomyPayload | null;
  readonly policyEscapes: number | null;
  readonly pending?: boolean;
}) {
  const metric = autonomy?.success.auto_resolution_rate;
  const value = metric?.value ?? null;
  const baseline = metric?.baseline ?? null;
  const sample = kpi.audit_sample;
  const sampleParams = auditSampleParams(kpi);
  const summary = value === null && !pending;
  const metricHref = routeHref("operating-outcomes", { segments: ["auto-resolution"] });
  return (
    <div class={`overview-posture${summary ? " is-summary" : ""}`}>
      {!summary && <a class="overview-primary-metric" href={metricHref}>
        <span class="overview-linked-label">{t("overview.metric.autoRes")}</span>
        {value === null ? (
          <EvidenceLoading label={t("overview.metric.autoRes")} />
        ) : (
          <span class="overview-progress-ring">
            <svg viewBox="0 0 100 100" aria-hidden="true" focusable="false">
              <circle class="overview-ring-track" cx="50" cy="50" r="42" />
              <circle class="overview-ring-value" cx="50" cy="50" r="42" pathLength="100"
                stroke-dasharray={`${value * 100} ${100 - value * 100}`} transform="rotate(-90 50 50)" />
              {baseline !== null && (
                <line class="overview-ring-baseline" x1="50" y1="3" x2="50" y2="13"
                  transform={`rotate(${baseline * 360} 50 50)`} />
              )}
            </svg>
            <strong>{Math.round(value * 100)}%</strong>
          </span>
        )}
        {!pending && <small>{baseline === null
          ? t("overview.evidence.baselineUnavailable")
          : tDashboard("baseline", { value: `${Math.round(baseline * 100)}%` })}</small>}
        {value !== null && baseline !== null && (
          <small>{tDashboard("delta", { value: `${value >= baseline ? "+" : ""}${Math.round((value - baseline) * 100)}` })}</small>
        )}
      </a>}
      <div class="overview-posture-facts">
        <PostureFact
          href={routeHref("audit", { params: { ...sampleParams, mode: "shadow" } })}
          label={tDashboard("observation")}
          value={formatShare(kpi.shadow_share)}
          hint={tDashboard("observationHint")}
        />
        <PostureFact
          href={routeHref("promotion-gates")}
          label={tDashboard("escapes")}
          value={pending ? <EvidenceLoading label={tDashboard("escapes")} /> : policyEscapes === null ? t("overview.evidence.unavailable") : policyEscapes}
          hint={pending ? undefined : policyEscapes === null ? tDashboard("registryMissing") : tDashboard("escapesHint")}
        />
        <PostureFact
          href={routeHref("audit", { params: sampleParams })}
          label={tDashboard("sample")}
          value={sample === null ? t("overview.evidence.unavailable") : t("overview.evidence.sample", { samples: sample.row_count })}
          hint={sample?.from_seq !== null && sample?.from_seq !== undefined && sample.through_seq !== null
            ? tDashboard("sequence", { from: sample.from_seq, through: sample.through_seq })
            : tDashboard("sampleMissing")}
        />
      </div>
      {summary && (
        <EvidenceSummary
          label={t("overview.metric.autoRes")}
          href={metricHref}
          description={baseline === null ? undefined
            : t("overview.metric.vsBaseline", { baseline: `${Math.round(baseline * 100)}%` })}
        />
      )}
    </div>
  );
}

function PostureFact({ href, label, value, hint }: {
  readonly href: string;
  readonly label: string;
  readonly value: ComponentChildren;
  readonly hint?: string | undefined;
}) {
  return (
    <a class="overview-posture-fact" href={href}>
      <span class="overview-linked-label">{label}</span>
      <strong>{value}</strong>
      {hint && <small>{hint}</small>}
    </a>
  );
}
