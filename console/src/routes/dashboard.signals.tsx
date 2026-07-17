import type { AutonomyPayload, VerticalSummary } from "../types";
import { Tooltip } from "../components/tooltip";
import { t } from "../i18n";
import { routeHref } from "../router";
import { formatUsd } from "./dashboard.model";

export function VerticalCards({
  verticals,
}: {
  readonly verticals: readonly VerticalSummary[];
}) {
  return (
    <section class="overview-verticals" aria-label="per-vertical activity">
      {verticals.map((vertical) => (
        <VerticalCard key={vertical.key} vertical={vertical} />
      ))}
    </section>
  );
}

function VerticalCard({ vertical }: { readonly vertical: VerticalSummary }) {
  const hasRisk = vertical.open_risks > 0;
  const slug = vertical.key === "change_safety"
    ? "change-safety"
    : vertical.key === "cost"
      ? "cost-governance"
      : vertical.key;
  return (
    <a
      href={routeHref("verticals", { segments: [slug] })}
      class={`card overview-vertical overview-vertical-${vertical.key} overview-drill-card`}
    >
      <div class="overview-vertical-head">
        <span class="overview-vertical-name">{t(`overview.vertical.${vertical.key}`)}</span>
        {hasRisk ? (
          <span class="overview-vertical-risk">
            {t("overview.vertical.risks", { count: vertical.open_risks })}
          </span>
        ) : (
          <span class="overview-vertical-clear muted">{t("overview.vertical.clear")}</span>
        )}
      </div>
      <div class="overview-vertical-stats">
        <span>
          <b>{vertical.events}</b> {t("overview.vertical.events")}
        </span>
        <span>
          <b>{vertical.auto_resolved}</b> {t("overview.vertical.auto")}
        </span>
        {vertical.monthly_savings > 0 ? (
          <span class="overview-vertical-savings">
            {formatUsd(vertical.monthly_savings)}/mo
          </span>
        ) : null}
      </div>
    </a>
  );
}

export function TierBands({ tier }: { readonly tier: AutonomyPayload["tier"] }) {
  const keys = ["t0", "t1", "t2"] as const;
  return (
    <section class="overview-tiers" aria-label="trust tier mix vs target band">
      <span class="overview-guards-label">{t("overview.tier.label")}</span>
      {keys.map((key) => {
        const share = measuredTierMix(tier.mix, key);
        const band = tier.bands[key];
        const inBand = share !== null && (band ? share >= band[0] && share <= band[1] : true);
        const bandText = band
          ? `${Math.round(band[0] * 100)}-${Math.round(band[1] * 100)}%`
          : "";
        return (
          <Tooltip key={key} content={bandText ? t("overview.tier.band", { range: bandText }) : undefined}>
            <a
              href={routeHref("trust-routing", { segments: [key] })}
              class={`overview-tier overview-tier-${key} ${inBand ? "ok" : "warn"}`}
            >
              {key.toUpperCase()} {share === null ? "unavailable" : `${Math.round(share * 100)}%`}
            </a>
          </Tooltip>
        );
      })}
    </section>
  );
}

export function measuredTierMix(
  mix: Readonly<Record<string, number>>,
  key: string,
): number | null {
  return Object.hasOwn(mix, key) ? mix[key] ?? null : null;
}

export function livingRulesProvenance(
  autonomy: Pick<AutonomyPayload, "synthetic" | "source">,
): { readonly kind: "simulated" | "measured"; readonly source: string; readonly asOf: string | null } {
  return {
    kind: autonomy.synthetic ? "simulated" : "measured",
    source: autonomy.source.name,
    asOf: autonomy.source.as_of,
  };
}

export function LivingRules({
  rules,
  provenance,
}: {
  readonly rules: AutonomyPayload["rules"];
  readonly provenance: Pick<AutonomyPayload, "synthetic" | "source">;
}) {
  const evidence = livingRulesProvenance(provenance);
  return (
    <section class="overview-rules" aria-label="living rule catalog">
      <span class="overview-guards-label">{t("overview.rules.label")}</span>
      <span class="overview-rules-provenance">
        <strong>{t(`overview.evidence.${evidence.kind}`)}</strong>
        <small>
          {t("overview.evidence.source", { source: evidence.source })}
          {evidence.asOf ? ` - ${t("overview.evidence.asOf", { time: evidence.asOf })}` : ""}
        </small>
      </span>
      <a class="overview-rules-stat" href={routeHref("rules", { params: { status: "active", origin: "active" } })}>
        <b>{rules.active}</b> {t("overview.rules.active")}
      </a>
      <a class="overview-rules-stat" href={routeHref("rules", { params: { status: "promoted", window: "30d" } })}>
        <b>{rules.promoted_30d}</b> {t("overview.rules.promoted")}
      </a>
      <a class="overview-rules-stat muted" href={routeHref("rules", { params: { status: "candidate" } })}>
        <b>{rules.candidates_30d}</b> {t("overview.rules.candidates")}
      </a>
      <a class="overview-drill" href={routeHref("rules")}>
        {t("overview.drill.browse")}
      </a>
    </section>
  );
}
