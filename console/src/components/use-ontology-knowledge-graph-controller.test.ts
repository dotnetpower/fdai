import { describe, expect, it } from "vitest";
import { ontologyKnowledgeKeyboardCommand } from "./use-ontology-knowledge-graph-controller";

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
});
