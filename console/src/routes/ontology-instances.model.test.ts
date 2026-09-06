import { describe, expect, it } from "vitest";
import {
  decodeOntologyInstanceDirectory,
  decodeOntologyInstanceExploration,
  groupOntologyInstanceRelationships,
  isOntologyInstanceDirectoryResource,
  isOntologyInstancePresentationRoot,
  isMatchableOntologyInstanceQuery,
  ontologyInstanceAutocompleteSuggestions,
  ontologyInstanceAksLanes,
  ontologyInstanceContextIdentity,
  ontologyInstanceNetworkPaths,
  ontologyInstanceNodeState,
  ontologyInstancePresentationCoverage,
  ontologyInstancePresentationLinks,
  ontologyInstanceResourceAutocompleteOptions,
  ontologyInstanceResourceOptionLabel,
  ontologyInstanceStatusTone,
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
      { source: "kubernetes_runtime_inventory", status: "unavailable", observed_at: null, reason: "kubernetes_source_unconfigured" },
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
    expect(decoded.relationship_coverage).toBeNull();
    expect(decoded.resources[0]?.capacity).toBeNull();
    expect(decoded.resources[0]?.model_deployment).toBeNull();
  });

  it("accepts bounded model deployment details", () => {
    const value = payload();
    const resources = value.resources as Record<string, unknown>[];
    resources[1]!.resource_type = "llm-model-deployment";
    resources[1]!.model_deployment = {
      model_name: "gpt-5.4",
      model_version: "2026-08-01",
      sku_name: "GlobalStandard",
      capacity_tpm: 50_000,
    };

    expect(decodeOntologyInstanceExploration(value).resources[1]?.model_deployment).toEqual(
      resources[1]!.model_deployment,
    );
  });

  it.each([-1, true, 1.5, 2_147_483_648])(
    "rejects invalid model deployment TPM %s",
    (capacityTpm) => {
      const value = payload();
      const resources = value.resources as Record<string, unknown>[];
      resources[1]!.resource_type = "llm-model-deployment";
      resources[1]!.model_deployment = {
        model_name: "gpt-5.4",
        model_version: "2026-08-01",
        sku_name: "GlobalStandard",
        capacity_tpm: capacityTpm,
      };

      expect(() => decodeOntologyInstanceExploration(value)).toThrow();
    },
  );

  it("rejects model deployment details on another Resource type", () => {
    const value = payload();
    const resources = value.resources as Record<string, unknown>[];
    resources[1]!.model_deployment = {
      model_name: "gpt-5.4",
      model_version: null,
      sku_name: null,
      capacity_tpm: null,
    };

    expect(() => decodeOntologyInstanceExploration(value)).toThrow(
      "model deployment details MUST use the llm-model-deployment Resource type",
    );
  });

  it("accepts an observed scalable-resource capacity", () => {
    const value = payload();
    const resources = value.resources as Record<string, unknown>[];
    resources[1]!.resource_type = "kubernetes-node-pool";
    resources[1]!.capacity = 2;

    expect(decodeOntologyInstanceExploration(value).resources[1]?.capacity).toBe(2);

    resources[1]!.capacity = -1;
    expect(() => decodeOntologyInstanceExploration(value)).toThrow(
      "Resource capacity MUST be a non-negative integer",
    );

    resources[1]!.resource_type = "compute.container-app-environment";
    resources[1]!.capacity = 2;
    expect(() => decodeOntologyInstanceExploration(value)).toThrow(
      "Resource capacity MUST use a supported scalable Resource type",
    );
  });

  describe("ontology instance status tone", () => {
    it.each([
      ["Stopped", "warning"],
      ["PowerState/deallocated", "warning"],
      ["Failed", "danger"],
      ["NotReady", "danger"],
      ["NotAvailable", "danger"],
      ["not-healthy", "danger"],
      ["NotActive", "warning"],
      ["Running", "success"],
      ["Succeeded", "success"],
      ["Unknown", "neutral"],
      [null, "neutral"],
    ] as const)("maps %s without rewriting the provider state", (status, expected) => {
      expect(ontologyInstanceStatusTone(status)).toBe(expected);
    });
  });

  describe("ontology instance node state", () => {
    const fact = (value: string | null, reason: string | null) => ({
      value,
      source_path: value === null ? null : "properties.state",
      observed_at: null,
      recorded_at: null,
      freshness: "unknown" as const,
      completeness: null,
      conflicts: [],
      reason,
    });
    const resource = (
      operational: ReturnType<typeof fact>,
      provisioning: ReturnType<typeof fact>,
      availability: ReturnType<typeof fact>,
    ) => ({
      ...decodeOntologyInstanceExploration(payload()).resources[0]!,
      states: {
        schema_version: "1.0.0" as const,
        operational,
        provisioning,
        availability,
      },
    });

    it("keeps applicable operational state as the primary graph label", () => {
      expect(ontologyInstanceNodeState(resource(
        fact("Running", null),
        fact("Succeeded", null),
        fact("Available", null),
      ))).toEqual({ axis: "operational", fact: fact("Running", null) });
    });

    it("shows exact availability when operation is not applicable", () => {
      expect(ontologyInstanceNodeState(resource(
        fact(null, "state_not_applicable"),
        fact("Succeeded", null),
        fact("Available", null),
      ))).toEqual({ axis: "availability", fact: fact("Available", null) });
    });

    it("keeps an applicable availability evidence gap ahead of provisioning", () => {
      expect(ontologyInstanceNodeState(resource(
        fact(null, "state_not_applicable"),
        fact("Succeeded", null),
        fact(null, "state_source_not_recorded"),
      ))).toEqual({
        axis: "availability",
        fact: fact(null, "state_source_not_recorded"),
      });
    });

    it("shows provisioning without recasting it as operation or health", () => {
      expect(ontologyInstanceNodeState(resource(
        fact(null, "state_not_applicable"),
        fact("Succeeded", null),
        fact(null, "state_not_applicable"),
      ))).toEqual({ axis: "provisioning", fact: fact("Succeeded", null) });
    });

    it("keeps an applicable operational evidence gap ahead of provisioning", () => {
      expect(ontologyInstanceNodeState(resource(
        fact(null, "provider_operational_state_not_exposed"),
        fact("Succeeded", null),
        fact(null, "state_not_recorded"),
      ))).toEqual({
        axis: "operational",
        fact: fact(null, "provider_operational_state_not_exposed"),
      });
    });

    it("keeps not-applicable operation when no other axis has a useful fact", () => {
      expect(ontologyInstanceNodeState(resource(
        fact(null, "state_not_applicable"),
        fact(null, "state_not_recorded"),
        fact(null, "state_not_recorded"),
      ))).toEqual({
        axis: "operational",
        fact: fact(null, "state_not_applicable"),
      });
    });
  });

  it("accepts additive relationship candidate accounting", () => {
    const value = payload();
    value.schema_version = "1.4.0";
    value.relationship_coverage = {
      total_candidates: 12,
      materialized: 9,
      reviewed_unavailable: 3,
      unclassified: 0,
      complete: true,
    };

    expect(decodeOntologyInstanceExploration(value).relationship_coverage).toEqual(
      value.relationship_coverage,
    );
  });

  it("rejects incomplete or contradictory relationship candidate accounting", () => {
    const value = payload();
    value.schema_version = "1.4.0";
    value.relationship_coverage = {
      total_candidates: 12,
      materialized: 9,
      reviewed_unavailable: 2,
      unclassified: 0,
      complete: true,
    };
    expect(() => decodeOntologyInstanceExploration(value)).toThrow(
      "relationship coverage counts MUST account for every candidate",
    );

    (value.relationship_coverage as Record<string, unknown>).total_candidates = 12;
    (value.relationship_coverage as Record<string, unknown>).unclassified = 1;
    expect(() => decodeOntologyInstanceExploration(value)).toThrow(
      "complete relationship coverage MUST NOT contain unclassified candidates",
    );
  });

  it("requires an opaque selection token for complete context identity", () => {
    const value = payload();
    value.principal_id = "operator-1";
    value.principal_scope_digest = `sha256:${"b".repeat(64)}`;
    value.selection_digest = `sha256:${"c".repeat(64)}`;
    expect(() => decodeOntologyInstanceExploration(value)).toThrow(
      "instance context identity is incomplete or invalid",
    );
    value.context_capability = { selection_token: "context-selection:" + "a".repeat(32) };
    expect(decodeOntologyInstanceExploration(value).selection_token).toBe(
      "context-selection:" + "a".repeat(32),
    );
  });

  it("accepts a legacy response before Kubernetes source state was additive", () => {
    const value = payload();
    value.sources = (value.sources as Record<string, unknown>[]).filter(
      (source) => source.source !== "kubernetes_runtime_inventory",
    );

    const decoded = decodeOntologyInstanceExploration(value);

    expect(decoded.sources.some((source) =>
      source.source === "kubernetes_runtime_inventory")).toBe(false);
  });

  it("accepts an independently verified Kubernetes provider identity bridge", () => {
    const value = payload();
    value.link_types = ["kubernetes_backed_by"];
    const links = value.links as Record<string, unknown>[];
    links[0] = {
      ...links[0],
      link_type: "kubernetes_backed_by",
      evidence: {
        ...relationshipEvidence(),
        evidence_kind: "observation",
        verification_status: "independently_verified",
        source: "kubernetes-api-inventory",
        source_property_path: "provider_resource_ref",
        mapping_id: "kubernetes.node-backed-by-vmss-vm",
      },
    };

    const decoded = decodeOntologyInstanceExploration(value);

    expect(decoded.links[0]?.link_type).toBe("kubernetes_backed_by");
    expect(decoded.links[0]?.evidence.verification_status).toBe("independently_verified");
  });

  it("keeps absent AKS runtime hops unavailable instead of inferring nodes or pods", () => {
    const value = payload();
    const resources = value.resources as Record<string, unknown>[];
    resources[0] = { ...resources[0], resource_type: "kubernetes-cluster" };

    const lanes = ontologyInstanceAksLanes(decodeOntologyInstanceExploration(value));

    expect(lanes?.find((lane) => lane.id === "runtime")?.steps).toEqual([
      { id: "agentPool", status: "unknown" },
      { id: "node", status: "unavailable" },
      { id: "pod", status: "unavailable" },
    ]);
    expect(lanes?.find((lane) => lane.id === "service")?.steps.every(
      (step) => step.status === "unavailable",
    )).toBe(true);
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

  it("preserves stale configuration evidence without marking it complete", () => {
    const value = payload();
    const links = value.links as Record<string, unknown>[];
    links[0]!.evidence = {
      ...relationshipEvidence(),
      status: "stale",
      verification_status: "configuration_observed",
      complete: false,
      reason: "relationship_evidence_stale",
    };

    const decoded = decodeOntologyInstanceExploration(value);

    expect(decoded.links[0]?.evidence).toMatchObject({
      status: "stale",
      verification_status: "configuration_observed",
      complete: false,
      reason: "relationship_evidence_stale",
    });
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

  it("keeps observed runtime calls in a first-class runtime group", () => {
    const runtimeCall = relationship(
      "root",
      "dependency",
      "runtime_calls",
      "runtime.telemetry-call",
    );

    expect(groupOntologyInstanceRelationships([runtimeCall], "root")).toMatchObject({
      runtimeCalls: [runtimeCall],
      directOutgoing: [],
    });
  });
});

describe("ontologyInstanceNetworkPaths", () => {
  it("orders one current VM NAT egress path and keeps absent ingress unknown", () => {
    const data = vmNetworkPayload();
    data.complete = false;
    data.relationship_drop_reasons = ["missing_target_endpoint"];

    const paths = ontologyInstanceNetworkPaths(decodeOntologyInstanceExploration(data));

    expect(paths?.egress).toMatchObject({
      status: "current",
      kind: "nat_gateway",
      reason: null,
    });
    expect(paths?.egress.links.map((link) => link.evidence.mapping_id)).toEqual([
      "azure.vm-nic-attached-to-vm",
      "azure.nic-attached-to-subnet",
      "azure.subnet-attached-to-nat-gateway",
      "azure.nat-gateway-attached-to-public-ip",
    ]);
    expect(paths?.ingress).toEqual({
      status: "unknown",
      kind: null,
      links: [],
      reason: "coverage_incomplete",
    });
  });

  it("lowers a configured path when one edge is stale", () => {
    const data = vmNetworkPayload();
    const links = data.links as Record<string, unknown>[];
    links[2]!.evidence = {
      ...relationshipEvidence(),
      mapping_id: "azure.subnet-attached-to-nat-gateway",
      status: "stale",
      complete: false,
      reason: "relationship_evidence_stale",
    };

    expect(ontologyInstanceNetworkPaths(decodeOntologyInstanceExploration(data))?.egress.status)
      .toBe("stale");
  });
});

function vmNetworkPayload(): Record<string, unknown> {
  const value = payload();
  value.root_id = "vm";
  value.link_types = ["attached_to"];
  value.resources = [
    networkResource("vm", "compute.vm"),
    networkResource("nic", "network.interface"),
    networkResource("subnet", "network.subnet"),
    networkResource("nat", "network.nat-gateway"),
    networkResource("public-ip", "network.public-ip"),
  ];
  value.links = [
    relationship("nic", "vm", "attached_to", "azure.vm-nic-attached-to-vm"),
    relationship("nic", "subnet", "attached_to", "azure.nic-attached-to-subnet"),
    relationship("subnet", "nat", "attached_to", "azure.subnet-attached-to-nat-gateway"),
    relationship("nat", "public-ip", "attached_to", "azure.nat-gateway-attached-to-public-ip"),
  ];
  return value;
}

function networkResource(id: string, resourceType: string): Record<string, unknown> {
  return {
    id,
    object_type: "Resource",
    resource_type: resourceType,
    name: id,
    location: null,
    resource_group: null,
    status: null,
    last_seen: null,
    selected: id === "vm",
  };
}

function relationshipEvidence(): Record<string, unknown> {
  return {
    status: "available",
    evidence_kind: "configuration",
    verification_status: "configuration_observed",
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
  linkType: "attached_to" | "routes_to" | "runtime_calls",
  mappingId: string,
) {
  return {
    source,
    target,
    link_type: linkType,
    evidence: {
      status: "available" as const,
      evidence_kind: "configuration" as const,
      verification_status: "configuration_observed" as const,
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
  it("shares recorded state facts with instance detail without merging provisioning into operation", () => {
    const value = payload();
    const fact = (state: string | null, source_path: string | null) => ({
      value: state, source_path, observed_at: null, recorded_at: null,
      freshness: "unknown", completeness: null, conflicts: [], reason: "metadata_not_recorded",
    });
    const states = {
      schema_version: "1.0.0",
      operational: fact("Running", "properties.runningStatus"),
      provisioning: fact("Succeeded", "properties.provisioningState"),
      availability: fact(null, null),
    };
    const resources = (value.resources as Record<string, unknown>[]).map((resource) => ({ ...resource, states }));
    const detail = decodeOntologyInstanceExploration({ ...value, resources });
    const directory = decodeOntologyInstanceDirectory({
      schema_version: "1.0.0", ontology_release_digest: value.ontology_release_digest,
      source_generation: value.source_generation, source_cutoff: value.source_cutoff,
      search: null, resources: resources.map((resource) => ({ ...resource, selected: false })),
      complete: true, truncation_reason: null, execution_authority: false, mutation_authority: false,
    });
    expect(directory.resources[0]?.states).toEqual(detail.resources[0]?.states);
    expect(detail.resources[0]?.states?.operational.value).toBe("Running");
    expect(detail.resources[0]?.states?.provisioning.value).toBe("Succeeded");
    expect(detail.resources[0]?.states?.operational.observed_at).toBeNull();
  });

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

  it("excludes role-assignment endpoints from default presentation links", () => {
    const data = decodeOntologyInstanceExploration(payload());
    const role = {
      ...data.resources[1]!,
      id: "role-assignment",
      resource_type: "authorization.role-assignment",
    };
    const roleLink = relationship("role-assignment", "root", "attached_to", "azure.role");

    expect(ontologyInstancePresentationLinks({
      ...data,
      resources: [...data.resources, role],
      links: [...data.links, roleLink],
    })).toEqual(data.links);
  });

  it("accounts for focus, Inspector-only, and IAM-delegated relationships", () => {
    const data = decodeOntologyInstanceExploration(payload());
    const role = {
      ...data.resources[1]!,
      id: "role-assignment",
      resource_type: "authorization.role-assignment",
    };
    const roleLink = relationship("role-assignment", "root", "attached_to", "azure.role");
    const coverage = ontologyInstancePresentationCoverage(
      {
        ...data,
        resources: [...data.resources, role],
        links: [...data.links, roleLink],
      },
      ["root"],
      [],
    );

    expect(coverage).toMatchObject({
      responseResources: 3,
      responseLinks: 2,
      presentationResources: 2,
      presentationLinks: 1,
      graphResources: 1,
      graphLinks: 0,
      inspectorOnlyLinks: 1,
      delegatedResources: 1,
      delegatedLinks: 1,
      graphOmittedResources: 1,
      graphOmittedLinks: 1,
      graphConsistent: true,
    });
  });

  it("rejects a stale graph relationship outside the returned presentation response", () => {
    const data = decodeOntologyInstanceExploration(payload());
    const stale = relationship("root", "stale", "attached_to", "azure.stale");

    expect(ontologyInstancePresentationCoverage(
      data,
      ["root", "stale"],
      [stale],
    ).graphConsistent).toBe(false);
  });

  it("rejects a role assignment as the exact default presentation root", () => {
    const data = decodeOntologyInstanceExploration(payload());
    const root = data.resources[0]!;

    expect(isOntologyInstancePresentationRoot(data)).toBe(true);
    expect(isOntologyInstancePresentationRoot({
      ...data,
      resources: [{ ...root, resource_type: "authorization.role-assignment" }],
    })).toBe(false);
  });

  it("excludes hidden role assignments from the exact screen selection identity", () => {
    const value = payload();
    value.principal_id = "operator-1";
    value.principal_scope_digest = `sha256:${"b".repeat(64)}`;
    value.selection_digest = `sha256:${"c".repeat(64)}`;
    value.context_capability = { selection_token: "context-selection:" + "a".repeat(32) };
    const data = decodeOntologyInstanceExploration(value);
    const role = {
      ...data.resources[1]!,
      id: "role-assignment",
      resource_type: "authorization.role-assignment",
    };

    const identity = ontologyInstanceContextIdentity({
      ...data,
      resources: [...data.resources, role],
    });

    expect(identity?.resourceIds).toEqual(["root", "environment"]);
    expect(identity?.resourceIds).not.toContain("role-assignment");
  });

  it("withholds the selection identity when context identity fields are absent", () => {
    const data = decodeOntologyInstanceExploration(payload());

    expect(ontologyInstanceContextIdentity(data)).toBeUndefined();
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
  });

  it("browses the directory when the operator has typed nothing", () => {
    const options = Array.from({ length: 12 }, (_, index) => ({
      resourceId: `resource-${index}`,
      value: `Shared Resource ${index}`,
      primary: `Shared Resource ${index}`,
      secondary: "service.shared-resource",
      kind: "RES",
    }));

    expect(ontologyInstanceAutocompleteSuggestions(options, "")).toEqual(options.slice(0, 10));
    expect(ontologyInstanceAutocompleteSuggestions(options, "   ")).toEqual(options.slice(0, 10));
    expect(ontologyInstanceAutocompleteSuggestions(options, "", 0)).toEqual([]);
  });

  it("refuses a query the recorded identifiers cannot contain", () => {
    expect(isMatchableOntologyInstanceQuery("aks-fdai-sre-lab-krc")).toBe(true);
    expect(isMatchableOntologyInstanceQuery("")).toBe(true);
    expect(isMatchableOntologyInstanceQuery("쿠버네티스")).toBe(false);
    expect(isMatchableOntologyInstanceQuery("aks 클러스터")).toBe(false);
  });
});
