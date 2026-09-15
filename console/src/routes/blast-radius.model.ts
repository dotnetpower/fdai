import { routeHref } from "../router";
import { isRfc3339Timestamp } from "../time-format";

export const BLAST_RADIUS_LINKS = [
  "contains",
  "depends_on",
  "attached_to",
  "runtime_calls",
] as const;
export const DEFAULT_BLAST_RADIUS_LINKS: readonly string[] = ["contains", "depends_on"];

export interface BlastRadiusQuery {
  readonly target: string | null;
  readonly depth: number;
  readonly links: readonly string[];
  readonly architectureView: string | null;
}

export interface ReachedNode {
  readonly resource_id: string;
  readonly depth: number;
  readonly via_link_type: string | null;
}

export type ImpactRelationshipEvidenceStatus = "available" | "stale" | "unavailable";
export type ImpactRelationshipVerificationClass =
  | "configuration_observed"
  | "independently_verified"
  | "unavailable";

export interface ImpactRelationshipEvidence {
  readonly status: ImpactRelationshipEvidenceStatus;
  readonly evidence_kind: "configuration" | "observation" | null;
  readonly verification_status: ImpactRelationshipVerificationClass;
  readonly source: string | null;
  readonly source_property_path: string | null;
  readonly mapping_id: string | null;
  readonly evidence_method: string | null;
  readonly cutoff: string | null;
  readonly freshness_ceiling_seconds: number | null;
  readonly complete: boolean;
  readonly reason:
    | "provider_relationship_evidence_unavailable"
    | "relationship_source_incomplete"
    | "relationship_source_coverage_unavailable"
    | "relationship_evidence_future_cutoff"
    | "relationship_evidence_stale"
    | null;
}

export interface ImpactRelationshipSourceCoverage {
  readonly materialized: number;
  readonly reviewed_unavailable: number;
  readonly unclassified: number;
  readonly total_candidates: number;
  readonly complete: boolean;
}

export interface TraversedEdge {
  readonly source: string;
  readonly target: string;
  readonly link_type: string;
  readonly depth: number;
  readonly verification_status: "verified" | "unverified";
  readonly evidence: ImpactRelationshipEvidence | null;
}

export interface BlastRadiusResponse {
  readonly schema_version: "1.0.0" | "1.1.0";
  readonly ontology_release_digest: string;
  readonly source_generation: string;
  readonly source_cutoff: string;
  readonly target: string;
  readonly traversal_depth: number;
  readonly traversal_links: readonly string[];
  readonly reached: readonly ReachedNode[];
  readonly edges: readonly TraversedEdge[];
  readonly affected_count: number;
  readonly complete: boolean;
  readonly relationship_evidence_complete: boolean | null;
  readonly relationship_source_coverage: ImpactRelationshipSourceCoverage | null;
  readonly truncated_at_depth: boolean;
  readonly truncation_reasons: readonly ("depth_limit" | "edge_limit")[];
  readonly execution_authority: false;
  readonly mutation_authority: false;
}

export function decodeBlastRadiusResponse(value: unknown): BlastRadiusResponse {
  const record = impactRecord(value, "response");
  const schemaVersion = record.schema_version;
  if ((schemaVersion !== "1.0.0" && schemaVersion !== "1.1.0")
    || record.execution_authority !== false
    || record.mutation_authority !== false) {
    throw new Error("impact response MUST be read-only schema version 1.0.0 or 1.1.0");
  }
  const commonKeys = [
    "schema_version",
    "ontology_release_digest",
    "source_generation",
    "source_cutoff",
    "target",
    "traversal_depth",
    "traversal_links",
    "reached",
    "edges",
    "affected_count",
    "complete",
    "truncated_at_depth",
    "truncation_reasons",
    "execution_authority",
    "mutation_authority",
  ];
  impactExactKeys(
    record,
    schemaVersion === "1.1.0"
      ? [...commonKeys, "relationship_evidence_complete", "relationship_source_coverage"]
      : commonKeys,
    "response",
  );
  const releaseDigest = impactString(record, "ontology_release_digest");
  if (!/^sha256:[a-f0-9]{64}$/.test(releaseDigest)) {
    throw new Error("impact ontology release digest MUST be sha256");
  }
  const sourceCutoff = impactBoundedString(record, "source_cutoff", 64);
  if (!isRfc3339Timestamp(sourceCutoff)) {
    throw new Error("impact source_cutoff MUST be an RFC 3339 timestamp");
  }
  const target = impactBoundedString(record, "target", 1_024);
  const traversalDepth = impactInteger(record, "traversal_depth", 1, 5);
  const traversalLinks = impactStringArray(record.traversal_links, "traversal_links");
  if (traversalLinks.length === 0) throw new Error("impact traversal_links MUST NOT be empty");
  if (traversalLinks.length > 16 || traversalLinks.some((link) => link.length > 256)) {
    throw new Error("impact traversal_links exceed their bound");
  }
  const rawReached = impactArray(record.reached, "reached");
  if (rawReached.length > 1_001) {
    throw new Error("impact reached exceeds the 1001 Resource bound");
  }
  const reached = rawReached.map((raw) => {
    const item = impactRecord(raw, "reached item");
    impactExactKeys(item, ["resource_id", "depth", "via_link_type"], "reached item");
    const via = item.via_link_type;
    if (via !== null && (typeof via !== "string" || !via || via.length > 256)) {
      throw new Error("impact via_link_type MUST be null or non-empty");
    }
    return {
      resource_id: impactBoundedString(item, "resource_id", 1_024),
      depth: impactInteger(item, "depth", 0, traversalDepth),
      via_link_type: via as string | null,
    };
  });
  const identities = reached.map((item) => item.resource_id);
  if (new Set(identities).size !== identities.length
    || reached.filter((item) => item.resource_id === target && item.depth === 0).length !== 1) {
    throw new Error("impact reached identities MUST be unique and include the target root");
  }
  const reachedIdentities = new Set(identities);
  const reachedDepths = new Map(reached.map((item) => [item.resource_id, item.depth]));
  const rawEdges = impactArray(record.edges, "edges");
  if (rawEdges.length > 1_000) {
    throw new Error("impact edges exceed the 1000 relationship bound");
  }
  const edges = rawEdges.map((raw) => {
    const item = impactRecord(raw, "edge");
    impactExactKeys(
      item,
      schemaVersion === "1.1.0"
        ? ["source", "target", "link_type", "depth", "verification_status", "evidence"]
        : ["source", "target", "link_type", "depth", "verification_status"],
      "edge",
    );
    const verification = item.verification_status;
    if (verification !== "verified" && verification !== "unverified") {
      throw new Error("impact edge verification_status MUST be bounded");
    }
    const verificationStatus: TraversedEdge["verification_status"] = verification;
    const evidence = schemaVersion === "1.1.0"
      ? decodeImpactRelationshipEvidence(item.evidence, sourceCutoff)
      : null;
    if (schemaVersion === "1.1.0") {
      const expectedVerification = evidence?.status === "available"
        ? "verified"
        : "unverified";
      if (verificationStatus !== expectedVerification) {
        throw new Error("impact edge verification_status MUST match current evidence");
      }
    } else if (item.evidence !== undefined) {
      throw new Error("legacy impact edge MUST NOT carry additive evidence");
    }
    const linkType = impactBoundedString(item, "link_type", 256);
    if (!traversalLinks.includes(linkType)) {
      throw new Error("impact edge link_type MUST belong to the traversal request");
    }
    const source = impactBoundedString(item, "source", 1_024);
    const edgeTarget = impactBoundedString(item, "target", 1_024);
    if (source === edgeTarget) {
      throw new Error("impact edge MUST NOT be a self-link");
    }
    if (!reachedIdentities.has(source) || !reachedIdentities.has(edgeTarget)) {
      throw new Error("impact edge endpoints MUST reference reached identities");
    }
    const depth = impactInteger(item, "depth", 1, traversalDepth);
    const sourceDepth = reachedDepths.get(source);
    const targetDepth = reachedDepths.get(edgeTarget);
    if (sourceDepth !== depth - 1 || targetDepth === undefined || targetDepth > depth) {
      throw new Error("impact edge depth MUST follow the reached breadth-first depths");
    }
    return {
      source,
      target: edgeTarget,
      link_type: linkType,
      depth,
      verification_status: verificationStatus,
      evidence,
    };
  });
  const edgeSignatures = edges.map((edge) => JSON.stringify([
    edge.source,
    edge.target,
    edge.link_type,
  ]));
  if (new Set(edgeSignatures).size !== edgeSignatures.length) {
    throw new Error("impact edges MUST NOT contain duplicate relationships");
  }
  for (const node of reached) {
    if (node.resource_id === target) {
      if (node.via_link_type !== null) {
        throw new Error("impact target root via_link_type MUST be null");
      }
      continue;
    }
    if (node.depth === 0
      || node.via_link_type === null
      || !traversalLinks.includes(node.via_link_type)
      || !edges.some((edge) => (
        edge.target === node.resource_id
        && edge.depth === node.depth
        && edge.link_type === node.via_link_type
      ))) {
      throw new Error("impact reached node MUST have matching traversal edge provenance");
    }
  }
  const affectedCount = impactInteger(record, "affected_count", 0, Number.MAX_SAFE_INTEGER);
  if (affectedCount !== reached.length - 1) {
    throw new Error("impact affected_count MUST match reached identities excluding the target");
  }
  const reasons = impactStringArray(record.truncation_reasons, "truncation_reasons");
  if (reasons.some((reason) => reason !== "depth_limit" && reason !== "edge_limit")) {
    throw new Error("impact truncation reasons MUST be bounded");
  }
  if (typeof record.complete !== "boolean" || typeof record.truncated_at_depth !== "boolean") {
    throw new Error("impact completeness flags MUST be boolean");
  }
  if (record.complete !== (reasons.length === 0)
    || record.truncated_at_depth !== reasons.includes("depth_limit")) {
    throw new Error("impact completeness flags MUST match truncation reasons");
  }
  const relationshipEvidenceComplete = schemaVersion === "1.1.0"
    ? record.relationship_evidence_complete
    : null;
  if (schemaVersion === "1.1.0") {
    if (typeof relationshipEvidenceComplete !== "boolean") {
      throw new Error("impact relationship evidence completeness MUST be boolean");
    }
    const computedComplete = edges.every((edge) => edge.evidence?.complete === true);
    if (relationshipEvidenceComplete !== computedComplete) {
      throw new Error("impact relationship evidence completeness MUST match every edge");
    }
  } else if (record.relationship_evidence_complete !== undefined) {
    throw new Error("legacy impact response MUST NOT carry additive evidence completeness");
  }
  const relationshipSourceCoverage = schemaVersion === "1.1.0"
    ? decodeRelationshipSourceCoverage(record.relationship_source_coverage)
    : null;
  if (
    relationshipSourceCoverage !== null
    && relationshipSourceCoverage.materialized < edges.length
  ) {
    throw new Error("impact relationship source coverage cannot undercount returned edges");
  }
  for (const edge of edges) {
    const evidence = edge.evidence;
    if (evidence?.reason === "relationship_source_coverage_unavailable"
      && relationshipSourceCoverage !== null) {
      throw new Error(
        "unavailable relationship source coverage MUST match the response envelope",
      );
    }
    if (evidence?.reason === "relationship_source_incomplete"
      && (relationshipSourceCoverage === null || relationshipSourceCoverage.complete)) {
      throw new Error(
        "incomplete relationship source evidence MUST match the response envelope",
      );
    }
    if (evidence?.evidence_kind === "configuration"
      && evidence.status === "available"
      && (relationshipSourceCoverage === null || !relationshipSourceCoverage.complete)) {
      throw new Error(
        "current configuration evidence requires complete relationship source coverage",
      );
    }
  }
  if (schemaVersion === "1.0.0" && record.relationship_source_coverage !== undefined) {
    throw new Error("legacy impact response MUST NOT carry relationship source coverage");
  }
  return {
    schema_version: schemaVersion,
    ontology_release_digest: releaseDigest,
    source_generation: impactBoundedString(record, "source_generation", 256),
    source_cutoff: sourceCutoff,
    target,
    traversal_depth: traversalDepth,
    traversal_links: traversalLinks,
    reached,
    edges,
    affected_count: affectedCount,
    complete: record.complete,
    relationship_evidence_complete: relationshipEvidenceComplete as boolean | null,
    relationship_source_coverage: relationshipSourceCoverage,
    truncated_at_depth: record.truncated_at_depth,
    truncation_reasons: reasons as BlastRadiusResponse["truncation_reasons"],
    execution_authority: false,
    mutation_authority: false,
  };
}

function decodeRelationshipSourceCoverage(
  value: unknown,
): ImpactRelationshipSourceCoverage | null {
  if (value === null) return null;
  const record = impactRecord(value, "relationship source coverage");
  impactExactKeys(
    record,
    [
      "materialized",
      "reviewed_unavailable",
      "unclassified",
      "total_candidates",
      "complete",
    ],
    "relationship source coverage",
  );
  const materialized = impactInteger(
    record,
    "materialized",
    0,
    Number.MAX_SAFE_INTEGER,
  );
  const reviewedUnavailable = impactInteger(
    record,
    "reviewed_unavailable",
    0,
    Number.MAX_SAFE_INTEGER,
  );
  const unclassified = impactInteger(
    record,
    "unclassified",
    0,
    Number.MAX_SAFE_INTEGER,
  );
  const totalCandidates = impactInteger(
    record,
    "total_candidates",
    0,
    Number.MAX_SAFE_INTEGER,
  );
  if (typeof record.complete !== "boolean") {
    throw new Error("impact relationship source coverage complete MUST be boolean");
  }
  if (totalCandidates !== materialized + reviewedUnavailable + unclassified) {
    throw new Error("impact relationship source coverage counts MUST reconcile");
  }
  if (record.complete && unclassified !== 0) {
    throw new Error("complete impact relationship source coverage MUST be classified");
  }
  return {
    materialized,
    reviewed_unavailable: reviewedUnavailable,
    unclassified,
    total_candidates: totalCandidates,
    complete: record.complete,
  };
}

export type ImpactEdgeEvidenceState =
  | "configuration_observed"
  | "independently_verified"
  | "stale"
  | "source_incomplete"
  | "coverage_unavailable"
  | "unavailable"
  | "legacy_verified"
  | "legacy_unverified";

export function impactEdgeEvidenceState(edge: TraversedEdge): ImpactEdgeEvidenceState {
  if (edge.evidence === null) {
    return edge.verification_status === "verified"
      ? "legacy_verified"
      : "legacy_unverified";
  }
  if (edge.evidence.status === "stale") return "stale";
  if (edge.evidence.status === "unavailable") {
    if (edge.evidence.reason === "relationship_source_incomplete") {
      return "source_incomplete";
    }
    if (edge.evidence.reason === "relationship_source_coverage_unavailable") {
      return "coverage_unavailable";
    }
    return "unavailable";
  }
  return edge.evidence.verification_status;
}

function decodeImpactRelationshipEvidence(
  value: unknown,
  sourceCutoff: string,
): ImpactRelationshipEvidence {
  const record = impactRecord(value, "relationship evidence");
  impactExactKeys(
    record,
    [
      "status",
      "evidence_kind",
      "verification_status",
      "source",
      "source_property_path",
      "mapping_id",
      "evidence_method",
      "cutoff",
      "freshness_ceiling_seconds",
      "complete",
      "reason",
    ],
    "relationship evidence",
  );
  const status = record.status;
  if (status !== "available" && status !== "stale" && status !== "unavailable") {
    throw new Error("impact relationship evidence status MUST be bounded");
  }
  const evidenceKind = record.evidence_kind;
  const verification = record.verification_status;
  const complete = record.complete;
  if (typeof complete !== "boolean") {
    throw new Error("impact relationship evidence complete MUST be boolean");
  }
  const reason = record.reason;
  if (
    reason !== null
    && reason !== "provider_relationship_evidence_unavailable"
    && reason !== "relationship_source_incomplete"
    && reason !== "relationship_source_coverage_unavailable"
    && reason !== "relationship_evidence_future_cutoff"
    && reason !== "relationship_evidence_stale"
  ) {
    throw new Error("impact relationship evidence reason MUST be bounded");
  }
  const sourceQualificationUnavailable = status === "unavailable"
    && (
      reason === "relationship_source_incomplete"
      || reason === "relationship_source_coverage_unavailable"
    );
  if (status === "unavailable" && !sourceQualificationUnavailable) {
    if (
      evidenceKind !== null
      || verification !== "unavailable"
      || record.source !== null
      || record.source_property_path !== null
      || record.mapping_id !== null
      || record.evidence_method !== null
      || record.cutoff !== null
      || record.freshness_ceiling_seconds !== null
      || complete
      || reason !== "provider_relationship_evidence_unavailable"
    ) {
      throw new Error("unavailable impact relationship evidence MUST contain no claim");
    }
    return {
      status,
      evidence_kind: null,
      verification_status: "unavailable",
      source: null,
      source_property_path: null,
      mapping_id: null,
      evidence_method: null,
      cutoff: null,
      freshness_ceiling_seconds: null,
      complete: false,
      reason,
    };
  }
  if (evidenceKind !== "configuration" && evidenceKind !== "observation") {
    throw new Error("impact relationship evidence kind MUST be bounded");
  }
  if (sourceQualificationUnavailable && evidenceKind !== "configuration") {
    throw new Error(
      "unavailable relationship source coverage MUST qualify configuration evidence",
    );
  }
  const expectedVerification = evidenceKind === "observation"
    ? "independently_verified"
    : "configuration_observed";
  if (verification !== expectedVerification) {
    throw new Error("impact relationship verification class MUST match its evidence kind");
  }
  const source = impactBoundedString(record, "source", 512);
  const sourcePropertyPath = impactBoundedString(record, "source_property_path", 512);
  const mappingId = impactBoundedString(record, "mapping_id", 512);
  const evidenceMethod = impactBoundedString(record, "evidence_method", 512);
  const cutoff = impactBoundedString(record, "cutoff", 64);
  if (!isRfc3339Timestamp(cutoff)) {
    throw new Error("impact relationship evidence cutoff MUST be RFC 3339");
  }
  const followsSourceCutoff = Date.parse(cutoff) > Date.parse(sourceCutoff);
  if (
    followsSourceCutoff
    && (status !== "stale" || reason !== "relationship_evidence_future_cutoff")
  ) {
    throw new Error(
      "post-generation impact evidence MUST carry the future-cutoff stale reason",
    );
  }
  const freshness = impactInteger(
    record,
    "freshness_ceiling_seconds",
    1,
    31_536_000,
  );
  if (complete !== (status === "available")) {
    throw new Error("impact relationship evidence complete MUST match availability");
  }
  if (
    (status === "available" && reason !== null)
    || (status === "stale"
      && reason !== "relationship_evidence_future_cutoff"
      && reason !== "relationship_evidence_stale")
    || (status === "unavailable"
      && reason !== "relationship_source_incomplete"
      && reason !== "relationship_source_coverage_unavailable")
  ) {
    throw new Error("impact relationship evidence reason MUST match availability");
  }
  return {
    status,
    evidence_kind: evidenceKind,
    verification_status: expectedVerification,
    source,
    source_property_path: sourcePropertyPath,
    mapping_id: mappingId,
    evidence_method: evidenceMethod,
    cutoff,
    freshness_ceiling_seconds: freshness,
    complete,
    reason,
  };
}

function impactRecord(value: unknown, label: string): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error(`impact ${label} MUST be an object`);
  }
  return value as Record<string, unknown>;
}

function impactExactKeys(
  record: Record<string, unknown>,
  expected: readonly string[],
  label: string,
): void {
  const actual = Object.keys(record).sort();
  const keys = [...expected].sort();
  if (actual.length !== keys.length || actual.some((key, index) => key !== keys[index])) {
    throw new Error(`impact ${label} fields MUST match schema`);
  }
}

function impactString(record: Record<string, unknown>, key: string): string {
  const value = record[key];
  if (typeof value !== "string" || !value) throw new Error(`impact ${key} MUST be non-empty`);
  return value;
}

function impactBoundedString(
  record: Record<string, unknown>,
  key: string,
  maximum: number,
): string {
  const value = impactString(record, key);
  if (value.length > maximum) throw new Error(`impact ${key} exceeds its bound`);
  return value;
}

function impactInteger(
  record: Record<string, unknown>,
  key: string,
  minimum: number,
  maximum: number,
): number {
  const value = record[key];
  if (!Number.isInteger(value) || (value as number) < minimum || (value as number) > maximum) {
    throw new Error(`impact ${key} MUST be an integer in [${minimum}, ${maximum}]`);
  }
  return value as number;
}

function impactArray(value: unknown, label: string): unknown[] {
  if (!Array.isArray(value)) throw new Error(`impact ${label} MUST be an array`);
  return value;
}

function impactStringArray(value: unknown, label: string): string[] {
  const values = impactArray(value, label);
  if (values.some((item) => typeof item !== "string" || !item)) {
    throw new Error(`impact ${label} values MUST be non-empty strings`);
  }
  return values as string[];
}

export function blastRadiusQueryFromSearch(search: string): BlastRadiusQuery {
  const params = new URLSearchParams(search.replace(/^\?/, ""));
  const target = params.get("target")?.trim() || null;
  const rawDepth = Number(params.get("depth"));
  const depth = Number.isInteger(rawDepth) && rawDepth >= 1 && rawDepth <= 5 ? rawDepth : 2;
  const requestedLinks = [
    ...params.getAll("link"),
    ...(params.get("links")?.split(",") ?? []),
  ];
  const links = [...new Set(requestedLinks.map((value) => value.trim()).filter(
    (value) => BLAST_RADIUS_LINKS.includes(value as (typeof BLAST_RADIUS_LINKS)[number]),
  ))];
  const explicitlyEmptyLinks = params.get("links") === "none";
  return {
    target,
    depth,
    links: explicitlyEmptyLinks ? [] : links.length > 0 ? links : DEFAULT_BLAST_RADIUS_LINKS,
    architectureView: params.get("view")?.trim() || null,
  };
}

export function blastRadiusHref(query: BlastRadiusQuery, result: string | null = null): string {
  return routeHref("blast-radius", {
    params: {
      target: query.target,
      depth: query.depth,
      links: query.links.length > 0 ? query.links.join(",") : "none",
      view: query.architectureView,
      result,
    },
  });
}

export function blastRadiusRequestIsCurrent(current: number, candidate: number): boolean {
  return current === candidate;
}

export function blastRadiusResponseMatchesQuery(
  response: Pick<
    BlastRadiusResponse,
    "target" | "traversal_depth" | "traversal_links"
  >,
  query: BlastRadiusQuery,
): boolean {
  return query.target !== null
    && response.target === query.target
    && response.traversal_depth === query.depth
    && response.traversal_links.length === query.links.length
    && response.traversal_links.every((link, index) => link === query.links[index]);
}
