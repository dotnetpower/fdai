import { routeHref } from "../router";

export const BLAST_RADIUS_LINKS = ["contains", "depends_on", "attached_to"] as const;
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

export interface TraversedEdge {
  readonly source: string;
  readonly target: string;
  readonly link_type: string;
  readonly depth: number;
  readonly verification_status: "verified" | "unverified";
}

export interface BlastRadiusResponse {
  readonly schema_version: "1.0.0";
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
  readonly truncated_at_depth: boolean;
  readonly truncation_reasons: readonly ("depth_limit" | "edge_limit")[];
  readonly execution_authority: false;
  readonly mutation_authority: false;
}

export function decodeBlastRadiusResponse(value: unknown): BlastRadiusResponse {
  const record = impactRecord(value, "response");
  if (record.schema_version !== "1.0.0"
    || record.execution_authority !== false
    || record.mutation_authority !== false) {
    throw new Error("impact response MUST be read-only schema version 1.0.0");
  }
  const releaseDigest = impactString(record, "ontology_release_digest");
  if (!/^sha256:[a-f0-9]{64}$/.test(releaseDigest)) {
    throw new Error("impact ontology release digest MUST be sha256");
  }
  const target = impactString(record, "target");
  const traversalDepth = impactInteger(record, "traversal_depth", 1, 5);
  const traversalLinks = impactStringArray(record.traversal_links, "traversal_links");
  if (traversalLinks.length === 0) throw new Error("impact traversal_links MUST NOT be empty");
  const reached = impactArray(record.reached, "reached").map((raw) => {
    const item = impactRecord(raw, "reached item");
    const via = item.via_link_type;
    if (via !== null && (typeof via !== "string" || !via)) {
      throw new Error("impact via_link_type MUST be null or non-empty");
    }
    return {
      resource_id: impactString(item, "resource_id"),
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
  const edges = impactArray(record.edges, "edges").map((raw) => {
    const item = impactRecord(raw, "edge");
    const verification = item.verification_status;
    if (verification !== "verified" && verification !== "unverified") {
      throw new Error("impact edge verification_status MUST be bounded");
    }
    const verificationStatus: TraversedEdge["verification_status"] = verification;
    const linkType = impactString(item, "link_type");
    if (!traversalLinks.includes(linkType)) {
      throw new Error("impact edge link_type MUST belong to the traversal request");
    }
    const source = impactString(item, "source");
    const edgeTarget = impactString(item, "target");
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
  const sourceCutoff = impactString(record, "source_cutoff");
  if (!Number.isFinite(Date.parse(sourceCutoff))) {
    throw new Error("impact source_cutoff MUST be an RFC 3339 timestamp");
  }
  return {
    schema_version: "1.0.0",
    ontology_release_digest: releaseDigest,
    source_generation: impactString(record, "source_generation"),
    source_cutoff: sourceCutoff,
    target,
    traversal_depth: traversalDepth,
    traversal_links: traversalLinks,
    reached,
    edges,
    affected_count: affectedCount,
    complete: record.complete,
    truncated_at_depth: record.truncated_at_depth,
    truncation_reasons: reasons as BlastRadiusResponse["truncation_reasons"],
    execution_authority: false,
    mutation_authority: false,
  };
}

function impactRecord(value: unknown, label: string): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error(`impact ${label} MUST be an object`);
  }
  return value as Record<string, unknown>;
}

function impactString(record: Record<string, unknown>, key: string): string {
  const value = record[key];
  if (typeof value !== "string" || !value) throw new Error(`impact ${key} MUST be non-empty`);
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
