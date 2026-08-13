import { describe, expect, it } from "vitest";
import type { OntologyKnowledgeGraph } from "../components/ontology-knowledge-graph.model";
import { OntologyKnowledgeMap } from "./ontology-knowledge-map";

describe("ontology knowledge map", () => {
  it("renders only the exact-release graph supplied by the parent projection", () => {
    const graph: OntologyKnowledgeGraph = {
      schemaVersion: "2.0.0",
      generatedFrom: "operator ontology projection",
      ontologyReleaseDigest: `sha256:${"2".repeat(64)}`,
      mutationAuthority: false,
      nodes: [],
      edges: [],
    };
    const view = OntologyKnowledgeMap({ graph });

    expect(view.props.class).toBe("ontology-knowledge-map");
    expect(graph.generatedFrom).toBe("operator ontology projection");
  });
});
