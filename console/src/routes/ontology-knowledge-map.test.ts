import { describe, expect, it } from "vitest";
import { ontologyKnowledgeGraphSummary } from "../components/ontology-knowledge-graph.model";
import { loadOntologyKnowledgeGraph } from "./ontology-knowledge-map";

describe("ontology knowledge map", () => {
  it("loads the complete generated catalog graph without inventory input", async () => {
    const graph = await loadOntologyKnowledgeGraph();
    const summary = ontologyKnowledgeGraphSummary(graph);

    expect(summary.nodes).toBeGreaterThan(200);
    expect(summary.edges).toBeGreaterThan(500);
    expect(graph.generatedFrom).toBe("rule-catalog + PANTHEON_SPECS");
  });
});
