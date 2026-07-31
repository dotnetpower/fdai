import { useMemo } from "preact/hooks";
import { t } from "../i18n";
import { useViewContext } from "./context";

const FACT_DESCRIPTIONS: Readonly<Record<string, string>> = {
  eps: "eps",
  "session.total": "sessionTotal",
  "session.duration": "sessionDuration",
  "tiles.active": "tilesActive",
  "tiles.empty": "tilesEmpty",
  "tiles.shadow": "tilesShadow",
  "tier.t0": "tierT0",
  "tier.t1": "tierT1",
  "tier.t2": "tierT2",
  "gate.auto": "gateAuto",
  "gate.hil": "gateHil",
  "gate.abstain": "gateAbstain",
  "gate.deny": "gateDeny",
  "attention.total": "attentionTotal",
  "attention.hil": "attentionHil",
  "attention.deny": "attentionDeny",
  "attention.failed": "attentionFailed",
  "attention.stuck": "attentionStuck",
  "verticals.change": "verticalsChange",
  "verticals.resilience": "verticalResilience",
  "verticals.cost": "verticalCost",
  "verticals.unknown": "verticalUnknown",
};

const FACT_LABELS: Readonly<Record<string, string>> = {
  health: "health",
  event_count: "eventCount",
  shadow_share: "shadowShare",
  t0_share: "t0Share",
  hil_pending: "approvalsPending",
  section_count: "sectionCount",
  measurement_state: "measurementState",
  measurement_source: "measurementSource",
  measurement_synthetic: "measurementSynthetic",
  auto_resolution_rate: "autoResolutionRate",
  auto_resolution_baseline: "autoResolutionBaseline",
  human_touchpoints_per_100: "humanTouchpoints",
  mttr_seconds: "mttr",
  change_lead_time_seconds: "changeLeadTime",
  monthly_savings: "monthlySavings",
  cost_actions: "costActions",
  policy_escapes: "policyEscapes",
  promotion_ready: "promotionReady",
};

const GROUP_LABELS = new Set(["overview", "page", "autonomy", "cost", "guards", "facts"]);
const VALUE_LABELS: Readonly<Record<string, string>> = {
  attention: "attention",
  healthy: "healthy",
  measured: "measured",
  simulated: "simulated",
  unavailable: "unavailable",
  "not connected": "notConnected",
  "n/a": "notAvailable",
  true: "yes",
  false: "no",
};

export function digestFactLabel(key: string, label?: string): string {
  if (label) return label;
  const labelKey = FACT_LABELS[key];
  return labelKey ? t(`deck.digest.factLabel.${labelKey}`) : key.replace(/[._]/g, " ");
}

export function digestGroupLabel(group: string): string {
  return GROUP_LABELS.has(group) ? t(`deck.digest.group.${group}`) : group.replace(/[._]/g, " ");
}

export function digestFactValue(value: unknown): string {
  if (value === null) return "-";
  const raw = String(value);
  const valueKey = VALUE_LABELS[raw.toLowerCase()];
  return valueKey ? t(`deck.digest.value.${valueKey}`) : raw;
}

export function DigestList({ snapshot }: { readonly snapshot: ReturnType<typeof useViewContext> }) {
  const grouped = useMemo(() => {
    if (snapshot === null) return new Map<string, readonly { key: string; label?: string; value: unknown }[]>();
    const out = new Map<string, { key: string; label?: string; value: unknown }[]>();
    for (const fact of snapshot.facts) {
      const group = fact.group ?? "facts";
      const bucket = out.get(group) ?? [];
      bucket.push({ key: fact.key, ...(fact.label ? { label: fact.label } : {}), value: fact.value });
      out.set(group, bucket);
    }
    return out;
  }, [snapshot]);

  if (snapshot === null) {
    return (
      <div class="deck-digest-empty muted">
        {t("deck.digest.empty")}
      </div>
    );
  }

  const recordCount = snapshot.records
    ? Object.entries(snapshot.records).reduce((count, [, records]) => count + records.length, 0)
    : 0;

  return (
    <div class="deck-digest-body">
      {[...grouped.entries()].map(([group, facts]) => (
        <section key={group} class="deck-digest-group">
          <h4 class="deck-digest-group-title">{digestGroupLabel(group)}</h4>
          <dl class="deck-digest-list">
            {facts.map((fact) => {
              const descriptionKey = FACT_DESCRIPTIONS[fact.key];
              const description = descriptionKey ? t(`deck.digest.fact.${descriptionKey}`) : "";
              return (
                <div key={fact.key} class="deck-digest-row">
                  <dt title={fact.key}>{digestFactLabel(fact.key, fact.label)}</dt>
                  <dd>{digestFactValue(fact.value)}</dd>
                  {description ? (
                    <span class="deck-digest-tip" role="tooltip">
                      {description}
                    </span>
                  ) : null}
                </div>
              );
            })}
          </dl>
        </section>
      ))}
      {recordCount > 0 ? (
        <p class="deck-digest-records muted">
          {t("deck.digest.records", {
            count: recordCount,
            breakdown: "",
          })}
        </p>
      ) : null}
    </div>
  );
}
