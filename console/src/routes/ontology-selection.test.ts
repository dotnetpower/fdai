import { describe, expect, it } from "vitest";
import type { OntologyEdge, OntologyNode } from "../components/ontology-graph";
import {
  ontologyNamedSelection,
  selectedOntologyExplanations,
  selectedOntologyRecords,
} from "./ontology";
import {
  ontologyActionFiltersFromSearch,
  ontologyActionHref,
  requestedOntologyAction,
  resolveOntologyActionSelection,
} from "./ontology-actions";
import type { OntologyActionTypeRecord } from "./ontology.types";

function action(name: string): OntologyActionTypeRecord {
  return { name } as OntologyActionTypeRecord;
}

describe("ontology explicit selections", () => {
  it("keeps an absent ActionType selection implicit", () => {
    expect(requestedOntologyAction(new URLSearchParams())).toBeNull();
    expect(requestedOntologyAction(new URLSearchParams("action=alpha"))).toBe("alpha");
  });

  it("defaults only when no LinkType or ActionType was requested", () => {
    expect(ontologyNamedSelection(["alpha", "beta"], null)).toBe("alpha");
    expect(ontologyNamedSelection(["alpha", "beta"], "missing")).toBe("missing");
  });

  it("publishes the selected ObjectType and its one-hop relationships", () => {
    const nodes = [
      { name: "Agent", key: "agent", property_count: 13, properties: ["id"], description: "Agent type", lifecycle: null },
      {
        name: "Issue",
        key: "issue",
        property_count: 10,
        properties: ["id"],
        description: "Issue type",
        lifecycle: {
          owner: "Saga",
          creation: [{
            code: "agent_handoff",
            when: "An Agent emits HandoffEscalation.",
            result: "Saga creates Issue.",
            source_refs: ["src/fdai/agents/saga.py#escalate_to_github_issue"],
          }],
          closure: [],
          authority_refs: ["rule-catalog/vocabulary/object-types/Issue.yaml"],
        },
      },
    ] satisfies OntologyNode[];
    const edges = [{
      name: "raises",
      from_type: "Agent",
      to_type: "Issue",
      cardinality: "many_to_many",
      is_transitive: false,
      is_causal: false,
      temporal_order: false,
      description: "Agent raises Issue",
    }] satisfies OntologyEdge[];

    expect(selectedOntologyRecords(nodes, edges, "Agent")).toEqual({
      selected_object_types: [{
        name: "Agent",
        properties: 13,
        property_names: ["id"],
        description: "Agent type",
      }],
      selected_relationships: [{
        link: "raises",
        from: "Agent",
        to: "Issue",
        neighbor: "Issue",
        direction: "outgoing",
        cardinality: "many_to_many",
        causal: false,
        description: "Agent raises Issue",
      }],
    });
    expect(selectedOntologyExplanations(nodes, edges, "Agent")).toMatchObject({
      selection: { entity_kind: "ObjectType", entity_id: "Agent" },
      relationships: [{ link: "raises", neighbor: "Issue", direction: "outgoing" }],
      lifecycles: [{ entity_id: "Issue", owner: "Saga" }],
      provenance: { authority: "ontology_catalog" },
    });
  });

  it("never substitutes another ActionType for an invalid or filtered selection", () => {
    const alpha = action("alpha");
    const beta = action("beta");
    expect(resolveOntologyActionSelection([alpha, beta], [alpha, beta], null)).toBe(alpha);
    expect(resolveOntologyActionSelection([alpha, beta], [alpha, beta], "missing")).toBeNull();
    expect(resolveOntologyActionSelection([alpha, beta], [beta], "alpha")).toBeNull();
  });

  it("round-trips ActionType filters through selection links", () => {
    const filters = ontologyActionFiltersFromSearch(new URLSearchParams(
      "q=restart&category=ops&trigger=operator_request&execution=direct_api",
    ));

    expect(filters).toEqual({
      query: "restart",
      category: "ops",
      trigger: "operator_request",
      execution: "direct_api",
    });
    expect(ontologyActionHref(filters, "restart-service")).toBe(
      "/ontology?view=actions&action=restart-service&q=restart&category=ops&trigger=operator_request&execution=direct_api",
    );
  });

  it("omits default ActionType filters from the canonical URL", () => {
    const filters = ontologyActionFiltersFromSearch(new URLSearchParams());

    expect(ontologyActionHref(filters, null)).toBe("/ontology?view=actions");
  });
});
