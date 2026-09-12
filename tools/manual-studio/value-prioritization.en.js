/** Assemble the 25-slide value-prioritization workshop; it grants no runtime authority. */
import { evidenceLine, sources } from "./value-prioritization-slide-kit.en.js";
import { buildValuePrioritizationFoundations } from "./value-prioritization-foundations.en.js";
import { buildValuePrioritizationEligibility } from "./value-prioritization-eligibility.en.js";
import { buildValuePrioritizationValue } from "./value-prioritization-value.en.js";
import { buildValuePrioritizationPortfolio } from "./value-prioritization-portfolio.en.js";
import { buildValuePrioritizationAction } from "./value-prioritization-action.en.js";

/** Return the complete static deck in its authored decision sequence. */
export function buildValuePrioritizationDeck() {
  const cover = {
    brandLogo: "assets/microsoft-logo.png",
    eyebrow: "VISION & VALUE / L200",
    deckTitle: "FDAI / VALUE PORTFOLIO",
    title: "Use Case &<br>Value Prioritization",
    lead: "A portfolio workshop for choosing the first verifiable decision",
    layout: "briefing-value-cover deck-value-prioritization",
    priority: {
      id: "cover",
      chapter: 1,
      state: "PROPOSAL",
      sources: [sources.constitution, sources.metrics],
    },
    content: `
      <section class="vp-cover-field" aria-hidden="true">
        <i></i><i></i><i></i><i></i>
      </section>
      <div class="vp-cover-meta"><span>L200</span><span>35 MIN</span><span>25 SLIDES</span></div>
      ${evidenceLine(["constitution", "metrics"])}`,
  };

  return [
    cover,
    ...buildValuePrioritizationFoundations(),
    ...buildValuePrioritizationEligibility(),
    ...buildValuePrioritizationValue(),
    ...buildValuePrioritizationPortfolio(),
    ...buildValuePrioritizationAction(),
  ];
}
