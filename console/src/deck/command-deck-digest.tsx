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
  "verticals.change": "verticalChange",
  "verticals.resilience": "verticalResilience",
  "verticals.cost": "verticalCost",
  "verticals.unknown": "verticalUnknown",
};

export function DigestList({ snapshot }: { readonly snapshot: ReturnType<typeof useViewContext> }) {
  const grouped = useMemo(() => {
    if (snapshot === null) return new Map<string, readonly { key: string; value: unknown }[]>();
    const out = new Map<string, { key: string; value: unknown }[]>();
    for (const fact of snapshot.facts) {
      const group = fact.group ?? "facts";
      const bucket = out.get(group) ?? [];
      bucket.push({ key: fact.key, value: fact.value });
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
          <h4 class="deck-digest-group-title">{group}</h4>
          <dl class="deck-digest-list">
            {facts.map((fact) => {
              const descriptionKey = FACT_DESCRIPTIONS[fact.key];
              const description = descriptionKey ? t(`deck.digest.fact.${descriptionKey}`) : "";
              return (
                <div key={fact.key} class="deck-digest-row">
                  <dt>{fact.key}</dt>
                  <dd>{fact.value === null ? "-" : String(fact.value)}</dd>
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
            breakdown: snapshot.records
              ? Object.entries(snapshot.records)
                  .map(([key, records]) => `${key}: ${records.length}`)
                  .join(", ")
              : "",
          })}
        </p>
      ) : null}
    </div>
  );
}
