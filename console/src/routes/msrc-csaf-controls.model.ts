import { OperatorApiError } from "../api";
import { routeHref } from "../router";
import msrcCsafCatalogJson from "./msrc-csaf-catalog.json";
import {
  panelArray,
  panelBoolean,
  panelNonEmptyString,
  panelNonNegativeInteger,
  panelNullableString,
  panelRecord,
  panelStringArray,
} from "./panel-decode";

export const MSRC_CSAF_SEVERITIES = ["critical", "high", "medium", "low"] as const;
export const MSRC_CSAF_EXPLOIT_STATUSES = [
  "exploited",
  "exploitation_more_likely",
  "exploitation_less_likely",
  "exploitation_unlikely",
  "publicly_disclosed",
  "unproven",
] as const;
export const MSRC_CSAF_DISPOSITIONS = [
  "existing_rule",
  "new_rule_candidate",
  "version_observation",
  "manual_evidence",
  "conditional_not_applicable",
  "ambiguous_or_blocked",
] as const;
export const MSRC_CSAF_MAPPING_STATES = ["full", "partial", "unmapped"] as const;
export const MSRC_CSAF_EXPOSURES = [
  "affected",
  "mitigated",
  "fixed",
  "not_applicable",
  "unknown",
] as const;

export type MsrcCsafSeverity = (typeof MSRC_CSAF_SEVERITIES)[number];
export type MsrcCsafExploitStatus = (typeof MSRC_CSAF_EXPLOIT_STATUSES)[number];
export type MsrcCsafDisposition = (typeof MSRC_CSAF_DISPOSITIONS)[number];
export type MsrcCsafMappingState = (typeof MSRC_CSAF_MAPPING_STATES)[number];
export type MsrcCsafExposure = (typeof MSRC_CSAF_EXPOSURES)[number];

export interface MsrcCsafRemediation {
  readonly category: "vendor_fix" | "workaround" | "mitigation" | "none_available";
  readonly product_ids: readonly string[];
  readonly details: string;
  readonly fixed_version: string | null;
  readonly kb_article: string | null;
  readonly workaround_property: string | null;
  readonly workaround_expected_value: string | boolean | number | null;
  readonly recommended_action_type: string | null;
  readonly url: string | null;
}

export interface MsrcCsafProductMapping {
  readonly product_id: string;
  readonly product_name: string;
  readonly disposition: "canonical" | "unsupported" | "ambiguous";
  readonly canonical_resource_type: string | null;
  readonly canonical_resource_types: readonly string[];
  readonly provider_resource_types: readonly string[];
  readonly version_property: string | null;
  readonly minimum_affected_version_inclusive: string | null;
  readonly vulnerable_version_ceiling_exclusive: string | null;
  readonly freshness_ceiling_seconds: number;
  readonly reviewer: string;
}

export interface MsrcCsafControlRow {
  readonly cve_id: string;
  readonly title: string;
  readonly advisory_tracking_id: string;
  readonly advisory_title: string;
  readonly source_url: string;
  readonly document_digest: string;
  readonly initial_release_date: string;
  readonly current_release_date: string;
  readonly signature_verified: boolean;
  readonly severity: MsrcCsafSeverity;
  readonly cvss_base_score: number;
  readonly cvss_temporal_score: number | null;
  readonly cvss_vector: string;
  readonly exploit_status: MsrcCsafExploitStatus;
  readonly publicly_disclosed: boolean;
  readonly disposition: MsrcCsafDisposition;
  readonly mapping_state: MsrcCsafMappingState;
  readonly product_ids: readonly string[];
  readonly products: readonly MsrcCsafProductMapping[];
  readonly primary_resource_type: string;
  readonly version_window: string;
  readonly existing_rule_id: string | null;
  readonly candidate_action_type: string | null;
  readonly workaround_property: string | null;
  readonly workaround_expected_value: string | boolean | number | null;
  readonly blocked_reasons: readonly string[];
  readonly remediations: readonly MsrcCsafRemediation[];
  readonly evaluation_status: "not_evaluated" | "evaluated" | "blocked";
  readonly exposure: MsrcCsafExposure;
  readonly execution_authority: false;
}

export interface MsrcCsafCatalog {
  readonly schema_version: string;
  readonly source_id: "msrc_csaf";
  readonly source_revision: string;
  readonly advisories_digest: string;
  readonly crosswalk_digest: string;
  readonly rows: readonly MsrcCsafControlRow[];
}

export interface MsrcCsafFilters {
  readonly severity: string;
  readonly exploit_status: string;
  readonly disposition: string;
  readonly mapping_state: string;
  readonly resource_type: string;
  readonly q: string;
}

export const EMPTY_MSRC_CSAF_FILTERS: MsrcCsafFilters = {
  severity: "",
  exploit_status: "",
  disposition: "",
  mapping_state: "",
  resource_type: "",
  q: "",
};

function decodeEnum<T extends string>(
  value: string,
  allowed: readonly T[],
  label: string,
): T {
  if (!allowed.includes(value as T)) {
    throw new OperatorApiError(502, `invalid MSRC CSAF value for ${label}: ${value}`);
  }
  return value as T;
}

export function decodeMsrcCsafCatalog(raw: unknown): MsrcCsafCatalog {
  const root = panelRecord(raw, "msrc_csaf");
  const schemaVersion = panelNonEmptyString(root, "schema_version", "msrc_csaf");
  const sourceId = panelNonEmptyString(root, "source_id", "msrc_csaf");
  if (sourceId !== "msrc_csaf") {
    throw new OperatorApiError(502, "invalid MSRC CSAF catalog source_id");
  }
  const sourceRevision = panelNonEmptyString(root, "source_revision", "msrc_csaf");
  const advisoriesDigest = panelNonEmptyString(root, "advisories_digest", "msrc_csaf");
  const crosswalkDigest = panelNonEmptyString(root, "crosswalk_digest", "msrc_csaf");

  const productMap = new Map<string, MsrcCsafProductMapping>();
  for (const [idx, item] of panelArray(root["product_mappings"], "msrc_csaf.product_mappings").entries()) {
    const prod = panelRecord(item, `product_mappings[${idx}]`);
    const productId = panelNonEmptyString(prod, "product_id", `product_mappings[${idx}]`);
    const disposition = decodeEnum(
      panelNonEmptyString(prod, "disposition", `product_mappings[${idx}]`),
      ["canonical", "unsupported", "ambiguous"] as const,
      `product_mappings[${idx}].disposition`,
    );
    productMap.set(productId, {
      product_id: productId,
      product_name: panelNonEmptyString(prod, "product_name", `product_mappings[${idx}]`),
      disposition,
      canonical_resource_type: panelNullableString(prod, "canonical_resource_type", `product_mappings[${idx}]`),
      canonical_resource_types: panelStringArray(
        prod["canonical_resource_types"],
        `product_mappings[${idx}].canonical_resource_types`,
      ),
      provider_resource_types: panelStringArray(
        prod["provider_resource_types"],
        `product_mappings[${idx}].provider_resource_types`,
      ),
      version_property: panelNullableString(prod, "version_property", `product_mappings[${idx}]`),
      minimum_affected_version_inclusive: panelNullableString(
        prod,
        "minimum_affected_version_inclusive",
        `product_mappings[${idx}]`,
      ),
      vulnerable_version_ceiling_exclusive: panelNullableString(
        prod,
        "vulnerable_version_ceiling_exclusive",
        `product_mappings[${idx}]`,
      ),
      freshness_ceiling_seconds: panelNonNegativeInteger(
        prod,
        "freshness_ceiling_seconds",
        `product_mappings[${idx}]`,
      ),
      reviewer: panelNonEmptyString(prod, "reviewer", `product_mappings[${idx}]`),
    });
  }

  const vulnMeta = new Map<
    string,
    {
      readonly advisory_tracking_id: string;
      readonly advisory_title: string;
      readonly source_url: string;
      readonly document_digest: string;
      readonly initial_release_date: string;
      readonly current_release_date: string;
      readonly signature_verified: boolean;
      readonly title: string;
      readonly severity: MsrcCsafSeverity;
      readonly cvss_base_score: number;
      readonly cvss_temporal_score: number | null;
      readonly cvss_vector: string;
      readonly exploit_status: MsrcCsafExploitStatus;
      readonly publicly_disclosed: boolean;
      readonly remediations: readonly MsrcCsafRemediation[];
    }
  >();

  for (const [advIdx, advItem] of panelArray(root["advisories"], "msrc_csaf.advisories").entries()) {
    const adv = panelRecord(advItem, `advisories[${advIdx}]`);
    const trackingId = panelNonEmptyString(adv, "tracking_id", `advisories[${advIdx}]`);
    const advTitle = panelNonEmptyString(adv, "title", `advisories[${advIdx}]`);
    const sourceUrl = panelNonEmptyString(adv, "source_url", `advisories[${advIdx}]`);
    const docDigest = panelNonEmptyString(adv, "document_digest", `advisories[${advIdx}]`);
    const initialDate = panelNonEmptyString(adv, "initial_release_date", `advisories[${advIdx}]`);
    const currentDate = panelNonEmptyString(adv, "current_release_date", `advisories[${advIdx}]`);
    const sigVerified = panelBoolean(adv, "signature_verified", `advisories[${advIdx}]`);
    if (!sigVerified) {
      throw new OperatorApiError(502, `MSRC CSAF advisory ${trackingId} signature is not verified`);
    }

    for (const [vIdx, vItem] of panelArray(adv["vulnerabilities"], `advisories[${advIdx}].vulnerabilities`).entries()) {
      const vuln = panelRecord(vItem, `vulnerabilities[${vIdx}]`);
      const cveId = panelNonEmptyString(vuln, "cve_id", `vulnerabilities[${vIdx}]`);
      const baseScore = vuln["cvss_base_score"];
      if (typeof baseScore !== "number" || !Number.isFinite(baseScore) || baseScore < 0 || baseScore > 10) {
        throw new OperatorApiError(502, `invalid CVSS base score for ${cveId}`);
      }
      const temporalRaw = vuln["cvss_temporal_score"];
      if (
        temporalRaw !== null
        && (typeof temporalRaw !== "number" || !Number.isFinite(temporalRaw) || temporalRaw < 0 || temporalRaw > 10)
      ) {
        throw new OperatorApiError(502, `invalid CVSS temporal score for ${cveId}`);
      }
      const remediations: MsrcCsafRemediation[] = [];
      for (const [rIdx, rItem] of panelArray(vuln["remediations"], `vulnerabilities[${vIdx}].remediations`).entries()) {
        const rem = panelRecord(rItem, `remediations[${rIdx}]`);
        const expectedVal = rem["workaround_expected_value"];
        if (
          expectedVal !== null
          && typeof expectedVal !== "string"
          && typeof expectedVal !== "boolean"
          && typeof expectedVal !== "number"
        ) {
          throw new OperatorApiError(502, `invalid workaround_expected_value in ${cveId}`);
        }
        remediations.push({
          category: decodeEnum(
            panelNonEmptyString(rem, "category", `remediations[${rIdx}]`),
            ["vendor_fix", "workaround", "mitigation", "none_available"] as const,
            `remediations[${rIdx}].category`,
          ),
          product_ids: panelStringArray(rem["product_ids"], `remediations[${rIdx}].product_ids`),
          details: panelNonEmptyString(rem, "details", `remediations[${rIdx}]`),
          fixed_version: panelNullableString(rem, "fixed_version", `remediations[${rIdx}]`),
          kb_article: panelNullableString(rem, "kb_article", `remediations[${rIdx}]`),
          workaround_property: panelNullableString(rem, "workaround_property", `remediations[${rIdx}]`),
          workaround_expected_value: expectedVal,
          recommended_action_type: panelNullableString(rem, "recommended_action_type", `remediations[${rIdx}]`),
          url: panelNullableString(rem, "url", `remediations[${rIdx}]`),
        });
      }
      vulnMeta.set(cveId, {
        advisory_tracking_id: trackingId,
        advisory_title: advTitle,
        source_url: sourceUrl,
        document_digest: docDigest,
        initial_release_date: initialDate,
        current_release_date: currentDate,
        signature_verified: sigVerified,
        title: panelNonEmptyString(vuln, "title", `vulnerabilities[${vIdx}]`),
        severity: decodeEnum(
          panelNonEmptyString(vuln, "severity", `vulnerabilities[${vIdx}]`),
          MSRC_CSAF_SEVERITIES,
          `vulnerabilities[${vIdx}].severity`,
        ),
        cvss_base_score: baseScore,
        cvss_temporal_score: temporalRaw,
        cvss_vector: panelNonEmptyString(vuln, "cvss_vector", `vulnerabilities[${vIdx}]`),
        exploit_status: decodeEnum(
          panelNonEmptyString(vuln, "exploit_status", `vulnerabilities[${vIdx}]`),
          MSRC_CSAF_EXPLOIT_STATUSES,
          `vulnerabilities[${vIdx}].exploit_status`,
        ),
        publicly_disclosed: panelBoolean(vuln, "publicly_disclosed", `vulnerabilities[${vIdx}]`),
        remediations,
      });
    }
  }

  const rows: MsrcCsafControlRow[] = [];
  for (const [mIdx, mItem] of panelArray(root["vulnerability_mappings"], "msrc_csaf.vulnerability_mappings").entries()) {
    const mapping = panelRecord(mItem, `vulnerability_mappings[${mIdx}]`);
    const cveId = panelNonEmptyString(mapping, "cve_id", `vulnerability_mappings[${mIdx}]`);
    const meta = vulnMeta.get(cveId);
    if (!meta) {
      throw new OperatorApiError(502, `missing advisory vulnerability metadata for ${cveId}`);
    }
    const productIds = panelStringArray(mapping["product_ids"], `vulnerability_mappings[${mIdx}].product_ids`);
    const products = productIds.map((pid) => {
      const found = productMap.get(pid);
      if (!found) {
        throw new OperatorApiError(502, `missing product crosswalk for ${pid}`);
      }
      return found;
    });
    const disposition = decodeEnum(
      panelNonEmptyString(mapping, "disposition", `vulnerability_mappings[${mIdx}]`),
      MSRC_CSAF_DISPOSITIONS,
      `vulnerability_mappings[${mIdx}].disposition`,
    );
    const mappingState = decodeEnum(
      panelNonEmptyString(mapping, "mapping_state", `vulnerability_mappings[${mIdx}]`),
      MSRC_CSAF_MAPPING_STATES,
      `vulnerability_mappings[${mIdx}].mapping_state`,
    );
    const blockedReasons = panelStringArray(
      mapping["blocked_reasons"],
      `vulnerability_mappings[${mIdx}].blocked_reasons`,
    );
    const primaryResourceType = products.find((p) => p.canonical_resource_type !== null)?.canonical_resource_type
      ?? "unmapped";
    const firstCanonical = products.find(
      (p) => p.version_property && p.minimum_affected_version_inclusive && p.vulnerable_version_ceiling_exclusive,
    );
    const versionWindow = firstCanonical
      ? `${firstCanonical.version_property} in [${firstCanonical.minimum_affected_version_inclusive}, ${firstCanonical.vulnerable_version_ceiling_exclusive})`
      : "blocked";
    const expectedVal = mapping["workaround_expected_value"];
    if (
      expectedVal !== null
      && typeof expectedVal !== "string"
      && typeof expectedVal !== "boolean"
      && typeof expectedVal !== "number"
    ) {
      throw new OperatorApiError(502, `invalid crosswalk workaround_expected_value for ${cveId}`);
    }
    rows.push({
      cve_id: cveId,
      title: meta.title,
      advisory_tracking_id: meta.advisory_tracking_id,
      advisory_title: meta.advisory_title,
      source_url: meta.source_url,
      document_digest: meta.document_digest,
      initial_release_date: meta.initial_release_date,
      current_release_date: meta.current_release_date,
      signature_verified: meta.signature_verified,
      severity: meta.severity,
      cvss_base_score: meta.cvss_base_score,
      cvss_temporal_score: meta.cvss_temporal_score,
      cvss_vector: meta.cvss_vector,
      exploit_status: meta.exploit_status,
      publicly_disclosed: meta.publicly_disclosed,
      disposition,
      mapping_state: mappingState,
      product_ids: productIds,
      products,
      primary_resource_type: primaryResourceType,
      version_window: versionWindow,
      existing_rule_id: panelNullableString(mapping, "existing_rule_id", `vulnerability_mappings[${mIdx}]`),
      candidate_action_type: panelNullableString(mapping, "candidate_action_type", `vulnerability_mappings[${mIdx}]`),
      workaround_property: panelNullableString(mapping, "workaround_property", `vulnerability_mappings[${mIdx}]`),
      workaround_expected_value: expectedVal,
      blocked_reasons: blockedReasons,
      remediations: meta.remediations,
      evaluation_status: disposition === "ambiguous_or_blocked" || blockedReasons.length > 0
        ? "blocked"
        : "not_evaluated",
      exposure: "unknown",
      execution_authority: false,
    });
  }

  return {
    schema_version: schemaVersion,
    source_id: "msrc_csaf",
    source_revision: sourceRevision,
    advisories_digest: advisoriesDigest,
    crosswalk_digest: crosswalkDigest,
    rows,
  };
}

export const PINNED_MSRC_CSAF_RAW: unknown = msrcCsafCatalogJson;

export const PINNED_MSRC_CSAF_CATALOG: MsrcCsafCatalog = decodeMsrcCsafCatalog(PINNED_MSRC_CSAF_RAW);

export function filterMsrcCsafRows(
  rows: readonly MsrcCsafControlRow[],
  filters: MsrcCsafFilters,
): readonly MsrcCsafControlRow[] {
  const query = filters.q.trim().toLowerCase();
  return rows.filter((row) => {
    if (filters.severity && row.severity !== filters.severity) return false;
    if (filters.exploit_status && row.exploit_status !== filters.exploit_status) return false;
    if (filters.disposition && row.disposition !== filters.disposition) return false;
    if (filters.mapping_state && row.mapping_state !== filters.mapping_state) return false;
    if (filters.resource_type && row.primary_resource_type !== filters.resource_type) return false;
    if (!query) return true;
    return (
      row.cve_id.toLowerCase().includes(query)
      || row.title.toLowerCase().includes(query)
      || row.advisory_tracking_id.toLowerCase().includes(query)
      || row.advisory_title.toLowerCase().includes(query)
      || row.primary_resource_type.toLowerCase().includes(query)
      || row.product_ids.some((pid) => pid.toLowerCase().includes(query))
    );
  });
}

export function buildMsrcCsafFacets(
  rows: readonly MsrcCsafControlRow[],
): Readonly<Record<string, Readonly<Record<string, number>>>> {
  const bySeverity: Record<string, number> = {};
  const byExploit: Record<string, number> = {};
  const byDisposition: Record<string, number> = {};
  const byMapping: Record<string, number> = {};
  const byResourceType: Record<string, number> = {};
  for (const row of rows) {
    bySeverity[row.severity] = (bySeverity[row.severity] ?? 0) + 1;
    byExploit[row.exploit_status] = (byExploit[row.exploit_status] ?? 0) + 1;
    byDisposition[row.disposition] = (byDisposition[row.disposition] ?? 0) + 1;
    byMapping[row.mapping_state] = (byMapping[row.mapping_state] ?? 0) + 1;
    byResourceType[row.primary_resource_type] = (byResourceType[row.primary_resource_type] ?? 0) + 1;
  }
  return {
    by_severity: bySeverity,
    by_exploit_status: byExploit,
    by_disposition: byDisposition,
    by_mapping_state: byMapping,
    by_resource_type: byResourceType,
  };
}

export function msrcCsafStateFromSearch(search: URLSearchParams): {
  readonly filters: MsrcCsafFilters;
  readonly selected: string | null;
  readonly offset: number;
} {
  const rawOffset = Number.parseInt(search.get("offset") ?? "0", 10);
  return {
    filters: {
      severity: search.get("severity") ?? "",
      exploit_status: search.get("exploit_status") ?? "",
      disposition: search.get("disposition") ?? "",
      mapping_state: search.get("mapping_state") ?? "",
      resource_type: search.get("resource_type") ?? "",
      q: search.get("q") ?? "",
    },
    selected: search.get("cve"),
    offset: Number.isFinite(rawOffset) && rawOffset > 0 ? rawOffset : 0,
  };
}

export function msrcCsafHref(
  filters: MsrcCsafFilters,
  selected: string | null,
  offset = 0,
): string {
  return routeHref("rules", {
    params: {
      view: "controls",
      framework: "msrc-csaf",
      severity: filters.severity || undefined,
      exploit_status: filters.exploit_status || undefined,
      disposition: filters.disposition || undefined,
      mapping_state: filters.mapping_state || undefined,
      resource_type: filters.resource_type || undefined,
      q: filters.q || undefined,
      cve: selected ?? undefined,
      offset: offset > 0 ? String(offset) : undefined,
    },
  });
}
