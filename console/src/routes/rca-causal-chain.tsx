import { architectureHref } from "../components/architecture-map.model";
import {
  CorrelationTimeline,
  type CorrelationStepItem,
} from "../components/domain-primitives";
import type { RcaHypothesis } from "../types";
import { rcaText } from "./rca.i18n";

export function CausalChainSection({ hypothesis }: { readonly hypothesis: RcaHypothesis }) {
  const chain = hypothesis.causal_chain;
  if (chain === null || chain.hops.length === 0) return null;
  const firstHop = chain.hops[0]!;
  const items: CorrelationStepItem[] = [
    {
      id: `root:${firstHop.cause_event_id}`,
      title: rcaText("chainNodeRoot"),
      stateLabel: rcaText("chainNodeRoot"),
      tone: "human",
      detail: (
        <div class="rca-causal-node is-root">
          <span>{rcaText("chainNodeRoot")}</span>
          <a href={architectureHref(firstHop.cause_resource_ref)}>
            {firstHop.cause_resource_ref}
          </a>
          <code>{firstHop.cause_event_id}</code>
        </div>
      ),
    },
    ...chain.hops.map((hop, index): CorrelationStepItem => {
      const isFailure = index === chain.hops.length - 1;
      const roleLabel = isFailure
        ? rcaText("chainNodeFailure")
        : rcaText("chainNodePropagation");
      return {
        id: `${hop.cause_event_id}:${hop.effect_event_id}:${index}`,
        title: hop.relationship,
        stateLabel: roleLabel,
        tone: isFailure ? "sec" : "sre",
        current: isFailure,
        timestamp: `${rcaText("causalLead", { seconds: hop.lead_seconds.toFixed(1) })} / ${rcaText("causalConfidence", { value: hop.confidence.toFixed(2) })}`,
        detail: (
          <div class={`rca-causal-node${isFailure ? " is-failure" : ""}`}>
            <span>{roleLabel}</span>
            <a href={architectureHref(hop.effect_resource_ref)}>
              {hop.effect_resource_ref}
            </a>
            <code>{hop.effect_event_id}</code>
          </div>
        ),
      };
    }),
  ];

  return (
    <section class="rca-detail-section" aria-labelledby={`rca-chain-${hypothesis.seq}`}>
      <header class="rca-section-heading">
        <h4 id={`rca-chain-${hypothesis.seq}`}>{rcaText("causalChain")}</h4>
        <span>
          {rcaText("causalSummary", {
            hops: chain.hops.length,
            ambiguity: chain.ambiguity,
          })}
        </span>
      </header>
      <div class="rca-causal-panel">
        <CorrelationTimeline
          variant="causal"
          ariaLabel={rcaText("causalChain")}
          items={items}
        />
      </div>
    </section>
  );
}
