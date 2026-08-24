import { describe, expect, it } from "vitest";
import {
  decodeOntologyInstanceDirectory,
  decodeOntologyInstanceExploration,
  groupOntologyInstanceRelationships,
  isOntologyInstanceDirectoryResource,
  ontologyInstanceAutocompleteSuggestions,
  ontologyInstanceResourceAutocompleteOptions,
  ontologyInstanceResourceOptionLabel,
  ontologyInstanceTrafficDirection,
  partitionOntologyInstanceLinks,
  resolveOntologyInstanceAutocomplete,
} from "./ontology-instances.model";

function payload(): Record<string, unknown> {
  return {
    schema_version: "1.3.0",
    ontology_release_digest: `sha256:${"a".repeat(64)}`,
    source_generation: "generation-1",
    source_cutoff: "2026-08-22T00:00:00+00:00",
    root_id: "root",
    depth: 8,
    link_types: ["depends_on"],
    resources: [
      {
        id: "root",
        object_type: "Resource",
        resource_type: "compute.container-app",
        name: "core",
        location: "koreacentral",
        resource_group: "resource-group-one",
        status: "Succeeded",
        last_seen: "2026-08-22T00:00:00+00:00",
        selected: true,
      },
      {
        id: "environment",
        object_type: "Resource",
        resource_type: "compute.container-app-environment",
        name: "environment",
        location: null,
        resource_group: null,
        status: null,
        last_seen: null,
        selected: false,
      },
    ],
    links: [{
      source: "root",
      target: "environment",
      link_type: "depends_on",
      evidence: relationshipEvidence(),
    }],
    timeline: {
      items: [
        {
          sequence: 42,
          action_kind: "audit.record",
          actor: "fdai.system",
          recorded_at: "2026-08-22T00:00:00+00:00",
          correlation_id: null,
          facts: { reason: "no_rule_match" },
          evidence_ref: "audit:42",
        },
      ],
      complete: true,
      truncation_reason: null,
    },
    sources: [
      { source: "inventory_snapshot", status: "available", observed_at: "2026-08-22T00:00:00+00:00", reason: null },
      { source: "inventory_relationships", status: "available", observed_at: "2026-08-22T00:00:00+00:00", reason: null },
      { source: "fdai_audit", status: "available", observed_at: "2026-08-22T00:00:00+00:00", reason: null },
      { source: "runtime_call_graph", status: "unavailable", observed_at: null, reason: "endpoint_identity_projection_unavailable" },
      { source: "postgres_role_evidence", status: "unavailable", observed_at: null, reason: "projection_not_bound" },
      { source: "azure_resource_health", status: "unavailable", observed_at: null, reason: "projection_not_bound" },
    ],
    complete: true,
    relationship_drop_reasons: [],
    relationship_drop_classifications: [],
    truncation_reasons: [],
    execution_authority: false,
    mutation_authority: false,
  };
}

describe("decodeOntologyInstanceExploration", () => {
  it("accepts one bounded root neighborhood with durable activity", () => {
    const decoded = decodeOntologyInstanceExploration(payload());

    expect(decoded.root_id).toBe("root");
    expect(decoded.links).toHaveLength(1);
    expect(decoded.timeline.items[0]?.evidence_ref).toBe("audit:42");
  });

  it("accepts bounded mapping-specific relationship coverage", () => {
    const value = payload();
    value.complete = false;
    value.relationship_drop_reasons = ["missing_target_endpoint"];
    value.relationship_drop_classifications = [{
      reason: "missing_target_endpoint",
      mapping_id: "azure.example-depends-on-target",
      source_property_path: "properties.target.id",
      source_provider_type: "microsoft.example/widgets",
      target_provider_type: "Microsoft.Example/targets",
      unavailable_reason: "target_outside_active_generation",
      count: 2,
    }];

    const decoded = decodeOntologyInstanceExploration(value);

    expect(decoded.relationship_drop_classifications).toEqual(
      value.relationship_drop_classifications,
    );
  });

  it("accepts unavailable authorization child-scope evidence", () => {
    const value = payload();
    value.complete = false;
    value.relationship_drop_reasons = ["target_type_mismatch"];
    value.relationship_drop_classifications = [{
      reason: "target_type_mismatch",
      mapping_id: "azure.role-assignment-attached-to-scope",
      source_property_path: "properties.scope",
      source_provider_type: "microsoft.authorization/roleassignments",
      target_provider_type: "microsoft.management/managementgroups",
      unavailable_reason: "authorization_child_scope_unmodeled",
      count: 1,
    }];

    const decoded = decodeOntologyInstanceExploration(value);

    expect(decoded.relationship_drop_classifications[0]?.unavailable_reason).toBe(
      "authorization_child_scope_unmodeled",
    );
  });

  it.each([
    ["authority", (value: Record<string, unknown>) => { value.execution_authority = true; }],
    ["dangling edge", (value: Record<string, unknown>) => {
      value.links = [{ source: "missing", target: "root", link_type: "contains" }];
    }],
    ["activity evidence", (value: Record<string, unknown>) => {
      const timeline = value.timeline as { items: Record<string, unknown>[] };
      timeline.items[0]!.evidence_ref = "audit:41";
    }],
    ["truncation", (value: Record<string, unknown>) => {
      value.complete = false;
    }],
    ["relationship evidence", (value: Record<string, unknown>) => {
      const links = value.links as Record<string, unknown>[];
      links[0]!.evidence = {
        status: "unavailable",
        evidence_kind: "configuration",
        source: null,
        source_property_path: null,
        mapping_id: null,
        evidence_method: null,
        cutoff: null,
        freshness_ceiling_seconds: null,
        complete: false,
        reason: "provider_relationship_evidence_unavailable",
      };
    }],
  ])("rejects invalid %s", (_label, mutate) => {
    const value = payload();
    mutate(value);
    expect(() => decodeOntologyInstanceExploration(value)).toThrow();
  });
});

describe("partitionOntologyInstanceLinks", () => {
  it("keeps only root-adjacent links in the direct partition", () => {
    const decoded = decodeOntologyInstanceExploration(payload());
    const pathLink = {
      ...decoded.links[0]!,
      source: "environment",
      target: "other",
    };
    const partitions = partitionOntologyInstanceLinks(
      [...decoded.links, pathLink],
      decoded.root_id,
    );

    expect(partitions.direct).toEqual(decoded.links);
    expect(partitions.path).toEqual([pathLink]);
  });

  it("keeps non-network routes and dependencies as graph direction", () => {
    const decoded = decodeOntologyInstanceExploration(payload());
    const alertRoute = relationship(
      "root",
      "action-group",
      "routes_to",
      "azure.alert-rule-routes-to-action-group",
    );
    const groups = groupOntologyInstanceRelationships(
      [...decoded.links, alertRoute],
      decoded.root_id,
    );

    expect(groups.directOutgoing).toEqual([decoded.links[0], alertRoute]);
    expect(groups.verifiedIngress).toEqual([]);
    expect(groups.verifiedEgress).toEqual([]);
  });

  it("classifies only reviewed network mappings as verified traffic paths", () => {
    const ingress = relationship(
      "gateway",
      "root",
      "routes_to",
      "azure.application-gateway-routes-to-configured-backend",
    );
    const egress = relationship(
      "root",
      "public-ip",
      "routes_to",
      "azure.aks-routes-to-effective-outbound-ip",
    );
    const access = relationship(
      "private-endpoint",
      "root",
      "attached_to",
      "azure.private-endpoint-attached-to-service",
    );

    expect(ontologyInstanceTrafficDirection(ingress, "root")).toBe("ingress");
    expect(ontologyInstanceTrafficDirection(egress, "root")).toBe("egress");
    expect(ontologyInstanceTrafficDirection(access, "root")).toBeNull();
    expect(groupOntologyInstanceRelationships([ingress, egress, access], "root"))
      .toMatchObject({
        verifiedIngress: [ingress],
        verifiedEgress: [egress],
        accessContext: [access],
      });
  });
});

function relationshipEvidence(): Record<string, unknown> {
  return {
    status: "available",
    evidence_kind: "configuration",
    source: "azure-resource-graph",
    source_property_path: "properties.managedEnvironmentId",
    mapping_id: "azure.container-app-depends-on-managed-environment",
    evidence_method: "deterministic-cross-check",
    cutoff: "2026-08-22T00:00:00+00:00",
    freshness_ceiling_seconds: 21600,
    complete: true,
    reason: null,
  };
}

function relationship(
  source: string,
  target: string,
  linkType: "attached_to" | "routes_to",
  mappingId: string,
) {
  return {
    source,
    target,
    link_type: linkType,
    evidence: {
      status: "available" as const,
      evidence_kind: "configuration" as const,
      source: "azure-resource-graph",
      source_property_path: "properties.referenceId",
      mapping_id: mappingId,
      evidence_method: "deterministic-cross-check",
      cutoff: "2026-08-22T00:00:00+00:00",
      freshness_ceiling_seconds: 21600,
      complete: true,
      reason: null,
    },
  };
}

describe("decodeOntologyInstanceDirectory", () => {
  it("accepts a complete active-generation directory", () => {
    const value = payload();
    const decoded = decodeOntologyInstanceDirectory({
      schema_version: "1.0.0",
      ontology_release_digest: value.ontology_release_digest,
      source_generation: value.source_generation,
      source_cutoff: value.source_cutoff,
      search: "core",
      resources: (value.resources as Record<string, unknown>[]).map((resource) => ({
        ...resource,
        selected: false,
      })),
      complete: true,
      truncation_reason: null,
      execution_authority: false,
      mutation_authority: false,
    });

    expect(decoded.search).toBe("core");
    expect(decoded.resources).toHaveLength(2);
  });

  it("rejects a selected directory row", () => {
    const value = payload();
    expect(() => decodeOntologyInstanceDirectory({
      schema_version: "1.0.0",
      ontology_release_digest: value.ontology_release_digest,
      source_generation: value.source_generation,
      source_cutoff: value.source_cutoff,
      search: null,
      resources: [
        {
          ...(value.resources as Record<string, unknown>[])[0],
          selected: true,
        },
      ],
      complete: true,
      truncation_reason: null,
      execution_authority: false,
      mutation_authority: false,
    })).toThrow();
  });
});

describe("Resource instance autocomplete", () => {
  const resources = decodeOntologyInstanceExploration(payload()).resources;

  it("excludes role assignments from operator-selectable Resources", () => {
    expect(isOntologyInstanceDirectoryResource(resources[0]!)).toBe(true);
    expect(isOntologyInstanceDirectoryResource({
      ...resources[0]!,
      id: "role-assignment",
      resource_type: "authorization.role-assignment",
    })).toBe(false);
  });

  it("resolves one exact display label", () => {
    const resource = resources[0]!;
    const label = ontologyInstanceResourceOptionLabel(resource, "Unnamed Resource");
    const options = ontologyInstanceResourceAutocompleteOptions(resources, "Unnamed Resource");

    expect(resolveOntologyInstanceAutocomplete(options, label)).toBe(resource.id);
  });

  it("adds identity only when duplicate display labels need disambiguation", () => {
    const duplicate = { ...resources[0]!, id: "duplicate" };
    const label = ontologyInstanceResourceOptionLabel(resources[0]!, "Unnamed Resource");
    const options = ontologyInstanceResourceAutocompleteOptions(
      [...resources, duplicate],
      "Unnamed Resource",
    );

    expect(options.filter((option) => option.value.startsWith(`${label} - `)))
      .toHaveLength(2);
    expect(resolveOntologyInstanceAutocomplete(options, `${label} - ${duplicate.id}`))
      .toBe(duplicate.id);
    expect(resolveOntologyInstanceAutocomplete(options, label)).toBeNull();
    expect(resolveOntologyInstanceAutocomplete(options, "cor")).toBeNull();
  });

  it("returns at most ten case-insensitive matching suggestions", () => {
    const options = Array.from({ length: 12 }, (_, index) => ({
      resourceId: `resource-${index}`,
      value: `Shared Resource ${index}`,
      primary: `Shared Resource ${index}`,
      secondary: "service.shared-resource",
      kind: "RES",
    }));

    expect(ontologyInstanceAutocompleteSuggestions(options, "RESOURCE")).toEqual(options.slice(0, 10));
    expect(ontologyInstanceAutocompleteSuggestions(options, "  shared  ")).toEqual(options.slice(0, 10));
    expect(ontologyInstanceAutocompleteSuggestions(options, "missing")).toEqual([]);
    expect(ontologyInstanceAutocompleteSuggestions(options, "   ")).toEqual([]);
  });
});
