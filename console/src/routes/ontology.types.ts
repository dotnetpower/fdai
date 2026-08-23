import type { OntologyEdge, OntologyNode } from "../components/ontology-graph";
import {
  decodeOntologyKnowledgeGraph,
  type OntologyKnowledgeGraph,
} from "../components/ontology-knowledge-graph.model";
import {
  decodeOntologySemanticModel,
  type OntologySemanticModel,
} from "../components/ontology-semantic-model";

export type OntologyView = "map" | "objects" | "links" | "actions" | "topology";
export type UnknownRecord = Readonly<Record<string, unknown>>;

export interface OntologyPropertyDeclaration {
  readonly type: string;
  readonly required: boolean;
  readonly description?: string | null;
  readonly access_scope: "reader" | "contributor" | "approver" | "owner";
  readonly purpose_binding: readonly string[];
}

export interface OntologyObjectTypeDeclaration {
  readonly schema_version: string;
  readonly name: string;
  readonly version: string;
  readonly key: string;
  readonly properties: Readonly<Record<string, OntologyPropertyDeclaration>>;
  readonly description?: string | null;
  readonly lifecycle?: UnknownRecord;
  readonly provenance?: UnknownRecord;
}

export interface OntologyRelationshipDetail extends UnknownRecord {
  readonly name: string;
  readonly version: string;
  readonly from_type: string;
  readonly to_type: string;
  readonly selected_type_direction: "incoming" | "outgoing" | "self";
  readonly cardinality: string;
}

export interface OntologyObjectTypeDetailResponse {
  readonly schema_version: "1.0.0";
  readonly _revision: string;
  readonly ontology_release_digest: string;
  readonly declaration_kind: "object_type";
  readonly declaration_name: string;
  readonly mutation_authority: false;
  readonly complete: boolean;
  readonly incomplete_reasons: readonly string[];
  readonly redaction: {
    readonly redacted_field_count: number;
    readonly reasons: readonly string[];
  };
  readonly declaration: OntologyObjectTypeDeclaration;
  readonly relationships: readonly OntologyRelationshipDetail[];
  readonly related_actions: readonly (OntologyActionTypeRecord & {
    readonly target_evidence: UnknownRecord;
  })[];
}

export interface OntologyDependentRecord {
  readonly kind: string;
  readonly name: string;
  readonly relationship: string;
  readonly evidence_ref: string;
}

export interface OntologyDependentsResponse {
  readonly schema_version: "1.0.0";
  readonly _revision: string;
  readonly ontology_release_digest: string;
  readonly declaration_kind: "object_type";
  readonly declaration_name: string;
  readonly mutation_authority: false;
  readonly complete: boolean;
  readonly truncated: boolean;
  readonly truncation_reason: string | null;
  readonly dependents: readonly OntologyDependentRecord[];
}

export interface OntologyReleaseChange {
  readonly kind: string;
  readonly name: string;
  readonly version_before: string | null;
  readonly version_after: string | null;
  readonly digest_before: string | null;
  readonly digest_after: string | null;
}

export interface OntologyReleaseDiffResponse {
  readonly schema_version: "1.0.0";
  readonly base_release_digest: string;
  readonly candidate_release_digest: string;
  readonly mutation_authority: false;
  readonly added: readonly OntologyReleaseChange[];
  readonly changed: readonly OntologyReleaseChange[];
  readonly removed: readonly OntologyReleaseChange[];
  readonly compatibility_verdict: "compatible" | "migration_required" | "incompatible";
  readonly migration_required: boolean;
  readonly breaking_change: UnknownRecord | null;
  readonly historical_schema_detail: "declaration_refs_only";
  readonly unbound_historical_evidence: boolean;
  readonly diff_digest: string;
  readonly registry_truncated: boolean;
}

export interface OntologyEvidenceHealthResponse {
  readonly schema_version: "1.0.0";
  readonly _revision: string;
  readonly ontology_release_digest: string;
  readonly object_type: string;
  readonly availability: "available" | "unavailable";
  readonly unavailable_reason: string | null;
  readonly source: UnknownRecord | null;
  readonly freshness_state: "current" | "stale" | "unknown" | "unavailable";
  readonly complete: boolean;
  readonly truncated: boolean;
  readonly synthetic: boolean | null;
  readonly conflicts: readonly string[];
  readonly drop_reasons: readonly string[];
  readonly visible_instance_count: number | null;
  readonly visible_link_count: number | null;
  readonly evidence_refs: readonly string[];
  readonly execution_authority: false;
  readonly mutation_authority: false;
}

export interface OntologyActionTypeRecord {
  readonly schema_version: string;
  readonly name: string;
  readonly version: string;
  readonly operation: string;
  readonly interfaces: readonly string[];
  readonly rollback_contract: string;
  readonly irreversible: boolean;
  readonly default_mode: string;
  readonly promotion_gate: UnknownRecord;
  readonly preconditions: readonly UnknownRecord[];
  readonly stop_conditions: readonly UnknownRecord[];
  readonly blast_radius?: UnknownRecord;
  readonly description?: string;
  readonly category?: string;
  readonly trigger_kind?: UnknownRecord;
  readonly execution_path?: string;
  readonly ceiling_by_tier?: UnknownRecord;
  readonly env_scope: string;
  readonly prod_downgrade?: UnknownRecord;
  readonly argument_schema?: UnknownRecord;
  readonly live_probe_ref?: string;
}

export interface OntologyGraphResponse {
  readonly schema_version: "2.0.0";
  readonly _revision: string;
  readonly ontology_release_digest: string;
  readonly mutation_authority: false;
  readonly complete: boolean;
  readonly limitations: {
    readonly source_coverage: readonly string[];
    readonly query_truncation: readonly string[];
    readonly access_redaction: readonly string[];
    readonly presentation_omission: readonly string[];
  };
  readonly mermaid: string;
  readonly object_type_count: number;
  readonly link_type_count: number;
  readonly action_type_count?: number;
  readonly object_types: readonly string[];
  readonly link_types: readonly string[];
  readonly action_types?: readonly OntologyActionTypeRecord[];
  readonly interface_type_count: number;
  readonly function_type_count: number;
  readonly interface_types: readonly UnknownRecord[];
  readonly function_types: readonly UnknownRecord[];
  readonly semantic_model: OntologySemanticModel;
  readonly catalog_topology: OntologyKnowledgeGraph;
  readonly nodes?: readonly OntologyNode[];
  readonly edges?: readonly OntologyEdge[];
}

function responseRecord(value: unknown): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error("ontology graph response MUST be an object");
  }
  return value as Record<string, unknown>;
}

function responseString(record: Record<string, unknown>, key: string): string {
  const value = record[key];
  if (typeof value !== "string" || value.length === 0) {
    throw new Error(`ontology graph response ${key} MUST be a non-empty string`);
  }
  return value;
}

function responseCount(record: Record<string, unknown>, key: string): number {
  const value = record[key];
  if (!Number.isInteger(value) || (value as number) < 0) {
    throw new Error(`ontology graph response ${key} MUST be a non-negative integer`);
  }
  return value as number;
}

function responseBoolean(record: Record<string, unknown>, key: string): boolean {
  const value = record[key];
  if (typeof value !== "boolean") {
    throw new Error(`ontology graph response ${key} MUST be a boolean`);
  }
  return value;
}

function responseArray(record: Record<string, unknown>, key: string): unknown[] {
  const value = record[key];
  if (!Array.isArray(value)) throw new Error(`ontology graph response ${key} MUST be an array`);
  return value;
}

function limitationFamilies(record: Record<string, unknown>): OntologyGraphResponse["limitations"] {
  const value = responseRecord(record.limitations);
  const families = {
    source_coverage: responseArray(value, "source_coverage"),
    query_truncation: responseArray(value, "query_truncation"),
    access_redaction: responseArray(value, "access_redaction"),
    presentation_omission: responseArray(value, "presentation_omission"),
  };
  if (Object.values(families).some((items) =>
    items.some((item) => typeof item !== "string" || item.length === 0))) {
    throw new Error("ontology graph response limitation codes MUST be non-empty strings");
  }
  return families as OntologyGraphResponse["limitations"];
}

function decodeOntologyEdge(value: unknown): OntologyEdge {
  const record = responseRecord(value);
  const optionalRole = (key: "forward_role" | "reverse_role"): string | null => {
    const role = record[key];
    if (role === undefined || role === null) return null;
    if (typeof role !== "string" || role.length === 0) {
      throw new Error(`ontology graph edge ${key} MUST be null or a non-empty string`);
    }
    return role;
  };
  const traits = record.semantic_traits === undefined
    ? []
    : responseArray(record, "semantic_traits");
  if (traits.some((trait) => typeof trait !== "string" || trait.length === 0)
    || new Set(traits).size !== traits.length) {
    throw new Error("ontology graph edge semantic_traits MUST contain unique strings");
  }
  if (record.description !== null && typeof record.description !== "string") {
    throw new Error("ontology graph edge description MUST be null or a string");
  }
  return {
    name: responseString(record, "name"),
    from_type: responseString(record, "from_type"),
    to_type: responseString(record, "to_type"),
    cardinality: responseString(record, "cardinality"),
    is_transitive: responseBoolean(record, "is_transitive"),
    is_causal: responseBoolean(record, "is_causal"),
    temporal_order: responseBoolean(record, "temporal_order"),
    forward_role: optionalRole("forward_role"),
    reverse_role: optionalRole("reverse_role"),
    semantic_traits: traits as string[],
    description: record.description,
  };
}

export function decodeOntologyGraphResponse(value: unknown): OntologyGraphResponse {
  const record = responseRecord(value);
  if (record.schema_version !== "2.0.0") {
    throw new Error("ontology graph response schema_version MUST be 2.0.0");
  }
  if (record.mutation_authority !== false) {
    throw new Error("ontology graph response mutation_authority MUST be false");
  }
  const legacyLimitations = record.complete === undefined && record.limitations === undefined;
  if (!legacyLimitations && typeof record.complete !== "boolean") {
    throw new Error("ontology graph response complete MUST be a boolean");
  }
  const complete = legacyLimitations ? true : record.complete as boolean;
  const limitations = legacyLimitations
    ? {
        source_coverage: [],
        query_truncation: [],
        access_redaction: [],
        presentation_omission: [],
      }
    : limitationFamilies(record);
  const hasLimitations = Object.values(limitations).some((items) => items.length > 0);
  if (complete === hasLimitations) {
    throw new Error("ontology graph response complete MUST match limitation families");
  }
  const releaseDigest = responseString(record, "ontology_release_digest");
  if (!/^sha256:[a-f0-9]{64}$/.test(releaseDigest)) {
    throw new Error("ontology graph response ontology_release_digest MUST be sha256");
  }
  const objectTypes = responseArray(record, "object_types");
  const linkTypes = responseArray(record, "link_types");
  const actionTypes = responseArray(record, "action_types");
  const interfaceTypes = responseArray(record, "interface_types");
  const functionTypes = responseArray(record, "function_types");
  const counts = {
    objects: responseCount(record, "object_type_count"),
    links: responseCount(record, "link_type_count"),
    actions: responseCount(record, "action_type_count"),
    interfaces: responseCount(record, "interface_type_count"),
    functions: responseCount(record, "function_type_count"),
  };
  if (counts.objects !== objectTypes.length || counts.links !== linkTypes.length
    || counts.actions !== actionTypes.length || counts.interfaces !== interfaceTypes.length
    || counts.functions !== functionTypes.length) {
    throw new Error("ontology graph response declaration counts MUST match their records");
  }
  if (objectTypes.some((item) => typeof item !== "string")
    || linkTypes.some((item) => typeof item !== "string")) {
    throw new Error("ontology graph response declaration names MUST be strings");
  }
  const semanticModel = decodeOntologySemanticModel(record.semantic_model);
  const topology = decodeOntologyKnowledgeGraph(record.catalog_topology);
  if (topology.ontologyReleaseDigest !== releaseDigest) {
    throw new Error("ontology graph response topology release digest MUST match registry release");
  }
  const nodes = responseArray(record, "nodes") as unknown as OntologyNode[];
  const edges = responseArray(record, "edges").map(decodeOntologyEdge);
  if (nodes.length !== counts.objects || edges.length !== counts.links) {
    throw new Error("ontology graph response node and edge counts MUST match declarations");
  }
  return {
    schema_version: "2.0.0",
    _revision: responseString(record, "_revision"),
    ontology_release_digest: releaseDigest,
    mutation_authority: false,
    complete,
    limitations,
    mermaid: responseString(record, "mermaid"),
    object_type_count: counts.objects,
    link_type_count: counts.links,
    action_type_count: counts.actions,
    interface_type_count: counts.interfaces,
    function_type_count: counts.functions,
    object_types: objectTypes as string[],
    link_types: linkTypes as string[],
    action_types: actionTypes as unknown as OntologyActionTypeRecord[],
    interface_types: interfaceTypes as UnknownRecord[],
    function_types: functionTypes as UnknownRecord[],
    semantic_model: semanticModel,
    catalog_topology: topology,
    nodes,
    edges,
  };
}

export function decodeOntologyObjectTypeDetail(
  value: unknown,
  expectedReleaseDigest?: string,
): OntologyObjectTypeDetailResponse {
  const record = responseRecord(value);
  if (record.schema_version !== "1.0.0") {
    throw new Error("ontology declaration detail schema_version MUST be 1.0.0");
  }
  if (record.declaration_kind !== "object_type") {
    throw new Error("ontology declaration detail kind MUST be object_type");
  }
  if (record.mutation_authority !== false) {
    throw new Error("ontology declaration detail mutation_authority MUST be false");
  }
  const releaseDigest = detailDigest(record, "ontology_release_digest");
  if (expectedReleaseDigest !== undefined && releaseDigest !== expectedReleaseDigest) {
    throw new Error("ontology declaration detail release MUST match registry release");
  }
  const revision = detailDigest(record, "_revision");
  const declarationName = detailString(record, "declaration_name");
  const declaration = detailRecord(record.declaration, "declaration");
  if (declaration.name !== declarationName) {
    throw new Error("ontology declaration detail identity MUST match its declaration");
  }
  const properties = detailRecord(declaration.properties, "declaration.properties");
  const decodedProperties = Object.fromEntries(
    Object.entries(properties).map(([name, raw]) => [name, decodeProperty(raw, name)]),
  );
  const relationships = detailArray(record.relationships, "relationships").map((raw) => {
    const relationship = detailRecord(raw, "relationship");
    const direction = relationship.selected_type_direction;
    if (direction !== "incoming" && direction !== "outgoing" && direction !== "self") {
      throw new Error("ontology declaration relationship direction MUST be bounded");
    }
    const fromType = detailString(relationship, "from_type");
    const toType = detailString(relationship, "to_type");
    const expectedDirection = fromType === declarationName && toType === declarationName
      ? "self"
      : fromType === declarationName
        ? "outgoing"
        : toType === declarationName
          ? "incoming"
          : null;
    if (direction !== expectedDirection) {
      throw new Error("ontology declaration relationship direction MUST match exact endpoints");
    }
    return {
      ...relationship,
      name: detailString(relationship, "name"),
      version: detailString(relationship, "version"),
      from_type: fromType,
      to_type: toType,
      selected_type_direction: direction,
      cardinality: detailString(relationship, "cardinality"),
    } as OntologyRelationshipDetail;
  });
  const redaction = detailRecord(record.redaction, "redaction");
  const redactedFieldCount = redaction.redacted_field_count;
  if (!Number.isInteger(redactedFieldCount) || (redactedFieldCount as number) < 0) {
    throw new Error("ontology declaration redacted_field_count MUST be non-negative");
  }
  if (typeof record.complete !== "boolean") {
    throw new Error("ontology declaration detail complete MUST be boolean");
  }
  const relatedActions = detailArray(record.related_actions, "related_actions").map((raw) => {
    const action = detailRecord(raw, "related_action");
    detailRecord(action.target_evidence, "related_action.target_evidence");
    detailString(action, "name");
    return action as unknown as OntologyObjectTypeDetailResponse["related_actions"][number];
  });
  return {
    schema_version: "1.0.0",
    _revision: revision,
    ontology_release_digest: releaseDigest,
    declaration_kind: "object_type",
    declaration_name: declarationName,
    mutation_authority: false,
    complete: record.complete,
    incomplete_reasons: detailStringArray(record.incomplete_reasons, "incomplete_reasons"),
    redaction: {
      redacted_field_count: redactedFieldCount as number,
      reasons: detailStringArray(redaction.reasons, "redaction.reasons"),
    },
    declaration: {
      ...declaration,
      schema_version: detailString(declaration, "schema_version"),
      name: declarationName,
      version: detailString(declaration, "version"),
      key: detailString(declaration, "key"),
      properties: decodedProperties,
    } as OntologyObjectTypeDeclaration,
    relationships,
    related_actions: relatedActions,
  };
}

export function decodeOntologyDependents(
  value: unknown,
  expectedReleaseDigest: string,
  expectedName: string,
): OntologyDependentsResponse {
  const record = detailRecord(value, "dependents response");
  if (record.schema_version !== "1.0.0" || record.declaration_kind !== "object_type") {
    throw new Error("ontology dependents contract identity MUST be supported");
  }
  if (record.mutation_authority !== false) {
    throw new Error("ontology dependents mutation_authority MUST be false");
  }
  if (detailDigest(record, "ontology_release_digest") !== expectedReleaseDigest) {
    throw new Error("ontology dependents release MUST match registry release");
  }
  if (detailString(record, "declaration_name") !== expectedName) {
    throw new Error("ontology dependents declaration identity MUST match the requested name");
  }
  if (typeof record.complete !== "boolean" || typeof record.truncated !== "boolean") {
    throw new Error("ontology dependents completeness MUST be boolean");
  }
  if (record.complete === record.truncated) {
    throw new Error("ontology dependents complete and truncated MUST be inverse states");
  }
  const truncationReason = record.truncation_reason;
  if (truncationReason !== null && (typeof truncationReason !== "string" || !truncationReason)) {
    throw new Error("ontology dependents truncation_reason MUST be null or non-empty");
  }
  const dependents = detailArray(record.dependents, "dependents").map((raw) => {
    const dependent = detailRecord(raw, "dependent");
    return {
      kind: detailString(dependent, "kind"),
      name: detailString(dependent, "name"),
      relationship: detailString(dependent, "relationship"),
      evidence_ref: detailString(dependent, "evidence_ref"),
    };
  });
  const identities = dependents.map((item) => `${item.kind}\0${item.name}\0${item.relationship}`);
  if (new Set(identities).size !== identities.length) {
    throw new Error("ontology dependents identities MUST be unique");
  }
  return {
    schema_version: "1.0.0",
    _revision: detailDigest(record, "_revision"),
    ontology_release_digest: expectedReleaseDigest,
    declaration_kind: "object_type",
    declaration_name: expectedName,
    mutation_authority: false,
    complete: record.complete,
    truncated: record.truncated,
    truncation_reason: truncationReason as string | null,
    dependents,
  };
}

export function decodeOntologyReleaseDiff(
  value: unknown,
  expectedCandidateDigest: string,
): OntologyReleaseDiffResponse {
  const record = detailRecord(value, "release diff response");
  if (record.schema_version !== "1.0.0" || record.mutation_authority !== false) {
    throw new Error("ontology release diff contract MUST be read-only version 1.0.0");
  }
  const candidate = detailDigest(record, "candidate_release_digest");
  if (candidate !== expectedCandidateDigest) {
    throw new Error("ontology release diff candidate MUST match the active release");
  }
  const verdict = record.compatibility_verdict;
  if (verdict !== "compatible" && verdict !== "migration_required" && verdict !== "incompatible") {
    throw new Error("ontology release diff compatibility verdict MUST be bounded");
  }
  if (typeof record.migration_required !== "boolean"
    || typeof record.unbound_historical_evidence !== "boolean"
    || typeof record.registry_truncated !== "boolean") {
    throw new Error("ontology release diff state flags MUST be boolean");
  }
  if (record.historical_schema_detail !== "declaration_refs_only") {
    throw new Error("ontology release diff historical schema detail MUST be explicit");
  }
  return {
    schema_version: "1.0.0",
    base_release_digest: detailDigest(record, "base_release_digest"),
    candidate_release_digest: candidate,
    mutation_authority: false,
    added: decodeReleaseChanges(record.added),
    changed: decodeReleaseChanges(record.changed),
    removed: decodeReleaseChanges(record.removed),
    compatibility_verdict: verdict,
    migration_required: record.migration_required,
    breaking_change: record.breaking_change === null
      ? null
      : detailRecord(record.breaking_change, "breaking_change"),
    historical_schema_detail: "declaration_refs_only",
    unbound_historical_evidence: record.unbound_historical_evidence,
    diff_digest: detailDigest(record, "diff_digest"),
    registry_truncated: record.registry_truncated,
  };
}

export function decodeOntologyEvidenceHealth(
  value: unknown,
  expectedReleaseDigest: string,
  expectedObjectType: string,
): OntologyEvidenceHealthResponse {
  const record = detailRecord(value, "evidence health response");
  if (record.schema_version !== "1.0.0"
    || record.execution_authority !== false
    || record.mutation_authority !== false) {
    throw new Error("ontology evidence health contract MUST be read-only version 1.0.0");
  }
  if (detailDigest(record, "ontology_release_digest") !== expectedReleaseDigest
    || detailString(record, "object_type") !== expectedObjectType) {
    throw new Error("ontology evidence health identity MUST match the active declaration");
  }
  const availability = record.availability;
  const freshnessState = record.freshness_state;
  if (availability !== "available" && availability !== "unavailable") {
    throw new Error("ontology evidence health availability MUST be bounded");
  }
  if (freshnessState !== "current" && freshnessState !== "stale"
    && freshnessState !== "unknown" && freshnessState !== "unavailable") {
    throw new Error("ontology evidence health freshness_state MUST be bounded");
  }
  if (typeof record.complete !== "boolean" || typeof record.truncated !== "boolean") {
    throw new Error("ontology evidence health completeness MUST be boolean");
  }
  const source = record.source === null ? null : detailRecord(record.source, "evidence source");
  const unavailableReason = nullableString(record.unavailable_reason);
  const synthetic = record.synthetic;
  const instanceCount = nullableCount(record.visible_instance_count);
  const linkCount = nullableCount(record.visible_link_count);
  if (availability === "unavailable" && (
    unavailableReason === null || source !== null || freshnessState !== "unavailable"
    || record.complete || synthetic !== null || instanceCount !== null || linkCount !== null
  )) {
    throw new Error("unavailable ontology evidence health MUST NOT fabricate source state");
  }
  if (availability === "available" && (
    unavailableReason !== null || source === null || freshnessState === "unavailable"
    || typeof synthetic !== "boolean" || instanceCount === null || linkCount === null
  )) {
    throw new Error("available ontology evidence health MUST carry typed source state");
  }
  return {
    schema_version: "1.0.0",
    _revision: detailDigest(record, "_revision"),
    ontology_release_digest: expectedReleaseDigest,
    object_type: expectedObjectType,
    availability,
    unavailable_reason: unavailableReason,
    source,
    freshness_state: freshnessState,
    complete: record.complete,
    truncated: record.truncated,
    synthetic: synthetic as boolean | null,
    conflicts: detailStringArray(record.conflicts, "evidence conflicts"),
    drop_reasons: detailStringArray(record.drop_reasons, "evidence drop_reasons"),
    visible_instance_count: instanceCount,
    visible_link_count: linkCount,
    evidence_refs: detailStringArray(record.evidence_refs, "evidence refs"),
    execution_authority: false,
    mutation_authority: false,
  };
}

function nullableCount(value: unknown): number | null {
  if (value === null) return null;
  if (!Number.isInteger(value) || (value as number) < 0) {
    throw new Error("ontology evidence count MUST be null or non-negative");
  }
  return value as number;
}

function decodeReleaseChanges(value: unknown): OntologyReleaseChange[] {
  return detailArray(value, "release changes").map((raw) => {
    const change = detailRecord(raw, "release change");
    return {
      kind: detailString(change, "kind"),
      name: detailString(change, "name"),
      version_before: nullableString(change.version_before),
      version_after: nullableString(change.version_after),
      digest_before: nullableDigest(change.digest_before),
      digest_after: nullableDigest(change.digest_after),
    };
  });
}

function nullableString(value: unknown): string | null {
  if (value === null) return null;
  if (typeof value !== "string" || value.length === 0) {
    throw new Error("ontology release change value MUST be null or non-empty");
  }
  return value;
}

function nullableDigest(value: unknown): string | null {
  const decoded = nullableString(value);
  if (decoded !== null && !/^sha256:[a-f0-9]{64}$/.test(decoded)) {
    throw new Error("ontology release change digest MUST be null or sha256");
  }
  return decoded;
}

function decodeProperty(value: unknown, name: string): OntologyPropertyDeclaration {
  const property = detailRecord(value, `property ${name}`);
  const accessScope = property.access_scope;
  if (accessScope !== "reader" && accessScope !== "contributor"
    && accessScope !== "approver" && accessScope !== "owner") {
    throw new Error(`ontology property ${name} access_scope MUST be an ordinary role`);
  }
  if (typeof property.required !== "boolean") {
    throw new Error(`ontology property ${name} required MUST be boolean`);
  }
  return {
    type: detailString(property, "type"),
    required: property.required,
    ...(property.description === undefined || property.description === null
      ? {}
      : { description: detailString(property, "description") }),
    access_scope: accessScope,
    purpose_binding: detailStringArray(property.purpose_binding, `property ${name} purpose_binding`),
  };
}

function detailRecord(value: unknown, label: string): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error(`ontology declaration ${label} MUST be an object`);
  }
  return value as Record<string, unknown>;
}

function detailArray(value: unknown, label: string): unknown[] {
  if (!Array.isArray(value)) throw new Error(`ontology declaration ${label} MUST be an array`);
  return value;
}

function detailString(record: Record<string, unknown>, key: string): string {
  const value = record[key];
  if (typeof value !== "string" || value.length === 0) {
    throw new Error(`ontology declaration ${key} MUST be a non-empty string`);
  }
  return value;
}

function detailStringArray(value: unknown, label: string): string[] {
  const values = detailArray(value, label);
  if (values.some((item) => typeof item !== "string" || item.length === 0)) {
    throw new Error(`ontology declaration ${label} values MUST be strings`);
  }
  return values as string[];
}

function detailDigest(record: Record<string, unknown>, key: string): string {
  const value = detailString(record, key);
  if (!/^sha256:[a-f0-9]{64}$/.test(value)) {
    throw new Error(`ontology declaration ${key} MUST be sha256`);
  }
  return value;
}

export function ontologyView(value: string | null): OntologyView {
  return value === "objects"
    || value === "links"
    || value === "actions"
    || value === "topology"
    ? value
    : "map";
}

export function recordValue(record: UnknownRecord | undefined, key: string): string | null {
  const value = record?.[key];
  if (value === null || value === undefined) return null;
  return String(value);
}

export function compactRecord(record: UnknownRecord): string {
  return Object.entries(record)
    .map(([key, value]) => `${key}: ${formatUnknown(value)}`)
    .join(" | ");
}

export function formatUnknown(value: unknown): string {
  if (value === null || value === undefined) return "-";
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  if (Array.isArray(value)) return value.map(formatUnknown).join(", ");
  if (typeof value === "object") {
    return Object.entries(value as Record<string, unknown>)
      .map(([key, nested]) => `${key}=${formatUnknown(nested)}`)
      .join(", ");
  }
  return String(value);
}
