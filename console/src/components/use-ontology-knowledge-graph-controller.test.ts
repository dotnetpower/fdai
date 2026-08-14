import { describe, expect, it } from "vitest";
import {
  ONTOLOGY_KNOWLEDGE_SETTLE_DURATION_MS,
  ontologyKnowledgeKeyboardCommand,
  ontologyKnowledgeSettleFrame,
} from "./use-ontology-knowledge-graph-controller";

describe("ontology topology keyboard commands", () => {
  it("maps pan, zoom, and fit keys without claiming unsupported selection", () => {
    expect(ontologyKnowledgeKeyboardCommand("ArrowUp")).toBe("pan-up");
    expect(ontologyKnowledgeKeyboardCommand("ArrowRight")).toBe("pan-right");
    expect(ontologyKnowledgeKeyboardCommand("+")).toBe("zoom-in");
    expect(ontologyKnowledgeKeyboardCommand("=")).toBe("zoom-in");
    expect(ontologyKnowledgeKeyboardCommand("-")).toBe("zoom-out");
    expect(ontologyKnowledgeKeyboardCommand("0")).toBe("fit");
    expect(ontologyKnowledgeKeyboardCommand("Home")).toBe("fit");
    expect(ontologyKnowledgeKeyboardCommand("Enter")).toBeNull();
  });

  it("bounds the initial spring and finishes without a persistent animation", () => {
    expect(ontologyKnowledgeSettleFrame(0, false)).toEqual({ progress: 0, done: false });
    const overshoot = ontologyKnowledgeSettleFrame(300, false);
    expect(overshoot.done).toBe(false);
    expect(overshoot.progress).toBeGreaterThan(1);
    expect(overshoot.progress).toBeLessThanOrEqual(1.12);
    expect(ontologyKnowledgeSettleFrame(ONTOLOGY_KNOWLEDGE_SETTLE_DURATION_MS, false))
      .toEqual({ progress: 1, done: true });
  });

  it("skips motion when reduced motion is requested", () => {
    expect(ontologyKnowledgeSettleFrame(0, true)).toEqual({ progress: 1, done: true });
  });
});
