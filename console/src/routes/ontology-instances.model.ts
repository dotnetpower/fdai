import type { ViewContextIdentity } from "../deck/context";
import { isOperationalResourceType } from "../resource-presentation";
import {
  decodeRecordedResourceStates,
  type RecordedResourceStates,
  type RecordedStateAxis,
  type RecordedStateFact,
} from "../recorded-resource-state";

export interface OntologyInstanceResource {
  readonly id: string;
  readonly object_type: "Resource";
  readonly resource_type: string;
  readonly name: string | null;
  readonly location: string | null;
  readonly resource_group: string | null;
  readonly status: string | null;
  readonly capacity?: number | null;
  readonly last_seen: string | null;
  readonly selected: boolean;
  readonly model_deployment?: OntologyInstanceModelDeployment | null;
  readonly kubernetes_identity?: OntologyInstanceKubernetesIdentity | null;
  readonly kubernetes_diagnostics?: Readonly<Record<string, OntologyInstanceDiagnosticValue>> | null;
  readonly aks_diagnostic_receipt?: OntologyInstanceAksDiagnosticReceipt | null;
  readonly states?: RecordedResourceStates;
}

export interface OntologyInstanceKubernetesIdentity {
  readonly api_version: string;
  readonly kind: string;
  readonly name: string;
  readonly namespace: string | null;
  readonly resource_version: string;
  readonly uid: string;
}

export type OntologyInstanceAksDiagnosticStatus =
  | "autoscale_limited"
  | "control_plane_unavailable"
  | "crash_loop"
  | "endpoint_unready"
  | "evicted"
  | "held"
  | "image_pull_failed"
  | "node_pressure"
  | "networking_unavailable"
  | "no_failure_signal"
  | "oom_killed"
  | "probe_failure_evidence"
  | "quota_constrained"
  | "resource_pressure"
  | "rollout_stalled"
  | "scheduling_blocked"
  | "storage_blocked";

export interface OntologyInstanceAksDiagnosticReceipt {
  readonly schema_version: "1.0.0";
  readonly owner_agent: "Forseti";
  readonly principal_class: string;
  readonly purpose: "operations-review";
  readonly producer_version: string;
  readonly method_version: string;
  readonly target_resource_id: string;
  readonly target_uid: string;
  readonly target_resource_version: string;
  readonly ontology_release: string;
  readonly cutoff: string;
  readonly source_cutoffs: Readonly<Record<string, string>>;
  readonly source_revisions: Readonly<Record<string, string>>;
  readonly status: OntologyInstanceAksDiagnosticStatus;
  readonly signals: readonly OntologyInstanceAksDiagnosticStatus[];
  readonly complete: boolean;
  readonly evidence_gaps: readonly string[];
  readonly conflicts: readonly string[];
  readonly evidence_refs: readonly string[];
  readonly synthetic: false;
  readonly cause_claim_supported: false;
  readonly execution_authority: false;
  readonly audit_correlation_id: string;
}

export type OntologyInstanceDiagnosticValue =
  | string
  | number
  | boolean
  | null
  | readonly OntologyInstanceDiagnosticValue[]
  | OntologyInstanceDiagnosticObject;

export interface OntologyInstanceDiagnosticObject {
  readonly [key: string]: OntologyInstanceDiagnosticValue;
}

export interface OntologyInstanceModelDeployment {
  readonly model_name: string | null;
  readonly model_version: string | null;
  readonly sku_name: string | null;
  readonly capacity_tpm: number | null;
}

export type OntologyInstanceStatusTone = "neutral" | "success" | "warning" | "danger";
export type OntologyInstanceCapacityKind = "node" | "instance";
export interface OntologyInstanceNodeState {
  readonly axis: RecordedStateAxis;
  readonly fact: RecordedStateFact;
}

/** Names the only scalable Resource types whose provider capacity is projected. */
export function ontologyInstanceCapacityKind(
  resourceType: string,
): OntologyInstanceCapacityKind | null {
  if (resourceType === "kubernetes-node-pool") return "node";
  if (resourceType === "compute.vm-scale-set") return "instance";
  return null;
}

/** Maps exact provider state text to presentation tone without changing the state value. */
export function ontologyInstanceStatusTone(status: string | null): OntologyInstanceStatusTone {
  const normalized = status?.trim().toLowerCase() ?? "";
  const compact = normalized.replace(/[^a-z0-9]/g, "");
  if (!normalized || normalized.includes("unknown")) return "neutral";
  if (["notready", "notavailable", "nothealthy"].some((value) =>
    compact.includes(value))) return "danger";
  if (["notactive", "notrunning", "notsucceeded"].some((value) =>
    compact.includes(value))) return "warning";
  if ([
    "failed",
    "error",
    "unhealthy",
    "notready",
    "not ready",
    "canceled",
    "cancelled",
  ].some((value) => normalized.includes(value))) return "danger";
  if ([
    "stopped",
    "stopping",
    "deallocated",
    "disabled",
    "inactive",
    "paused",
    "unavailable",
  ].some((value) => normalized.includes(value))) return "warning";
  if ([
    "running",
    "ready",
    "succeeded",
    "active",
    "healthy",
    "available",
  ].some((value) => normalized.includes(value))) return "success";
  return "neutral";
}

/** Selects the most relevant recorded axis for a compact graph label without merging facts. */
export function ontologyInstanceNodeState(
  resource: OntologyInstanceResource,
): OntologyInstanceNodeState | null {
  const states = resource.states;
  if (states === undefined) return null;
  if (states.operational.value !== null) {
    return { axis: "operational", fact: states.operational };
  }
  const operationCanFallBack = states.operational.reason === "state_not_applicable"
    || states.operational.reason === "provider_operational_state_not_exposed";
  if (!operationCanFallBack) {
    return { axis: "operational", fact: states.operational };
  }
  if (states.availability.value !== null) {
    return { axis: "availability", fact: states.availability };
  }
  if (
    states.availability.reason !== null
    && states.availability.reason !== "state_not_recorded"
    && states.availability.reason !== "state_not_applicable"
  ) {
    return { axis: "availability", fact: states.availability };
  }
  if (states.provisioning.value !== null) {
    return { axis: "provisioning", fact: states.provisioning };
  }
  return { axis: "operational", fact: states.operational };
}

/** Returns whether a Resource is meaningful as an operator-selected graph root. */
export function isOntologyInstanceDirectoryResource(
  resource: OntologyInstanceResource,
): boolean {
  return isOntologyInstancePresentationResource(resource);
}

/** Returns whether a Resource belongs on the default operational instance surface. */
export function isOntologyInstancePresentationResource(
  resource: OntologyInstanceResource,
): boolean {
  return isOperationalResourceType(resource.resource_type);
}

/** Omits hidden Resource endpoints without changing the authoritative response. */
export function ontologyInstancePresentationLinks(
  data: OntologyInstanceExploration,
): readonly OntologyInstanceLink[] {
  const visibleIds = new Set(
    data.resources.filter(isOntologyInstancePresentationResource).map((resource) => resource.id),
  );
  return data.links.filter((link) => visibleIds.has(link.source) && visibleIds.has(link.target));
}

/** Returns whether the exact exploration root belongs on the default instance surface. */
export function isOntologyInstancePresentationRoot(
  data: OntologyInstanceExploration,
): boolean {
  const root = data.resources.find((resource) => resource.id === data.root_id);
  return root !== undefined && isOntologyInstancePresentationResource(root);
}

/** Formats the stable operator-facing value used by the Resource autocomplete. */
export function ontologyInstanceResourceOptionLabel(
  resource: OntologyInstanceResource,
  unnamedLabel: string,
): string {
  return `${resource.name ?? unnamedLabel} - ${resource.resource_type}`;
}

export interface OntologyInstanceAutocompleteOption {
  readonly resourceId: string;
  readonly value: string;
  readonly primary: string;
  readonly secondary: string;
  readonly kind: string;
}

export const ONTOLOGY_INSTANCE_AUTOCOMPLETE_LIMIT = 10;

/** Builds unique autocomplete values without lengthening labels that are already distinct. */
export function ontologyInstanceResourceAutocompleteOptions(
  resources: readonly OntologyInstanceResource[],
  unnamedLabel: string,
): readonly OntologyInstanceAutocompleteOption[] {
  const labels = resources.map((resource) =>
    ontologyInstanceResourceOptionLabel(resource, unnamedLabel));
  const counts = new Map<string, number>();
  for (const label of labels) {
    const normalized = label.toLowerCase();
    counts.set(normalized, (counts.get(normalized) ?? 0) + 1);
  }
  return resources.map((resource, index) => {
    const label = labels[index]!;
    return {
      resourceId: resource.id,
      value: counts.get(label.toLowerCase()) === 1 ? label : `${label} - ${resource.id}`,
      primary: resource.name ?? unnamedLabel,
      secondary: resource.resource_type,
      kind: resource.resource_type.split(/[./-]/).filter(Boolean).at(-1)?.slice(0, 3).toUpperCase()
        ?? "RES",
    };
  });
}

/** Resolves only an exact autocomplete value. */
export function resolveOntologyInstanceAutocomplete(
  options: readonly OntologyInstanceAutocompleteOption[],
  value: string,
): string | null {
  const normalized = value.trim().toLowerCase();
  if (!normalized) return null;
  return options.find((option) => option.value.toLowerCase() === normalized)?.resourceId ?? null;
}

/** Returns the bounded autocomplete choices whose labels contain the operator query. */
export function ontologyInstanceAutocompleteSuggestions(
  options: readonly OntologyInstanceAutocompleteOption[],
  query: string,
  limit = ONTOLOGY_INSTANCE_AUTOCOMPLETE_LIMIT,
): readonly OntologyInstanceAutocompleteOption[] {
  const normalized = query.trim().toLowerCase();
  if (limit <= 0) return [];
  // An empty query browses the directory: it is the only entry point without a selector.
  if (!normalized) return options.slice(0, limit);
  return options
    .filter((option) => option.value.toLowerCase().includes(normalized))
    .slice(0, limit);
}

/**
 * Returns whether the directory can match this query at all.
 *
 * Resource names, types, and identifiers are ASCII, so a query outside that range
 * cannot match any Resource and an empty result would misread as an absent Resource.
 */
export function isMatchableOntologyInstanceQuery(query: string): boolean {
  return !/[^\u0020-\u007e]/.test(query);
}

export interface OntologyInstanceLink {
  readonly source: string;
  readonly target: string;
  readonly link_type:
    | "contains"
    | "attached_to"
    | "depends_on"
    | "routes_to"
    | "runtime_calls"
    | "peered_with"
    | "kubernetes_backed_by"
    | "kubernetes_exposes_endpoint_slice"
    | "kubernetes_exposes_endpoints"
    | "kubernetes_owned_by"
    | "kubernetes_scheduled_on"
    | "kubernetes_selects";
  readonly evidence: OntologyInstanceRelationshipEvidence;
}

export interface OntologyInstanceRelationshipEvidence {
  readonly status: "available" | "stale" | "unavailable";
  readonly evidence_kind: "configuration" | "observation" | null;
  readonly verification_status: "configuration_observed" | "independently_verified" | "unavailable";
  readonly source: string | null;
  readonly source_property_path: string | null;
  readonly mapping_id: string | null;
  readonly evidence_method: string | null;
  readonly cutoff: string | null;
  readonly freshness_ceiling_seconds: number | null;
  readonly complete: boolean;
  readonly reason: string | null;
}

export interface OntologyInstanceActivity {
  readonly sequence: number;
  readonly action_kind: string;
  readonly actor: string;
  readonly recorded_at: string;
  readonly correlation_id: string | null;
  readonly facts: Readonly<Record<string, string>>;
  readonly evidence_ref: string;
}

export interface OntologyInstanceSource {
  readonly source: string;
  readonly scope_digest: string | null;
  readonly status: "available" | "unavailable";
  readonly observed_at: string | null;
  readonly reason: string | null;
}

export interface OntologyRelationshipDropClassification {
  readonly reason: string;
  readonly mapping_id: string;
  readonly source_property_path: string;
  readonly source_provider_type: string;
  readonly target_provider_type: string;
  readonly unavailable_reason:
    | "reference_not_observed"
    | "source_outside_active_generation"
    | "target_outside_active_generation"
    | "target_provider_type_unmodeled"
    | "authorization_child_scope_unmodeled"
    | "unclassified";
  readonly count: number;
}

export interface OntologyInstanceRelationshipCoverage {
  readonly total_candidates: number;
  readonly materialized: number;
  readonly reviewed_unavailable: number;
  readonly unclassified: number;
  readonly complete: boolean;
}

export interface OntologyInstanceProviderTypeCount {
  readonly provider_type: string;
  readonly count: number;
}

export interface OntologyInstanceProviderScopeCoverage {
  readonly capture_method: string;
  readonly provider_object_count: number;
  readonly mapped_provider_object_count: number;
  readonly unmapped_provider_object_count: number;
  readonly materialized_unmapped_provider_object_count: number;
  readonly provider_identity_complete: boolean;
  readonly provider_type_count: number;
  readonly unmapped_provider_type_count: number;
  readonly unmapped_provider_types: readonly OntologyInstanceProviderTypeCount[];
}

export interface OntologyInstanceExploration {
  readonly schema_version: "1.3.0" | "1.4.0";
  readonly ontology_release_digest: string;
  readonly source_generation: string;
  readonly principal_id?: string;
  readonly principal_scope_digest?: string;
  readonly selection_digest?: string;
  readonly selection_token?: string;
  readonly context_capability?: {
    readonly selection_token: string;
  };
  readonly source_cutoff: string;
  readonly root_id: string;
  readonly depth: number;
  readonly link_types: readonly string[];
  readonly resources: readonly OntologyInstanceResource[];
  readonly links: readonly OntologyInstanceLink[];
  readonly timeline: {
    readonly items: readonly OntologyInstanceActivity[];
    readonly complete: boolean;
    readonly truncation_reason: "activity_limit" | null;
  };
  readonly sources: readonly OntologyInstanceSource[];
  readonly relationship_drop_reasons: readonly string[];
  readonly relationship_drop_classifications: readonly OntologyRelationshipDropClassification[];
  readonly relationship_coverage?: OntologyInstanceRelationshipCoverage | null;
  readonly provider_scope_coverage?: OntologyInstanceProviderScopeCoverage | null;
  readonly complete: boolean;
  readonly truncation_reasons: readonly (
    "adjacent_edge_limit" | "resource_limit" | "link_limit" | "activity_limit"
  )[];
  readonly execution_authority: false;
  readonly mutation_authority: false;
}

export interface OntologyInstancePresentationCoverage {
  readonly responseResources: number;
  readonly responseLinks: number;
  readonly presentationResources: number;
  readonly presentationLinks: number;
  readonly graphResources: number;
  readonly graphLinks: number;
  readonly inspectorOnlyLinks: number;
  readonly delegatedResources: number;
  readonly delegatedLinks: number;
  readonly graphOmittedResources: number;
  readonly graphOmittedLinks: number;
  readonly graphConsistent: boolean;
}

/** Accounts for every returned item without treating focus-graph omission as source loss. */
export function ontologyInstancePresentationCoverage(
  data: OntologyInstanceExploration,
  graphResourceIds: readonly string[],
  graphLinks: readonly OntologyInstanceLink[],
): OntologyInstancePresentationCoverage {
  const presentationResources = data.resources.filter(isOntologyInstancePresentationResource);
  const presentationLinks = ontologyInstancePresentationLinks(data);
  const presentationResourceIds = new Set(presentationResources.map((resource) => resource.id));
  const graphResourceSet = new Set(graphResourceIds);
  const graphResources = [...graphResourceSet].filter((id) =>
    presentationResourceIds.has(id)).length;
  const unexpectedGraphResources = [...graphResourceSet].some((id) =>
    !presentationResourceIds.has(id));
  const presentationLinkKeys = new Set(presentationLinks.map(ontologyInstanceLinkKey));
  const graphLinkKeys = new Set(graphLinks.map(ontologyInstanceLinkKey));
  const displayedGraphLinks = [...graphLinkKeys].filter((key) =>
    presentationLinkKeys.has(key)).length;
  const unexpectedGraphLinks = [...graphLinkKeys].some((key) =>
    !presentationLinkKeys.has(key));
  const delegatedResources = data.resources.length - presentationResources.length;
  const delegatedLinks = data.links.length - presentationLinks.length;
  const inspectorOnlyLinks = presentationLinks.length - displayedGraphLinks;
  return {
    responseResources: data.resources.length,
    responseLinks: data.links.length,
    presentationResources: presentationResources.length,
    presentationLinks: presentationLinks.length,
    graphResources,
    graphLinks: displayedGraphLinks,
    inspectorOnlyLinks,
    delegatedResources,
    delegatedLinks,
    graphOmittedResources: presentationResources.length - graphResources,
    graphOmittedLinks: inspectorOnlyLinks,
    graphConsistent: !unexpectedGraphResources
      && !unexpectedGraphLinks
      && graphLinkKeys.size === graphLinks.length,
  };
}

function ontologyInstanceLinkKey(link: OntologyInstanceLink): string {
  return `${link.source}\u0000${link.link_type}\u0000${link.target}`;
}

/**
 * Server-verifiable selection identity for a resolved exploration, scoped to
 * exactly the Resources the operator sees rendered on this screen.
 *
 * Hidden directory-only endpoints (e.g. `authorization.role-assignment`)
 * never reach the graph, legend, or inspector, so they MUST NOT count toward
 * the exact screen selection either - counting them would let an invisible
 * Resource make an otherwise-empty selection look bound.
 */
export function ontologyInstanceContextIdentity(
  data: OntologyInstanceExploration,
): ViewContextIdentity | undefined {
  if (
    !data.complete ||
    !data.principal_id ||
    !data.principal_scope_digest ||
    !data.selection_digest ||
    !data.selection_token
  ) {
    return undefined;
  }
  return {
    kind: "screen",
    screenId: "ontology-instances",
    resourceIds: data.resources
      .filter(isOntologyInstancePresentationResource)
      .map((resource) => resource.id),
    selectionToken: data.selection_token,
    principalId: data.principal_id,
    principalScopeDigest: data.principal_scope_digest,
    ontologyReleaseDigest: data.ontology_release_digest,
    sourceGeneration: data.source_generation,
    selectionDigest: data.selection_digest,
    complete: true,
  };
}

export interface OntologyInstanceDirectory {
  readonly schema_version: "1.0.0";
  readonly ontology_release_digest: string;
  readonly source_generation: string;
  readonly source_cutoff: string;
  readonly search: string | null;
  readonly resources: readonly OntologyInstanceResource[];
  readonly complete: boolean;
  readonly truncation_reason: "resource_limit" | null;
  readonly execution_authority: false;
  readonly mutation_authority: false;
}

export type OntologyInstanceTrafficDirection = "ingress" | "egress";

export interface OntologyInstanceRelationshipGroups {
  readonly directIncoming: readonly OntologyInstanceLink[];
  readonly directOutgoing: readonly OntologyInstanceLink[];
  readonly verifiedIngress: readonly OntologyInstanceLink[];
  readonly verifiedEgress: readonly OntologyInstanceLink[];
  readonly runtimeCalls: readonly OntologyInstanceLink[];
  readonly accessContext: readonly OntologyInstanceLink[];
  readonly containmentContext: readonly OntologyInstanceLink[];
  readonly path: readonly OntologyInstanceLink[];
}

export type OntologyInstanceNetworkPathStatus = "current" | "stale" | "unknown";

export interface OntologyInstanceNetworkPath {
  readonly status: OntologyInstanceNetworkPathStatus;
  readonly kind: "frontend_ingress" | "direct_public_ip" | "nat_gateway" | null;
  readonly links: readonly OntologyInstanceLink[];
  readonly reason: "coverage_incomplete" | "no_reviewed_path" | null;
}

export interface OntologyInstanceNetworkPaths {
  readonly ingress: OntologyInstanceNetworkPath;
  readonly egress: OntologyInstanceNetworkPath;
}

export type OntologyInstancePathStepStatus = "observed" | "unknown" | "unavailable";

export interface OntologyInstancePathStep {
  readonly id: string;
  readonly status: OntologyInstancePathStepStatus;
}

export interface OntologyInstanceAksLane {
  readonly id: "ingress" | "infrastructure" | "runtime" | "service";
  readonly steps: readonly OntologyInstancePathStep[];
}

/** Summarizes only stored AKS path evidence and explicit source unavailability. */
export function ontologyInstanceAksLanes(
  data: OntologyInstanceExploration,
): readonly OntologyInstanceAksLane[] | null {
  const resources = new Map(data.resources.map((resource) => [resource.id, resource]));
  if (resources.get(data.root_id)?.resource_type !== "kubernetes-cluster") return null;
  const mapped = (mappingId: string): readonly OntologyInstanceLink[] => data.links.filter(
    (link) => link.evidence.mapping_id === mappingId,
  );
  const kubernetesUnavailable = data.sources.some((source) =>
    source.source === "kubernetes_runtime_inventory" && source.status === "unavailable");
  const infrastructureStatus = (observed: boolean): OntologyInstancePathStepStatus =>
    observed ? "observed" : "unknown";
  const runtimeStatus = (observed: boolean): OntologyInstancePathStepStatus =>
    observed ? "observed" : kubernetesUnavailable ? "unavailable" : "unknown";

  const managedGroupIds = new Set(mapped("azure.aks-attached-to-node-resource-group")
    .filter((link) => link.source === data.root_id)
    .map((link) => link.target));
  const vmssIds = new Set(data.links
    .filter((link) => link.link_type === "contains" && managedGroupIds.has(link.source)
      && resources.get(link.target)?.resource_type === "compute.vm-scale-set")
    .map((link) => link.target));
  const vmIds = new Set(mapped("azure.vm-scale-set-contains-vm")
    .filter((link) => vmssIds.has(link.source))
    .map((link) => link.target));
  const nicIds = new Set(mapped("azure.vm-scale-set-nic-attached-to-vm")
    .filter((link) => vmIds.has(link.target))
    .map((link) => link.source));
  const agentPoolIds = new Set(mapped("azure.aks-contains-agent-pool")
    .filter((link) => link.source === data.root_id)
    .map((link) => link.target));
  const nodeIds = new Set(mapped("kubernetes.agent-pool-contains-node")
    .filter((link) => agentPoolIds.has(link.source))
    .map((link) => link.target));
  const scheduledPodIds = new Set(mapped("kubernetes.pod-scheduled-on-node")
    .filter((link) => nodeIds.has(link.target))
    .map((link) => link.source));
  const serviceLinks = data.links.filter((link) =>
    link.link_type === "kubernetes_selects"
    || link.link_type === "kubernetes_exposes_endpoints"
    || link.link_type === "kubernetes_exposes_endpoint_slice");
  const serviceIds = new Set(serviceLinks.map((link) => link.source));
  const selectedPodIds = new Set(serviceLinks
    .filter((link) => link.link_type === "kubernetes_selects")
    .map((link) => link.target));
  const endpointIds = new Set(serviceLinks
    .filter((link) => link.link_type !== "kubernetes_selects")
    .map((link) => link.target));
  const ingressObserved = data.links.some((link) =>
    link.link_type === "routes_to"
    && (resources.get(link.source)?.resource_type === "kubernetes.ingress"
      || link.evidence.mapping_id === "azure.application-gateway-routes-to-configured-backend"
      || link.evidence.mapping_id === "azure.load-balancer-routes-to-configured-backend")
    && (link.target === data.root_id || serviceIds.has(link.target)));

  return [
    {
      id: "ingress",
      steps: [
        { id: "frontend", status: infrastructureStatus(ingressObserved) },
        { id: "aksOrService", status: "observed" },
      ],
    },
    {
      id: "infrastructure",
      steps: [
        { id: "managedGroup", status: infrastructureStatus(managedGroupIds.size > 0) },
        { id: "vmss", status: infrastructureStatus(vmssIds.size > 0) },
        { id: "vm", status: infrastructureStatus(vmIds.size > 0) },
        { id: "nic", status: infrastructureStatus(nicIds.size > 0) },
      ],
    },
    {
      id: "runtime",
      steps: [
        { id: "agentPool", status: infrastructureStatus(agentPoolIds.size > 0) },
        { id: "node", status: runtimeStatus(nodeIds.size > 0) },
        { id: "pod", status: runtimeStatus(scheduledPodIds.size > 0) },
      ],
    },
    {
      id: "service",
      steps: [
        { id: "service", status: runtimeStatus(serviceIds.size > 0) },
        { id: "pod", status: runtimeStatus(selectedPodIds.size > 0) },
        { id: "endpoint", status: runtimeStatus(endpointIds.size > 0) },
      ],
    },
  ];
}

const VERIFIED_BACKEND_TRAFFIC_MAPPINGS = new Set([
  "azure.application-gateway-routes-to-configured-backend",
  "azure.load-balancer-routes-to-configured-backend",
]);
const VERIFIED_EGRESS_TRAFFIC_MAPPINGS = new Set([
  ...VERIFIED_BACKEND_TRAFFIC_MAPPINGS,
  "azure.aks-routes-to-effective-outbound-ip",
]);
const VM_NIC_MAPPING = "azure.vm-nic-attached-to-vm";
const NIC_SUBNET_MAPPING = "azure.nic-attached-to-subnet";
const NIC_PUBLIC_IP_MAPPING = "azure.nic-attached-to-public-ip";
const SUBNET_NAT_MAPPING = "azure.subnet-attached-to-nat-gateway";
const NAT_PUBLIC_IP_MAPPING = "azure.nat-gateway-attached-to-public-ip";

/** Summarizes only evidence-backed VM ingress and egress paths present in one bounded response. */
export function ontologyInstanceNetworkPaths(
  data: OntologyInstanceExploration,
): OntologyInstanceNetworkPaths | null {
  const resources = new Map(data.resources.map((resource) => [resource.id, resource]));
  if (resources.get(data.root_id)?.resource_type !== "compute.vm") return null;
  const mapped = (mappingId: string): readonly OntologyInstanceLink[] => data.links
    .filter((link) => link.evidence.mapping_id === mappingId)
    .sort(compareNetworkPathLink);
  const vmNics = mapped(VM_NIC_MAPPING).filter((link) => link.target === data.root_id);
  const nicIds = new Set(vmNics.map((link) => link.source));
  const nicSubnets = mapped(NIC_SUBNET_MAPPING).filter((link) => nicIds.has(link.source));
  const subnetIds = new Set(nicSubnets.map((link) => link.target));
  const localIds = new Set([data.root_id, ...nicIds, ...subnetIds]);

  const frontendIngress = data.links
    .filter((link) => link.link_type === "routes_to"
      && VERIFIED_BACKEND_TRAFFIC_MAPPINGS.has(link.evidence.mapping_id ?? "")
      && localIds.has(link.target))
    .sort(compareNetworkPathLink)[0];
  const directPublicIp = mapped(NIC_PUBLIC_IP_MAPPING)
    .find((link) => nicIds.has(link.source));
  const ingressLinks = frontendIngress
    ? [frontendIngress, ...linksFromEndpointToVm(frontendIngress.target, vmNics, nicSubnets)]
    : directPublicIp
      ? [directPublicIp, ...vmNics.filter((link) => link.source === directPublicIp.source)]
      : [];

  let egressLinks: readonly OntologyInstanceLink[] = [];
  for (const vmNic of vmNics) {
    const nicSubnet = nicSubnets.find((link) => link.source === vmNic.source);
    if (!nicSubnet) continue;
    const subnetNat = mapped(SUBNET_NAT_MAPPING)
      .find((link) => link.source === nicSubnet.target);
    if (!subnetNat) continue;
    const natPublicIp = mapped(NAT_PUBLIC_IP_MAPPING)
      .find((link) => link.source === subnetNat.target);
    if (!natPublicIp) continue;
    egressLinks = [vmNic, nicSubnet, subnetNat, natPublicIp];
    break;
  }

  const coverageIncomplete = data.relationship_drop_reasons.length > 0
    || data.truncation_reasons.some((reason) => reason !== "activity_limit");
  return {
    ingress: networkPath(
      ingressLinks,
      frontendIngress ? "frontend_ingress" : directPublicIp ? "direct_public_ip" : null,
      coverageIncomplete,
    ),
    egress: networkPath(egressLinks, egressLinks.length > 0 ? "nat_gateway" : null, coverageIncomplete),
  };
}

function linksFromEndpointToVm(
  endpointId: string,
  vmNics: readonly OntologyInstanceLink[],
  nicSubnets: readonly OntologyInstanceLink[],
): readonly OntologyInstanceLink[] {
  const vmNic = vmNics.find((link) => link.source === endpointId);
  if (vmNic) return [vmNic];
  const nicSubnet = nicSubnets.find((link) => link.target === endpointId);
  if (!nicSubnet) return [];
  const matchingVmNic = vmNics.find((link) => link.source === nicSubnet.source);
  return matchingVmNic ? [nicSubnet, matchingVmNic] : [];
}

function networkPath(
  links: readonly OntologyInstanceLink[],
  kind: OntologyInstanceNetworkPath["kind"],
  coverageIncomplete: boolean,
): OntologyInstanceNetworkPath {
  if (links.length === 0) {
    return {
      status: "unknown",
      kind: null,
      links: [],
      reason: coverageIncomplete ? "coverage_incomplete" : "no_reviewed_path",
    };
  }
  return {
    status: links.every((link) => link.evidence.status === "available" && link.evidence.complete)
      ? "current"
      : "stale",
    kind,
    links,
    reason: null,
  };
}

function compareNetworkPathLink(left: OntologyInstanceLink, right: OntologyInstanceLink): number {
  return `${left.source}\u0000${left.link_type}\u0000${left.target}`
    .localeCompare(`${right.source}\u0000${right.link_type}\u0000${right.target}`);
}

/** Classifies only reviewed provider mappings that prove a configured network traffic path. */
export function ontologyInstanceTrafficDirection(
  link: OntologyInstanceLink,
  rootId: string,
): OntologyInstanceTrafficDirection | null {
  const evidence = link.evidence;
  if (evidence.status !== "available" || !evidence.complete || evidence.mapping_id === null) {
    return null;
  }
  if (link.target === rootId && VERIFIED_BACKEND_TRAFFIC_MAPPINGS.has(evidence.mapping_id)) {
    return "ingress";
  }
  if (link.source === rootId && VERIFIED_EGRESS_TRAFFIC_MAPPINGS.has(evidence.mapping_id)) {
    return "egress";
  }
  return null;
}

/** Partitions direct graph direction, access, containment, traffic, and indirect path context. */
export function groupOntologyInstanceRelationships(
  links: readonly OntologyInstanceLink[],
  rootId: string,
): OntologyInstanceRelationshipGroups {
  const groups: Record<keyof OntologyInstanceRelationshipGroups, OntologyInstanceLink[]> = {
    directIncoming: [],
    directOutgoing: [],
    verifiedIngress: [],
    verifiedEgress: [],
    runtimeCalls: [],
    accessContext: [],
    containmentContext: [],
    path: [],
  };
  links.forEach((link) => {
    const direct = link.source === rootId || link.target === rootId;
    if (!direct) {
      groups.path.push(link);
      return;
    }
    const trafficDirection = ontologyInstanceTrafficDirection(link, rootId);
    if (link.link_type === "runtime_calls") {
      groups.runtimeCalls.push(link);
    } else if (trafficDirection === "ingress") {
      groups.verifiedIngress.push(link);
    } else if (trafficDirection === "egress") {
      groups.verifiedEgress.push(link);
    } else if (link.link_type === "attached_to" || link.link_type === "peered_with") {
      groups.accessContext.push(link);
    } else if (link.link_type === "contains") {
      groups.containmentContext.push(link);
    } else if (link.target === rootId) {
      groups.directIncoming.push(link);
    } else {
      groups.directOutgoing.push(link);
    }
  });
  return groups;
}

export function partitionOntologyInstanceLinks(
  links: readonly OntologyInstanceLink[],
  rootId: string,
): {
  readonly direct: readonly OntologyInstanceLink[];
  readonly path: readonly OntologyInstanceLink[];
} {
  return {
    direct: links.filter((link) => link.source === rootId || link.target === rootId),
    path: links.filter((link) => link.source !== rootId && link.target !== rootId),
  };
}

const ACTIVITY_FACTS = new Set([
  "action_type",
  "decision",
  "mode",
  "outcome",
  "reason",
  "risk_verdict",
  "state",
  "tier",
  "verdict",
]);
const INSTANCE_LINK_TYPES = new Set([
  "contains",
  "attached_to",
  "depends_on",
  "routes_to",
  "runtime_calls",
  "peered_with",
  "kubernetes_backed_by",
  "kubernetes_exposes_endpoint_slice",
  "kubernetes_exposes_endpoints",
  "kubernetes_owned_by",
  "kubernetes_scheduled_on",
  "kubernetes_selects",
]);

export function decodeOntologyInstanceDirectory(value: unknown): OntologyInstanceDirectory {
  const record = objectRecord(value, "instance directory");
  if (record.schema_version !== "1.0.0") throw new Error("instance directory schema_version MUST be 1.0.0");
  if (record.execution_authority !== false || record.mutation_authority !== false) {
    throw new Error("instance directory MUST carry no execution or mutation authority");
  }
  const releaseDigest = requiredString(record.ontology_release_digest, "directory ontology release");
  if (!/^sha256:[a-f0-9]{64}$/.test(releaseDigest)) {
    throw new Error("instance directory ontology release MUST be sha256");
  }
  const resources = array(record.resources, "directory resources", 200).map(decodeResource);
  if (new Set(resources.map((resource) => resource.id)).size !== resources.length
    || resources.some((resource) => resource.selected)) {
    throw new Error("instance directory resources MUST be unique and unselected");
  }
  const complete = boolean(record.complete, "directory complete");
  const truncationReason = record.truncation_reason;
  if (truncationReason !== null && truncationReason !== "resource_limit") {
    throw new Error("instance directory truncation reason is invalid");
  }
  if (complete === (truncationReason !== null)) {
    throw new Error("instance directory completeness contradicts truncation");
  }
  return {
    schema_version: "1.0.0",
    ontology_release_digest: releaseDigest,
    source_generation: requiredString(record.source_generation, "directory generation"),
    source_cutoff: timestamp(record.source_cutoff, "directory cutoff"),
    search: nullableString(record.search, "directory search", 256),
    resources,
    complete,
    truncation_reason: truncationReason,
    execution_authority: false,
    mutation_authority: false,
  };
}

export function decodeOntologyInstanceExploration(value: unknown): OntologyInstanceExploration {
  const record = objectRecord(value, "instance exploration");
  if (record.schema_version !== "1.3.0" && record.schema_version !== "1.4.0") {
    throw new Error("instance schema_version MUST be 1.3.0 or 1.4.0");
  }
  if (record.execution_authority !== false || record.mutation_authority !== false) {
    throw new Error("instance exploration MUST carry no execution or mutation authority");
  }
  const releaseDigest = requiredString(record.ontology_release_digest, "ontology release");
  if (!/^sha256:[a-f0-9]{64}$/.test(releaseDigest)) {
    throw new Error("instance ontology release MUST be sha256");
  }
  const sourceGeneration = requiredString(record.source_generation, "source generation");
  const sourceCutoff = timestamp(record.source_cutoff, "source cutoff");
  const rootId = requiredString(record.root_id, "root id", 1024);
  const depth = positiveInteger(record.depth, "instance depth");
  if (depth > 8) throw new Error("instance depth MUST be at most 8");
  const linkTypes = uniqueStrings(record.link_types, "link types", 16);
  if (linkTypes.some((linkType) => !INSTANCE_LINK_TYPES.has(linkType))) {
    throw new Error("instance link types MUST use the inventory relationship vocabulary");
  }
  const resources = array(record.resources, "resources", 200).map(decodeResource);
  const resourceIds = new Set(resources.map((resource) => resource.id));
  if (resourceIds.size !== resources.length || !resourceIds.has(rootId)) {
    throw new Error("instance resources MUST uniquely contain the root");
  }
  if (resources.filter((resource) => resource.selected).map((resource) => resource.id).join() !== rootId) {
    throw new Error("instance resources MUST select exactly the root");
  }
  const rootReceipt = resources.find((resource) => resource.id === rootId)?.aks_diagnostic_receipt;
  if (
    rootReceipt
    && (
      rootReceipt.ontology_release !== releaseDigest
      || rootReceipt.cutoff !== sourceCutoff
      || rootReceipt.source_cutoffs.inventory_snapshot !== sourceCutoff
    )
  ) {
    throw new Error("AKS diagnostic receipt MUST match the selected current source");
  }
  if (resources.some((resource) => resource.id !== rootId && resource.aks_diagnostic_receipt)) {
    throw new Error("AKS diagnostic receipt MUST only decorate the selected root");
  }
  const links = array(record.links, "links", 1600).map((item) => decodeLink(item, resourceIds, linkTypes));
  const linkKeys = new Set(links.map((link) => `${link.source}\u0000${link.link_type}\u0000${link.target}`));
  if (linkKeys.size !== links.length) throw new Error("instance links MUST be unique");
  const timelineRecord = objectRecord(record.timeline, "timeline");
  const timelineItems = array(timelineRecord.items, "timeline items", 100).map(decodeActivity);
  for (let index = 1; index < timelineItems.length; index++) {
    if (timelineItems[index - 1]!.sequence <= timelineItems[index]!.sequence) {
      throw new Error("instance activities MUST be newest-first");
    }
  }
  if (new Set(timelineItems.map((item) => item.sequence)).size !== timelineItems.length) {
    throw new Error("instance activity sequences MUST be unique");
  }
  const timelineComplete = boolean(timelineRecord.complete, "timeline complete");
  const timelineReason = timelineRecord.truncation_reason;
  if (timelineReason !== null && timelineReason !== "activity_limit") {
    throw new Error("instance timeline truncation reason is invalid");
  }
  if (timelineComplete === (timelineReason !== null)) {
    throw new Error("instance timeline completeness contradicts truncation");
  }
  const sources = array(record.sources, "sources", 43).map(decodeSource);
  if (
    new Set(sources.map((source) => `${source.source}\u0000${source.scope_digest ?? ""}`)).size
    !== sources.length
  ) {
    throw new Error("instance sources MUST be unique");
  }
  const sourceNames = new Set(sources.map((source) => source.source));
  for (const required of [
    "inventory_snapshot",
    "inventory_relationships",
    "fdai_audit",
    "runtime_call_graph",
    "postgres_role_evidence",
  ]) {
    if (!sourceNames.has(required)) throw new Error(`instance source ${required} is required`);
  }
  const kubernetesReceiptCutoff = rootReceipt?.source_cutoffs.kubernetes_runtime_inventory;
  const kubernetesReceiptRevision = rootReceipt?.source_revisions.kubernetes_runtime_inventory;
  if (
    rootReceipt
    && (
      (kubernetesReceiptCutoff === undefined) !== (kubernetesReceiptRevision === undefined)
      || (
        kubernetesReceiptCutoff !== undefined
        && !sources.some((source) =>
          source.source === "kubernetes_runtime_inventory"
          && source.status === "available"
          && source.observed_at === kubernetesReceiptCutoff
          && source.scope_digest === kubernetesReceiptRevision)
      )
    )
  ) {
    throw new Error("AKS diagnostic receipt source is not current");
  }
  const complete = boolean(record.complete, "complete");
  const identityFields = decodeContextIdentity(record, complete);
  const relationshipDropReasons = uniqueStrings(
    record.relationship_drop_reasons,
    "relationship drop reasons",
    16,
  );
  const relationshipDropClassifications = array(
    record.relationship_drop_classifications,
    "relationship drop classifications",
    256,
  ).map(decodeRelationshipDropClassification);
  const classificationKeys = new Set(relationshipDropClassifications.map((item) => [
    item.reason,
    item.mapping_id,
    item.source_property_path,
    item.source_provider_type,
    item.target_provider_type,
    item.unavailable_reason,
  ].join("\u0000")));
  if (classificationKeys.size !== relationshipDropClassifications.length) {
    throw new Error("relationship drop classifications MUST be unique");
  }
  const relationshipCoverage = record.relationship_coverage === undefined
    || record.relationship_coverage === null
    ? null
    : decodeRelationshipCoverage(record.relationship_coverage);
  const providerScopeCoverage = record.provider_scope_coverage === undefined
    || record.provider_scope_coverage === null
    ? null
    : decodeProviderScopeCoverage(record.provider_scope_coverage);
  const truncationReasons = uniqueStrings(
    record.truncation_reasons,
    "truncation reasons",
    4,
  );
  if (truncationReasons.some((reason) =>
    reason !== "adjacent_edge_limit"
    && reason !== "resource_limit"
    && reason !== "link_limit"
    && reason !== "activity_limit")) {
    throw new Error("instance truncation reason is invalid");
  }
  if (complete === (truncationReasons.length > 0 || relationshipDropReasons.length > 0)) {
    throw new Error("instance completeness contradicts truncation");
  }
  if (timelineReason !== null !== truncationReasons.includes("activity_limit")) {
    throw new Error("instance timeline truncation MUST match response truncation");
  }
  return {
    schema_version: record.schema_version,
    ontology_release_digest: releaseDigest,
    source_generation: sourceGeneration,
    source_cutoff: sourceCutoff,
    root_id: rootId,
    depth,
    link_types: linkTypes,
    resources,
    links,
    timeline: {
      items: timelineItems,
      complete: timelineComplete,
      truncation_reason: timelineReason,
    },
    sources,
    relationship_drop_reasons: relationshipDropReasons,
    relationship_drop_classifications: relationshipDropClassifications,
    relationship_coverage: relationshipCoverage,
    provider_scope_coverage: providerScopeCoverage,
    complete,
    truncation_reasons: truncationReasons as (
      "adjacent_edge_limit" | "resource_limit" | "link_limit" | "activity_limit"
    )[],
    execution_authority: false,
    mutation_authority: false,
    ...identityFields,
  };
}

function decodeRelationshipCoverage(value: unknown): OntologyInstanceRelationshipCoverage {
  const record = objectRecord(value, "relationship coverage");
  const totalCandidates = nonNegativeInteger(
    record.total_candidates,
    "relationship coverage total candidates",
  );
  const materialized = nonNegativeInteger(
    record.materialized,
    "relationship coverage materialized",
  );
  const reviewedUnavailable = nonNegativeInteger(
    record.reviewed_unavailable,
    "relationship coverage reviewed unavailable",
  );
  const unclassified = nonNegativeInteger(
    record.unclassified,
    "relationship coverage unclassified",
  );
  const complete = boolean(record.complete, "relationship coverage complete");
  if (totalCandidates !== materialized + reviewedUnavailable + unclassified) {
    throw new Error("relationship coverage counts MUST account for every candidate");
  }
  if (complete && unclassified > 0) {
    throw new Error("complete relationship coverage MUST NOT contain unclassified candidates");
  }
  return {
    total_candidates: totalCandidates,
    materialized,
    reviewed_unavailable: reviewedUnavailable,
    unclassified,
    complete,
  };
}

function decodeProviderScopeCoverage(value: unknown): OntologyInstanceProviderScopeCoverage {
  const record = objectRecord(value, "provider scope coverage");
  const captureMethod = requiredString(
    record.capture_method,
    "provider coverage capture method",
    128,
  );
  const providerObjectCount = nonNegativeInteger(
    record.provider_object_count,
    "provider coverage object count",
  );
  const mappedObjectCount = nonNegativeInteger(
    record.mapped_provider_object_count,
    "provider coverage mapped object count",
  );
  const unmappedObjectCount = nonNegativeInteger(
    record.unmapped_provider_object_count,
    "provider coverage unmapped object count",
  );
  const materializedUnmappedCount = nonNegativeInteger(
    record.materialized_unmapped_provider_object_count,
    "provider coverage materialized unmapped object count",
  );
  const providerTypeCount = nonNegativeInteger(
    record.provider_type_count,
    "provider coverage type count",
  );
  const unmappedProviderTypeCount = nonNegativeInteger(
    record.unmapped_provider_type_count,
    "provider coverage unmapped type count",
  );
  const providerIdentityComplete = boolean(
    record.provider_identity_complete,
    "provider coverage identity complete",
  );
  const unmappedProviderTypes = array(
    record.unmapped_provider_types,
    "provider coverage unmapped types",
    10_000,
  ).map((raw) => {
    const item = objectRecord(raw, "provider coverage unmapped type");
    return {
      provider_type: requiredString(
        item.provider_type,
        "provider coverage unmapped provider type",
        512,
      ),
      count: nonNegativeInteger(item.count, "provider coverage unmapped provider type count"),
    };
  });
  const providerTypeNames = unmappedProviderTypes.map((item) => item.provider_type);
  const sortedTypeNames = [...new Set(providerTypeNames)].sort();
  if (
    providerObjectCount !== mappedObjectCount + unmappedObjectCount
    || providerTypeCount > providerObjectCount
    || (providerObjectCount === 0) !== (providerTypeCount === 0)
    || unmappedProviderTypeCount !== unmappedProviderTypes.length
    || unmappedProviderTypes.length > providerTypeCount
    || unmappedProviderTypes.some((item) => item.count < 1)
    || unmappedProviderTypes.reduce((total, item) => total + item.count, 0)
      !== unmappedObjectCount
    || providerTypeNames.some((name, index) => name !== sortedTypeNames[index])
    || (materializedUnmappedCount !== 0 && materializedUnmappedCount !== unmappedObjectCount)
    || providerIdentityComplete !== (materializedUnmappedCount === unmappedObjectCount)
  ) {
    throw new Error("provider coverage object counts are inconsistent");
  }
  return {
    capture_method: captureMethod,
    provider_object_count: providerObjectCount,
    mapped_provider_object_count: mappedObjectCount,
    unmapped_provider_object_count: unmappedObjectCount,
    materialized_unmapped_provider_object_count: materializedUnmappedCount,
    provider_identity_complete: providerIdentityComplete,
    provider_type_count: providerTypeCount,
    unmapped_provider_type_count: unmappedProviderTypeCount,
    unmapped_provider_types: unmappedProviderTypes,
  };
}

function decodeContextIdentity(
  record: Record<string, unknown>,
  complete: boolean,
): Pick<
  OntologyInstanceExploration,
"principal_id" | "principal_scope_digest" | "selection_digest" | "selection_token"
> {
  const values = {
    principal_id: record.principal_id,
    principal_scope_digest: record.principal_scope_digest,
    selection_digest: record.selection_digest,
    selection_token: capabilityToken(record.context_capability),
  };
  const present = Object.values(values).some((value) => value !== undefined);
  if (!present) return {};
  if (!complete) throw new Error("incomplete instance exploration MUST NOT carry context identity");
  if (
    typeof values.principal_id !== "string" ||
    typeof values.principal_scope_digest !== "string" ||
    typeof values.selection_digest !== "string" ||
    typeof values.selection_token !== "string" ||
    !/^sha256:[a-f0-9]{64}$/.test(values.principal_scope_digest) ||
    !/^sha256:[a-f0-9]{64}$/.test(values.selection_digest)
  ) {
    throw new Error("instance context identity is incomplete or invalid");
  }

  function capabilityToken(value: unknown): string | undefined {
    if (value === undefined) return undefined;
    const capability = objectRecord(value, "context capability");
    const token = requiredString(capability.selection_token, "context capability token", 256);
    if (!/^context-selection:[a-f0-9]{32}$/.test(token)) {
      throw new Error("context capability token is invalid");
    }
    return token;
  }
  return values as Pick<
    OntologyInstanceExploration,
    "principal_id" | "principal_scope_digest" | "selection_digest"
    | "selection_token"
  >;
}

function decodeRelationshipDropClassification(
  value: unknown,
): OntologyRelationshipDropClassification {
  const record = objectRecord(value, "relationship drop classification");
  const unavailableReason = requiredString(
    record.unavailable_reason,
    "relationship unavailable reason",
    128,
  );
  if (![
    "reference_not_observed",
    "source_outside_active_generation",
    "target_outside_active_generation",
    "target_provider_type_unmodeled",
    "authorization_child_scope_unmodeled",
    "unclassified",
  ].includes(unavailableReason)) {
    throw new Error("relationship unavailable reason is invalid");
  }
  const count = positiveInteger(record.count, "relationship drop count");
  if (count > 2_147_483_647) throw new Error("relationship drop count exceeds its bound");
  return {
    reason: requiredString(record.reason, "relationship drop reason", 128),
    mapping_id: requiredString(record.mapping_id, "relationship mapping id", 256),
    source_property_path: requiredString(
      record.source_property_path,
      "relationship source property path",
      512,
    ),
    source_provider_type: requiredString(
      record.source_provider_type,
      "relationship source provider type",
      512,
    ),
    target_provider_type: requiredString(
      record.target_provider_type,
      "relationship target provider type",
      512,
    ),
    unavailable_reason: unavailableReason as OntologyRelationshipDropClassification["unavailable_reason"],
    count,
  };
}

function decodeResource(value: unknown): OntologyInstanceResource {
  const record = objectRecord(value, "Resource instance");
  if (record.object_type !== "Resource") throw new Error("instance object_type MUST be Resource");
  const resourceType = requiredString(record.resource_type, "Resource type", 256);
  const capacityKind = ontologyInstanceCapacityKind(resourceType);
  if (record.capacity !== undefined && record.capacity !== null && capacityKind === null) {
    throw new Error("Resource capacity MUST use a supported scalable Resource type");
  }
  if (
    record.model_deployment !== undefined
    && record.model_deployment !== null
    && resourceType !== "llm-model-deployment"
  ) {
    throw new Error("model deployment details MUST use the llm-model-deployment Resource type");
  }
  if (
    (
      record.kubernetes_identity !== undefined
      || record.kubernetes_diagnostics !== undefined
      || record.aks_diagnostic_receipt !== undefined
    )
    && !resourceType.startsWith("kubernetes.")
  ) {
    throw new Error("Kubernetes details MUST use a Kubernetes runtime Resource type");
  }
  const id = requiredString(record.id, "Resource id", 1024);
  const kubernetesIdentity =
    record.kubernetes_identity === undefined || record.kubernetes_identity === null
      ? null
      : decodeKubernetesIdentity(record.kubernetes_identity);
  const aksDiagnosticReceipt =
    record.aks_diagnostic_receipt === undefined || record.aks_diagnostic_receipt === null
      ? null
      : decodeAksDiagnosticReceipt(record.aks_diagnostic_receipt);
  if (
    aksDiagnosticReceipt
    && (
      kubernetesIdentity === null
      || aksDiagnosticReceipt.target_resource_id !== id
      || aksDiagnosticReceipt.target_uid !== kubernetesIdentity.uid
      || aksDiagnosticReceipt.target_resource_version !== kubernetesIdentity.resource_version
    )
  ) {
    throw new Error("AKS diagnostic receipt MUST match the exact Kubernetes Resource");
  }
  return {
    id,
    object_type: "Resource",
    resource_type: resourceType,
    name: nullableString(record.name, "Resource name", 512),
    location: nullableString(record.location, "Resource location", 128),
    resource_group: nullableString(record.resource_group, "Resource group", 256),
    status: nullableString(record.status, "Resource status", 128),
    capacity: record.capacity === undefined || record.capacity === null
      ? null
      : nonNegativeInteger(record.capacity, "Resource capacity"),
    last_seen: nullableTimestamp(record.last_seen, "Resource last seen"),
    selected: boolean(record.selected, "Resource selected"),
    model_deployment: record.model_deployment === undefined || record.model_deployment === null
      ? null
      : decodeModelDeployment(record.model_deployment),
    kubernetes_identity: kubernetesIdentity,
    kubernetes_diagnostics:
      record.kubernetes_diagnostics === undefined || record.kubernetes_diagnostics === null
        ? null
        : decodeKubernetesDiagnostics(record.kubernetes_diagnostics),
    ...(record.aks_diagnostic_receipt === undefined
      ? {}
      : { aks_diagnostic_receipt: aksDiagnosticReceipt }),
    ...(record.states === undefined ? {} : { states: decodeRecordedResourceStates(record.states) }),
  };
}

const KUBERNETES_DIAGNOSTIC_KEYS = new Set([
  "access_modes", "address_type", "affinity_kinds", "allow_volume_expansion", "available_replicas",
  "capacity_storage", "claim_name", "claim_namespace", "claim_uid", "container_count",
  "container_resources", "container_terminations", "container_waiting_reasons",
  "current_healthy", "current_replicas", "diagnostic_conditions", "disruptions_allowed",
  "desired_healthy", "desired_replicas", "egress_rule_count", "endpoint_count",
  "ephemeral_container_count", "ephemeral_container_ready_count",
  "ephemeral_container_restart_count", "ephemeral_container_termination_reasons",
  "ephemeral_container_waiting_reasons", "expected_pods", "init_container_count",
  "init_container_ready_count",
  "init_container_restart_count", "init_container_termination_reasons",
  "init_container_waiting_reasons", "ingress_rule_count", "limit_summaries", "max_replicas",
  "max_unavailable", "min_available", "min_replicas", "node_selector", "observed_generation",
  "phase", "policy_types", "port_count", "priority_class_name", "probe_kinds",
  "progressing_reason", "progressing_status", "provisioner", "pvc_claim_names", "qos_class",
  "quota_hard", "quota_used", "ready", "ready_container_count", "ready_replicas",
  "ready_status", "ready_unknown", "reason", "reclaim_policy", "requested_storage",
  "restart_count", "restart_policy",
  "scale_target_api_version", "scale_target_kind", "scale_target_name", "scheduler_name",
  "selector", "selector_matches_all", "serving", "serving_unknown", "service_account_name",
  "status_counts",
  "storage_class_name", "target_uids", "terminating", "terminating_unknown", "tolerations",
  "unavailable_replicas", "updated_replicas", "volume_binding_mode", "volume_mode", "volume_name",
]);

function decodeKubernetesIdentity(value: unknown): OntologyInstanceKubernetesIdentity {
  const record = objectRecord(value, "Kubernetes identity");
  return {
    api_version: requiredString(record.api_version, "Kubernetes api version", 512),
    kind: requiredString(record.kind, "Kubernetes kind", 256),
    name: requiredString(record.name, "Kubernetes name", 512),
    namespace: nullableString(record.namespace, "Kubernetes namespace", 253),
    resource_version: requiredString(record.resource_version, "Kubernetes resource version", 512),
    uid: requiredString(record.uid, "Kubernetes uid", 512),
  };
}

const AKS_DIAGNOSTIC_STATUSES = new Set<OntologyInstanceAksDiagnosticStatus>([
  "autoscale_limited",
  "control_plane_unavailable",
  "crash_loop",
  "endpoint_unready",
  "evicted",
  "held",
  "image_pull_failed",
  "node_pressure",
  "networking_unavailable",
  "no_failure_signal",
  "oom_killed",
  "probe_failure_evidence",
  "quota_constrained",
  "resource_pressure",
  "rollout_stalled",
  "scheduling_blocked",
  "storage_blocked",
]);

function decodeAksDiagnosticReceipt(value: unknown): OntologyInstanceAksDiagnosticReceipt {
  const record = objectRecord(value, "AKS diagnostic receipt");
  if (
    record.schema_version !== "1.0.0"
    || record.owner_agent !== "Forseti"
    || record.purpose !== "operations-review"
    || record.synthetic !== false
    || record.cause_claim_supported !== false
    || record.execution_authority !== false
  ) {
    throw new Error("AKS diagnostic receipt contract is invalid");
  }
  const ontologyRelease = requiredString(record.ontology_release, "AKS ontology release", 128);
  if (!/^sha256:[a-f0-9]{64}$/.test(ontologyRelease)) {
    throw new Error("AKS diagnostic ontology release MUST be sha256");
  }
  const status = requiredString(record.status, "AKS diagnostic status", 128);
  if (!AKS_DIAGNOSTIC_STATUSES.has(status as OntologyInstanceAksDiagnosticStatus)) {
    throw new Error("AKS diagnostic status is invalid");
  }
  const signals = uniqueStrings(record.signals, "AKS diagnostic signals", 16);
  if (signals.some((signal) =>
    !AKS_DIAGNOSTIC_STATUSES.has(signal as OntologyInstanceAksDiagnosticStatus))) {
    throw new Error("AKS diagnostic signal is invalid");
  }
  const sourceCutoffs = decodeAksSourceCutoffs(record.source_cutoffs);
  const sourceRevisions = decodeAksSourceRevisions(record.source_revisions);
  if (
    Object.keys(sourceCutoffs).length === 0
    || Object.keys(sourceCutoffs).length !== Object.keys(sourceRevisions).length
    || Object.keys(sourceCutoffs).some((source) => !(source in sourceRevisions))
    || sourceCutoffs.inventory_snapshot === undefined
  ) {
    throw new Error("AKS diagnostic source identities are invalid");
  }
  const cutoff = timestamp(record.cutoff, "AKS diagnostic cutoff");
  if (Object.values(sourceCutoffs).some((sourceCutoff) =>
    Date.parse(sourceCutoff) > Date.parse(cutoff))) {
    throw new Error("AKS diagnostic source cutoff exceeds the receipt cutoff");
  }
  return {
    schema_version: "1.0.0",
    owner_agent: "Forseti",
    principal_class: requiredString(record.principal_class, "AKS principal class", 64),
    purpose: "operations-review",
    producer_version: requiredString(record.producer_version, "AKS producer version", 128),
    method_version: requiredString(record.method_version, "AKS method version", 128),
    target_resource_id: requiredString(record.target_resource_id, "AKS target Resource id", 1024),
    target_uid: requiredString(record.target_uid, "AKS target uid", 512),
    target_resource_version: requiredString(
      record.target_resource_version,
      "AKS target resource version",
      512,
    ),
    ontology_release: ontologyRelease,
    cutoff,
    source_cutoffs: sourceCutoffs,
    source_revisions: sourceRevisions,
    status: status as OntologyInstanceAksDiagnosticStatus,
    signals: signals as OntologyInstanceAksDiagnosticStatus[],
    complete: boolean(record.complete, "AKS diagnostic complete"),
    evidence_gaps: diagnosticReasonCodes(record.evidence_gaps, "AKS evidence gaps"),
    conflicts: diagnosticReasonCodes(record.conflicts, "AKS conflicts"),
    evidence_refs: boundedStrings(record.evidence_refs, "AKS evidence refs", 32, 512),
    synthetic: false,
    cause_claim_supported: false,
    execution_authority: false,
    audit_correlation_id: requiredString(
      record.audit_correlation_id,
      "AKS audit correlation id",
      128,
    ),
  };
}

function decodeAksSourceCutoffs(value: unknown): Readonly<Record<string, string>> {
  const record = objectRecord(value, "AKS source cutoffs");
  if (Object.keys(record).length > 16) throw new Error("AKS source cutoffs exceed their bound");
  return Object.fromEntries(Object.entries(record).map(([source, cutoff]) => [
    diagnosticSourceName(source),
    timestamp(cutoff, `AKS ${source} cutoff`),
  ]));
}

function decodeAksSourceRevisions(value: unknown): Readonly<Record<string, string>> {
  const record = objectRecord(value, "AKS source revisions");
  if (Object.keys(record).length > 16) throw new Error("AKS source revisions exceed their bound");
  return Object.fromEntries(Object.entries(record).map(([source, revision]) => [
    diagnosticSourceName(source),
    requiredString(revision, `AKS ${source} revision`, 256),
  ]));
}

function diagnosticSourceName(value: string): string {
  if (!/^[a-z0-9][a-z0-9_.-]{0,127}$/.test(value)) {
    throw new Error("AKS source identity MUST be a bounded reason code");
  }
  return value;
}

function diagnosticReasonCodes(value: unknown, label: string): readonly string[] {
  const values = uniqueStrings(value, label, 32);
  if (values.some((item) => !/^[a-z0-9][a-z0-9_.-]{0,127}$/.test(item))) {
    throw new Error(`${label} MUST contain bounded reason codes`);
  }
  return values;
}

function boundedStrings(
  value: unknown,
  label: string,
  maximum: number,
  itemMaximum: number,
): readonly string[] {
  const values = array(value, label, maximum).map((item) =>
    requiredString(item, label, itemMaximum));
  if (new Set(values).size !== values.length) throw new Error(`${label} MUST be unique`);
  return values;
}

function decodeKubernetesDiagnostics(
  value: unknown,
): Readonly<Record<string, OntologyInstanceDiagnosticValue>> {
  const record = objectRecord(value, "Kubernetes diagnostics");
  if (Object.keys(record).some((key) => !KUBERNETES_DIAGNOSTIC_KEYS.has(key))) {
    throw new Error("Kubernetes diagnostics contain an unsupported key");
  }
  return Object.fromEntries(
    Object.entries(record).map(([key, item]) => [key, decodeDiagnosticValue(item, 0)]),
  );
}

function decodeDiagnosticValue(value: unknown, depth: number): OntologyInstanceDiagnosticValue {
  if (depth > 4) throw new Error("Kubernetes diagnostic nesting exceeds its bound");
  if (value === null || typeof value === "boolean") return value;
  if (typeof value === "string") {
    if (value.length > 512) throw new Error("Kubernetes diagnostic text exceeds its bound");
    return value;
  }
  if (typeof value === "number" && Number.isInteger(value) && Math.abs(value) <= 2_147_483_647) {
    return value;
  }
  if (Array.isArray(value)) {
    if (value.length > 128) throw new Error("Kubernetes diagnostic array exceeds its bound");
    return value.map((item) => decodeDiagnosticValue(item, depth + 1));
  }
  const record = objectRecord(value, "Kubernetes diagnostic object");
  if (Object.keys(record).length > 128) {
    throw new Error("Kubernetes diagnostic object exceeds its bound");
  }
  return Object.fromEntries(
    Object.entries(record).map(([key, item]) => [key, decodeDiagnosticValue(item, depth + 1)]),
  );
}

function decodeModelDeployment(value: unknown): OntologyInstanceModelDeployment {
  const record = objectRecord(value, "model deployment details");
  const capacityTpm = record.capacity_tpm === null
    ? null
    : nonNegativeInteger(record.capacity_tpm, "model deployment TPM");
  if (capacityTpm !== null && capacityTpm > 2_147_483_647) {
    throw new Error("model deployment TPM exceeds the provider projection bound");
  }
  return {
    model_name: nullableString(record.model_name, "model deployment model name", 256),
    model_version: nullableString(record.model_version, "model deployment model version", 256),
    sku_name: nullableString(record.sku_name, "model deployment SKU", 256),
    capacity_tpm: capacityTpm,
  };
}

function decodeLink(
  value: unknown,
  resourceIds: ReadonlySet<string>,
  linkTypes: readonly string[],
): OntologyInstanceLink {
  const record = objectRecord(value, "instance link");
  const source = requiredString(record.source, "link source", 1024);
  const target = requiredString(record.target, "link target", 1024);
  const linkType = requiredString(record.link_type, "link type", 128);
  if (!resourceIds.has(source) || !resourceIds.has(target)) {
    throw new Error("instance link endpoints MUST exist in resources");
  }
  if (!linkTypes.includes(linkType)) throw new Error("instance link type MUST be requested");
  return {
    source,
    target,
    link_type: linkType as OntologyInstanceLink["link_type"],
    evidence: decodeRelationshipEvidence(record.evidence),
  };
}

function decodeRelationshipEvidence(value: unknown): OntologyInstanceRelationshipEvidence {
  const record = objectRecord(value, "relationship evidence");
  const status = record.status;
  if (status !== "available" && status !== "stale" && status !== "unavailable") {
    throw new Error("relationship evidence status is invalid");
  }
  const evidenceKind = record.evidence_kind;
  if (evidenceKind !== null && evidenceKind !== "configuration" && evidenceKind !== "observation") {
    throw new Error("relationship evidence kind is invalid");
  }
  const inferredVerification = evidenceKind === "configuration"
    ? "configuration_observed"
    : evidenceKind === "observation"
      ? "independently_verified"
      : "unavailable";
  const verificationStatus = record.verification_status ?? inferredVerification;
  if (
    verificationStatus !== "configuration_observed"
    && verificationStatus !== "independently_verified"
    && verificationStatus !== "unavailable"
  ) {
    throw new Error("relationship evidence verification status is invalid");
  }
  if (verificationStatus !== inferredVerification) {
    throw new Error("relationship evidence verification status contradicts its kind");
  }
  const source = nullableString(record.source, "relationship evidence source", 128);
  const sourcePropertyPath = nullableString(
    record.source_property_path,
    "relationship evidence property path",
    512,
  );
  const mappingId = nullableString(record.mapping_id, "relationship evidence mapping", 256);
  const evidenceMethod = nullableString(
    record.evidence_method,
    "relationship evidence method",
    128,
  );
  const cutoff = nullableTimestamp(record.cutoff, "relationship evidence cutoff");
  const freshness = record.freshness_ceiling_seconds;
  const freshnessCeiling = freshness === null ? null : positiveInteger(
    freshness,
    "relationship evidence freshness",
  );
  const complete = boolean(record.complete, "relationship evidence complete");
  const reason = nullableString(record.reason, "relationship evidence reason", 128);
  const availableFields = [
    evidenceKind,
    source,
    sourcePropertyPath,
    mappingId,
    evidenceMethod,
    cutoff,
    freshnessCeiling,
  ];
  if (status === "available") {
    if (
      availableFields.some((field) => field === null)
      || verificationStatus === "unavailable"
      || !complete
      || reason !== null
    ) {
      throw new Error("available relationship evidence is incomplete");
    }
  } else if (status === "stale") {
    if (
      availableFields.some((field) => field === null)
      || verificationStatus === "unavailable"
      || complete
      || reason === null
    ) {
      throw new Error("stale relationship evidence is inconsistent");
    }
  } else if (availableFields.some((field) => field !== null) || complete || reason === null) {
    throw new Error("unavailable relationship evidence contradicts its fields");
  }
  return {
    status,
    evidence_kind: evidenceKind,
    verification_status: verificationStatus,
    source,
    source_property_path: sourcePropertyPath,
    mapping_id: mappingId,
    evidence_method: evidenceMethod,
    cutoff,
    freshness_ceiling_seconds: freshnessCeiling,
    complete,
    reason,
  };
}

function decodeActivity(value: unknown): OntologyInstanceActivity {
  const record = objectRecord(value, "instance activity");
  const sequence = record.sequence;
  if (!Number.isSafeInteger(sequence) || (sequence as number) < 1) {
    throw new Error("instance activity sequence MUST be positive");
  }
  const factsRecord = objectRecord(record.facts, "instance activity facts");
  const facts: Record<string, string> = {};
  for (const [key, fact] of Object.entries(factsRecord)) {
    if (!ACTIVITY_FACTS.has(key)) throw new Error("instance activity fact is not allowlisted");
    facts[key] = requiredString(fact, `activity fact ${key}`, 256);
  }
  const evidenceRef = requiredString(record.evidence_ref, "activity evidence ref", 128);
  if (evidenceRef !== `audit:${sequence as number}`) {
    throw new Error("instance activity evidence ref MUST match its sequence");
  }
  return {
    sequence: sequence as number,
    action_kind: requiredString(record.action_kind, "activity kind", 128),
    actor: requiredString(record.actor, "activity actor", 256),
    recorded_at: timestamp(record.recorded_at, "activity recorded at"),
    correlation_id: nullableString(record.correlation_id, "activity correlation", 256),
    facts,
    evidence_ref: evidenceRef,
  };
}

function decodeSource(value: unknown): OntologyInstanceSource {
  const record = objectRecord(value, "instance source");
  const status = record.status;
  if (status !== "available" && status !== "unavailable") {
    throw new Error("instance source status is invalid");
  }
  const observedAt = nullableTimestamp(record.observed_at, "source observation");
  const reason = nullableString(record.reason, "source reason", 128);
  const scopeDigest = nullableString(record.scope_digest ?? null, "source scope digest", 71);
  if (scopeDigest !== null && !/^sha256:[a-f0-9]{64}$/.test(scopeDigest)) {
    throw new Error("instance source scope digest is invalid");
  }
  if (status === "available" ? reason !== null : reason === null) {
    throw new Error("instance source reason contradicts availability");
  }
  return {
    source: requiredString(record.source, "source name", 128),
    scope_digest: scopeDigest,
    status,
    observed_at: observedAt,
    reason,
  };
}

function objectRecord(value: unknown, label: string): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error(`${label} MUST be an object`);
  }
  return value as Record<string, unknown>;
}

function array(value: unknown, label: string, maximum: number): unknown[] {
  if (!Array.isArray(value) || value.length > maximum) {
    throw new Error(`${label} MUST be an array of at most ${maximum}`);
  }
  return value;
}

function uniqueStrings(value: unknown, label: string, maximum: number): string[] {
  const values = array(value, label, maximum).map((item) => requiredString(item, label, 128));
  if (new Set(values).size !== values.length) throw new Error(`${label} MUST be unique`);
  return values;
}

function requiredString(value: unknown, label: string, maximum = 2048): string {
  if (typeof value !== "string" || value.length < 1 || value.length > maximum) {
    throw new Error(`${label} MUST be a bounded non-empty string`);
  }
  return value;
}

function nullableString(value: unknown, label: string, maximum: number): string | null {
  return value === null ? null : requiredString(value, label, maximum);
}

function boolean(value: unknown, label: string): boolean {
  if (typeof value !== "boolean") throw new Error(`${label} MUST be boolean`);
  return value;
}

function positiveInteger(value: unknown, label: string): number {
  if (!Number.isSafeInteger(value) || (value as number) < 1) {
    throw new Error(`${label} MUST be a positive integer`);
  }
  return value as number;
}

function nonNegativeInteger(value: unknown, label: string): number {
  if (!Number.isSafeInteger(value) || (value as number) < 0) {
    throw new Error(`${label} MUST be a non-negative integer`);
  }
  return value as number;
}

function timestamp(value: unknown, label: string): string {
  const text = requiredString(value, label, 64);
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.test(text)
    || Number.isNaN(Date.parse(text))) {
    throw new Error(`${label} MUST be RFC 3339`);
  }
  return text;
}

function nullableTimestamp(value: unknown, label: string): string | null {
  return value === null ? null : timestamp(value, label);
}
