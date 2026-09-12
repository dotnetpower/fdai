/** Assemble the 32-slide readiness workshop; all examples are static and authority-free. */
import { evidenceLine, sources } from "./readiness-slide-kit.en.js";
import { buildReadinessFoundations } from "./readiness-foundations.en.js";
import { buildReadinessAi } from "./readiness-ai.en.js";
import { buildReadinessMaturityModel } from "./readiness-maturity-model.en.js";
import { buildReadinessActionPlan } from "./readiness-action-plan.en.js";

/** Return the complete static deck in its authored chapter order. */
export function buildReadinessMaturityDeck() {
  const cover = {
    eyebrow: "DISCOVERY & ALIGNMENT / L200",
    title: "AI / Data<br>Readiness & Maturity",
    lead: "Data and operating capabilities for the first validation",
    layout: "briefing-readiness-cover deck-readiness-maturity",
    readiness: { id: "cover", chapter: 1, visual: "cover", state: "PROPOSAL", sources: [sources.constitution] },
    content: `<section class="rm-visual rm-cover" aria-hidden="true"></section>${evidenceLine(["constitution"])}`,
  };
  return [cover, ...buildReadinessFoundations(), ...buildReadinessAi(),
    ...buildReadinessMaturityModel(), ...buildReadinessActionPlan()];
}
