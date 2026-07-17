import { useMemo } from "preact/hooks";
import { useViewContext } from "./context";

const FACT_DESCRIPTIONS: Readonly<Record<string, string>> = {
  eps: "Events per second the control loop is processing (60s rolling).",
  "session.total": "Total events seen since this live session started.",
  "session.duration": "How long this live session has been running.",
  "tiles.active": "Tiles currently showing an in-flight action.",
  "tiles.empty": "Unused tiles in the cockpit grid.",
  "tiles.shadow": "Tiles running in shadow mode (judge-and-log, no execution).",
  "tier.t0": "Share routed to T0 - deterministic policy (target 70-80%).",
  "tier.t1": "Share routed to T1 - lightweight similarity / small model (15-20%).",
  "tier.t2": "Share routed to T2 - frontier-model reasoning, novel cases only (5-10%).",
  "gate.auto": "Actions the risk gate auto-executed (low risk).",
  "gate.hil": "High-risk actions routed to human approval.",
  "gate.abstain": "Cases the gate abstained on - no autonomous action taken.",
  "gate.deny": "Actions the gate denied outright.",
  "attention.total": "Items currently needing operator attention.",
  "attention.hil": "Items waiting on a human approval.",
  "attention.deny": "Denied actions flagged for review.",
  "attention.failed": "Actions that failed during execution.",
  "attention.stuck": "Actions stuck without progress past their budget.",
  "verticals.change": "Change Safety events (safe change, drift remediation).",
  "verticals.resilience": "Resilience events (disaster recovery, chaos testing).",
  "verticals.cost": "Cost Governance events (FinOps).",
  "verticals.unknown": "Events not yet classified into a vertical.",
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
        No route has published a view snapshot. Open Live, Dashboard, Audit,
        Approvals, Trace, Blast Radius, Promotion, or Ontology.
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
              const description = FACT_DESCRIPTIONS[fact.key] ?? "";
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
          + {recordCount} record(s) available for the answerer to search
          {snapshot.records
            ? " (" +
              Object.entries(snapshot.records)
                .map(([key, records]) => `${key}: ${records.length}`)
                .join(", ") +
              ")"
            : ""}
          .
        </p>
      ) : null}
    </div>
  );
}
