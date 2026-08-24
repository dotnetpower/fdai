export interface OntologyInstanceResource {
  readonly id: string;
  readonly object_type: "Resource";
  readonly resource_type: string;
  readonly name: string | null;
  readonly location: string | null;
  readonly resource_group: string | null;
  readonly status: string | null;
  readonly last_seen: string | null;
  readonly selected: boolean;
}

const HIDDEN_ONTOLOGY_INSTANCE_DIRECTORY_TYPES = new Set([
  "authorization.role-assignment",
]);

/** Returns whether a Resource is meaningful as an operator-selected graph root. */
export function isOntologyInstanceDirectoryResource(
  resource: OntologyInstanceResource,
): boolean {
  return !HIDDEN_ONTOLOGY_INSTANCE_DIRECTORY_TYPES.has(resource.resource_type);
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
  if (!normalized || limit <= 0) return [];
  return options
    .filter((option) => option.value.toLowerCase().includes(normalized))
    .slice(0, limit);
}

export interface OntologyInstanceLink {
  readonly source: string;
  readonly target: string;
  readonly link_type: "contains" | "attached_to" | "depends_on" | "routes_to" | "runtime_calls" | "peered_with";
  readonly evidence: OntologyInstanceRelationshipEvidence;
}

export interface OntologyInstanceRelationshipEvidence {
  readonly status: "available" | "unavailable";
  readonly evidence_kind: "configuration" | "observation" | null;
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

export interface OntologyInstanceExploration {
  readonly schema_version: "1.3.0";
  readonly ontology_release_digest: string;
  readonly source_generation: string;
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
  readonly complete: boolean;
  readonly truncation_reasons: readonly (
    "adjacent_edge_limit" | "resource_limit" | "link_limit" | "activity_limit"
  )[];
  readonly execution_authority: false;
  readonly mutation_authority: false;
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
  readonly accessContext: readonly OntologyInstanceLink[];
  readonly containmentContext: readonly OntologyInstanceLink[];
  readonly path: readonly OntologyInstanceLink[];
}

const VERIFIED_BACKEND_TRAFFIC_MAPPINGS = new Set([
  "azure.application-gateway-routes-to-configured-backend",
  "azure.load-balancer-routes-to-configured-backend",
]);
const VERIFIED_EGRESS_TRAFFIC_MAPPINGS = new Set([
  ...VERIFIED_BACKEND_TRAFFIC_MAPPINGS,
  "azure.aks-routes-to-effective-outbound-ip",
]);

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
    if (trafficDirection === "ingress") {
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
  if (record.schema_version !== "1.3.0") throw new Error("instance schema_version MUST be 1.3.0");
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
  const sources = array(record.sources, "sources", 8).map(decodeSource);
  if (new Set(sources.map((source) => source.source)).size !== sources.length) {
    throw new Error("instance sources MUST be unique");
  }
  const sourceNames = new Set(sources.map((source) => source.source));
  for (const required of [
    "inventory_snapshot",
    "inventory_relationships",
    "fdai_audit",
    "runtime_call_graph",
  ]) {
    if (!sourceNames.has(required)) throw new Error(`instance source ${required} is required`);
  }
  const complete = boolean(record.complete, "complete");
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
    schema_version: "1.3.0",
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
    complete,
    truncation_reasons: truncationReasons as (
      "adjacent_edge_limit" | "resource_limit" | "link_limit" | "activity_limit"
    )[],
    execution_authority: false,
    mutation_authority: false,
  };
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
  return {
    id: requiredString(record.id, "Resource id", 1024),
    object_type: "Resource",
    resource_type: requiredString(record.resource_type, "Resource type", 256),
    name: nullableString(record.name, "Resource name", 512),
    location: nullableString(record.location, "Resource location", 128),
    resource_group: nullableString(record.resource_group, "Resource group", 256),
    status: nullableString(record.status, "Resource status", 128),
    last_seen: nullableTimestamp(record.last_seen, "Resource last seen"),
    selected: boolean(record.selected, "Resource selected"),
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
  if (status !== "available" && status !== "unavailable") {
    throw new Error("relationship evidence status is invalid");
  }
  const evidenceKind = record.evidence_kind;
  if (evidenceKind !== null && evidenceKind !== "configuration" && evidenceKind !== "observation") {
    throw new Error("relationship evidence kind is invalid");
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
    if (availableFields.some((field) => field === null) || !complete || reason !== null) {
      throw new Error("available relationship evidence is incomplete");
    }
  } else if (availableFields.some((field) => field !== null) || complete || reason === null) {
    throw new Error("unavailable relationship evidence contradicts its fields");
  }
  return {
    status,
    evidence_kind: evidenceKind,
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
  if (status === "available" ? reason !== null : reason === null) {
    throw new Error("instance source reason contradicts availability");
  }
  return {
    source: requiredString(record.source, "source name", 128),
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
