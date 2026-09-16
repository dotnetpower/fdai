import { architectureHref } from "../components/architecture-map.model";
import type { RcaHypothesis } from "../types";
import { rcaText } from "./rca.i18n";

export function CausalChainSection({ hypothesis }: { readonly hypothesis: RcaHypothesis }) {
  const chain = hypothesis.causal_chain;
  if (chain === null || chain.hops.length === 0) return null;
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
        <div class="rca-causal-track" role="list">
          {chain.hops.map((hop, index) => (
            <div
              class="rca-causal-hop"
              key={`${hop.cause_event_id}:${hop.effect_event_id}:${index}`}
            >
              {index === 0 ? (
                <div class="rca-causal-node is-root" role="listitem">
                  <span>{rcaText("chainNodeRoot")}</span>
                  <a href={architectureHref(hop.cause_resource_ref)}>
                    {hop.cause_resource_ref}
                  </a>
                  <code>{hop.cause_event_id}</code>
                </div>
              ) : null}
              <div class="rca-causal-edge">
                <b aria-hidden="true">-&gt;</b>
                <strong>{hop.relationship}</strong>
                <small>
                  {rcaText("causalLead", { seconds: hop.lead_seconds.toFixed(1) })}
                </small>
                <small>
                  {rcaText("causalConfidence", { value: hop.confidence.toFixed(2) })}
                </small>
              </div>
              <div
                class={`rca-causal-node${index === chain.hops.length - 1 ? " is-failure" : ""}`}
                role="listitem"
              >
                <span>
                  {index === chain.hops.length - 1
                    ? rcaText("chainNodeFailure")
                    : rcaText("chainNodePropagation")}
                </span>
                <a href={architectureHref(hop.effect_resource_ref)}>
                  {hop.effect_resource_ref}
                </a>
                <code>{hop.effect_event_id}</code>
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
