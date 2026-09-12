/** Assemble the 25-slide FDAI target-architecture review; it grants no runtime authority. */
import { evidenceLine, sources } from "./target-architecture-slide-kit.en.js";
import { buildTargetArchitectureReview } from "./target-architecture-review.en.js";
import { buildTargetArchitectureRuntime } from "./target-architecture-runtime.en.js";
import { buildTargetArchitectureDecision } from "./target-architecture-decision.en.js";
import { buildTargetArchitectureExecution } from "./target-architecture-execution.en.js";
import { buildTargetArchitectureDeployment } from "./target-architecture-deployment.en.js";

/** Return the complete static architecture-review deck in decision order. */
export function buildTargetArchitectureDeck() {
  const cover = {
    brandLogo: "assets/microsoft-logo.png",
    eyebrow: "ARCHITECTURE & VALIDATION / L200",
    deckTitle: "FDAI / ARCHITECTURE REVIEW",
    title: "FDAI Target<br>Architecture",
    lead: "Agent-based operations control plane and Azure deployment",
    showDate: true,
    layout: "briefing-target-cover deck-target-architecture",
    architecture: {
      id: "cover",
      chapter: 1,
      state: "CONDITIONAL",
      diagramKind: "cover",
      sources: [sources.architectureGuide, sources.constitution, sources.arb],
    },
    content: `
      <section class="ta-cover-field" aria-hidden="true">
        <span></span><span></span><span></span><span></span><span></span>
        <i></i><i></i><i></i><i></i>
      </section>
      <div class="ta-cover-meta"><span>L200</span><span>40 MIN</span><span>25 SLIDES</span></div>
      ${evidenceLine(["architectureGuide", "constitution", "arb"])}`,
  };

  return [
    cover,
    ...buildTargetArchitectureReview(),
    ...buildTargetArchitectureRuntime(),
    ...buildTargetArchitectureDecision(),
    ...buildTargetArchitectureExecution(),
    ...buildTargetArchitectureDeployment(),
  ];
}
