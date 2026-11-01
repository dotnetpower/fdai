import { OperatorApiError } from "../api";
import { routeHref } from "../router";
import manifestJson from "../../../rule-catalog/collected/msrc-csaf/crosswalk.json";
import shard00 from "../../../rule-catalog/collected/msrc-csaf/shards/crosswalk-00.json";
import shard01 from "../../../rule-catalog/collected/msrc-csaf/shards/crosswalk-01.json";
import shard02 from "../../../rule-catalog/collected/msrc-csaf/shards/crosswalk-02.json";
import shard03 from "../../../rule-catalog/collected/msrc-csaf/shards/crosswalk-03.json";
import shard04 from "../../../rule-catalog/collected/msrc-csaf/shards/crosswalk-04.json";
import shard05 from "../../../rule-catalog/collected/msrc-csaf/shards/crosswalk-05.json";
import shard06 from "../../../rule-catalog/collected/msrc-csaf/shards/crosswalk-06.json";
import shard07 from "../../../rule-catalog/collected/msrc-csaf/shards/crosswalk-07.json";
import shard08 from "../../../rule-catalog/collected/msrc-csaf/shards/crosswalk-08.json";
import shard09 from "../../../rule-catalog/collected/msrc-csaf/shards/crosswalk-09.json";
import shard10 from "../../../rule-catalog/collected/msrc-csaf/shards/crosswalk-10.json";
import shard11 from "../../../rule-catalog/collected/msrc-csaf/shards/crosswalk-11.json";
import shard12 from "../../../rule-catalog/collected/msrc-csaf/shards/crosswalk-12.json";
import shard13 from "../../../rule-catalog/collected/msrc-csaf/shards/crosswalk-13.json";
import shard14 from "../../../rule-catalog/collected/msrc-csaf/shards/crosswalk-14.json";
import shard15 from "../../../rule-catalog/collected/msrc-csaf/shards/crosswalk-15.json";
import shard16 from "../../../rule-catalog/collected/msrc-csaf/shards/crosswalk-16.json";
import shard17 from "../../../rule-catalog/collected/msrc-csaf/shards/crosswalk-17.json";
import shard18 from "../../../rule-catalog/collected/msrc-csaf/shards/crosswalk-18.json";
import shard19 from "../../../rule-catalog/collected/msrc-csaf/shards/crosswalk-19.json";
import { computeCvePriorityTier, msrcCsafDisplayTitle } from "./msrc-csaf-guidance";
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
export type MsrcCsafAttackSurfaceTag =
  | "pre_auth_network"
  | "zero_click"
  | "scope_changed"
  | "wormable";
export type MsrcCsafKevSlaTier =
  | "immediate_24h"
  | "urgent_72h"
  | "high_14d"
  | "standard_30d"
  | "monitor_90d";
export type MsrcCsafVexJustification =
  | "component_not_present"
  | "vulnerable_code_not_in_execute_path"
  | "inline_mitigations_already_exist"
  | "patched_version_deployed"
  | "affected_requires_remediation"
  | "undetermined_evidence_gap";

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
  readonly year: string;
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
  // V31-V33: Attack-surface tags, KEV SLA tier, VEX justification, and composite risk score
  readonly attack_surface_tags: readonly MsrcCsafAttackSurfaceTag[];
  readonly kev_sla_tier: MsrcCsafKevSlaTier;
  readonly due_days: number;
  readonly vex_justification: MsrcCsafVexJustification;
  readonly risk_score: number;
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
  readonly year: string;
  readonly severity: string;
  readonly exploit_status: string;
  readonly disposition: string;
  readonly mapping_state: string;
  readonly resource_type: string;
  readonly exposure: string;
  // V34: Attack-surface, KEV SLA tier, and sort mode filters
  readonly attack_surface: string;
  readonly kev_sla_tier: string;
  readonly sort: string;
  readonly q: string;
}

export const EMPTY_MSRC_CSAF_FILTERS: MsrcCsafFilters = {
  year: "",
  severity: "",
  exploit_status: "",
  disposition: "",
  mapping_state: "",
  resource_type: "",
  exposure: "",
  attack_surface: "",
  kev_sla_tier: "",
  sort: "",
  q: "",
};

function deriveAttackSurfaceAndRisk(
  vector: string,
  baseScore: number,
  severity: MsrcCsafSeverity,
  exploitStatus: MsrcCsafExploitStatus,
  exposure: MsrcCsafExposure,
): {
  readonly tags: readonly MsrcCsafAttackSurfaceTag[];
  readonly kevSlaTier: MsrcCsafKevSlaTier;
  readonly dueDays: number;
  readonly vexJustification: MsrcCsafVexJustification;
  readonly riskScore: number;
} {
  const metrics = new Map<string, string>();
  for (const part of vector.split("/").slice(1)) {
    const [k, v] = part.split(":");
    if (k && v) metrics.set(k, v);
  }
  const isNet = metrics.get("AV") === "N";
  const isLowAc = metrics.get("AC") === "L";
  const isUnauth = metrics.get("PR") === "N";
  const isZeroClick = metrics.get("UI") === "N";
  const isScopeChanged = metrics.get("S") === "C";
  const isHighCia = metrics.get("C") === "H" && metrics.get("I") === "H" && metrics.get("A") === "H";
  const isPreAuthNet = isNet && isUnauth;
  const isWormable = isPreAuthNet && isLowAc && isZeroClick && isHighCia;
  const tags: MsrcCsafAttackSurfaceTag[] = [];
  if (isPreAuthNet) tags.push("pre_auth_network");
  if (isZeroClick) tags.push("zero_click");
  if (isScopeChanged) tags.push("scope_changed");
  if (isWormable) tags.push("wormable");

  let kevSlaTier: MsrcCsafKevSlaTier = "monitor_90d";
  let dueDays = 90;
  if (exploitStatus === "exploited") {
    kevSlaTier = "immediate_24h";
    dueDays = 1;
  } else if (
    severity === "critical"
    || (exploitStatus === "exploitation_more_likely" && isPreAuthNet)
  ) {
    kevSlaTier = "urgent_72h";
    dueDays = 3;
  } else if (
    severity === "high"
    || exploitStatus === "exploitation_more_likely"
    || exploitStatus === "publicly_disclosed"
  ) {
    kevSlaTier = "high_14d";
    dueDays = 14;
  } else if (severity === "medium") {
    kevSlaTier = "standard_30d";
    dueDays = 30;
  }

  const vexMap: Readonly<Record<MsrcCsafExposure, MsrcCsafVexJustification>> = {
    affected: "affected_requires_remediation",
    mitigated: "inline_mitigations_already_exist",
    fixed: "patched_version_deployed",
    not_applicable: "vulnerable_code_not_in_execute_path",
    unknown: "undetermined_evidence_gap",
  };
  const vexJustification = vexMap[exposure];

  let riskScore = 0;
  if (exposure !== "fixed" && exposure !== "not_applicable") {
    const basePoints = Math.min(50, Math.max(0, baseScore * 5));
    const exploitPoints: Readonly<Record<MsrcCsafExploitStatus, number>> = {
      exploited: 30,
      exploitation_more_likely: 22,
      publicly_disclosed: 16,
      exploitation_less_likely: 8,
      exploitation_unlikely: 4,
      unproven: 2,
    };
    let vectorPoints = 0;
    if (isPreAuthNet) vectorPoints += 8;
    if (isZeroClick) vectorPoints += 5;
    if (isScopeChanged) vectorPoints += 4;
    if (isHighCia) vectorPoints += 3;
    const rawTotal = Math.min(100, basePoints + exploitPoints[exploitStatus] + vectorPoints);
    const mult = exposure === "mitigated" ? 0.45 : exposure === "unknown" ? 0.75 : 1.0;
    riskScore = Math.round(rawTotal * mult * 10) / 10;
  }

  return { tags, kevSlaTier, dueDays, vexJustification, riskScore };
}

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
    // Q079: Reject control or bidi override characters in advisory and vulnerability titles
    if (/[\x00-\x1f\x7f\u202a-\u202e\u2066-\u2069]/.test(advTitle)) {
      throw new OperatorApiError(502, `MSRC CSAF advisory ${trackingId} title contains control/bidi chars`);
    }
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
      const vulnTitle = panelNonEmptyString(vuln, "title", `vulnerabilities[${vIdx}]`);
      if (/[\x00-\x1f\x7f\u202a-\u202e\u2066-\u2069]/.test(vulnTitle)) {
        throw new OperatorApiError(502, `MSRC CSAF vulnerability ${cveId} title contains control/bidi chars`);
      }
      const baseScore = vuln["cvss_base_score"];
      if (typeof baseScore !== "number" || !Number.isFinite(baseScore) || baseScore < 0 || baseScore > 10) {
        throw new OperatorApiError(502, `invalid CVSS base score for ${cveId}`);
      }
      const temporalRaw = vuln["cvss_temporal_score"];
      // Q080: Enforce temporalRaw <= baseScore when temporalRaw !== null
      if (
        temporalRaw !== null
        && (
          typeof temporalRaw !== "number"
          || !Number.isFinite(temporalRaw)
          || temporalRaw < 0
          || temporalRaw > 10
          || temporalRaw > baseScore
        )
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
      const sev = decodeEnum(
        panelNonEmptyString(vuln, "severity", `vulnerabilities[${vIdx}]`),
        MSRC_CSAF_SEVERITIES,
        `vulnerabilities[${vIdx}].severity`,
      );
      const exploitStatus = decodeEnum(
        panelNonEmptyString(vuln, "exploit_status", `vulnerabilities[${vIdx}]`),
        MSRC_CSAF_EXPLOIT_STATUSES,
        `vulnerabilities[${vIdx}].exploit_status`,
      );
      const disclosed = panelBoolean(vuln, "publicly_disclosed", `vulnerabilities[${vIdx}]`);
      // C33: Enforce CVSS band minimum and exploited -> publicly_disclosed invariant
      const minSeverityRank = baseScore >= 9.0 ? 3 : baseScore >= 7.0 ? 2 : baseScore >= 4.0 ? 1 : 0;
      const sevRank = { low: 0, medium: 1, high: 2, critical: 3 }[sev];
      if (sevRank < minSeverityRank) {
        throw new OperatorApiError(502, `MSRC CSAF severity ${sev} is below CVSS band for ${cveId}`);
      }
      if (exploitStatus === "exploited" && !disclosed) {
        throw new OperatorApiError(502, `MSRC CSAF exploited vulnerability ${cveId} MUST be publicly_disclosed`);
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
        severity: sev,
        cvss_base_score: baseScore,
        cvss_temporal_score: temporalRaw,
        cvss_vector: panelNonEmptyString(vuln, "cvss_vector", `vulnerabilities[${vIdx}]`),
        exploit_status: exploitStatus,
        publicly_disclosed: disclosed,
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
    const cveYearMatch = /^CVE-(\d{4})-/.exec(cveId);
    const year = cveYearMatch?.[1] ?? meta.initial_release_date.slice(0, 4);
    const derived = deriveAttackSurfaceAndRisk(
      meta.cvss_vector,
      meta.cvss_base_score,
      meta.severity,
      meta.exploit_status,
      "unknown",
    );
    rows.push({
      cve_id: cveId,
      year,
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
      attack_surface_tags: derived.tags,
      kev_sla_tier: derived.kevSlaTier,
      due_days: derived.dueDays,
      vex_justification: derived.vexJustification,
      risk_score: derived.riskScore,
      execution_authority: false,
    });
  }

  const exploitRank: Readonly<Record<MsrcCsafExploitStatus, number>> = {
    exploited: 5,
    exploitation_more_likely: 4,
    publicly_disclosed: 3,
    exploitation_less_likely: 2,
    exploitation_unlikely: 1,
    unproven: 0,
  };
  rows.sort((left, right) => {
    const expDiff = exploitRank[right.exploit_status] - exploitRank[left.exploit_status];
    if (expDiff !== 0) return expDiff;
    if (right.cvss_base_score !== left.cvss_base_score) {
      return right.cvss_base_score - left.cvss_base_score;
    }
    if (right.current_release_date !== left.current_release_date) {
      return right.current_release_date.localeCompare(left.current_release_date);
    }
    return left.cve_id.localeCompare(right.cve_id);
  });

  return {
    schema_version: schemaVersion,
    source_id: "msrc_csaf",
    source_revision: sourceRevision,
    advisories_digest: advisoriesDigest,
    crosswalk_digest: crosswalkDigest,
    rows,
  };
}

const SHARDS = [
  shard00,
  shard01,
  shard02,
  shard03,
  shard04,
  shard05,
  shard06,
  shard07,
  shard08,
  shard09,
  shard10,
  shard11,
  shard12,
  shard13,
  shard14,
  shard15,
  shard16,
  shard17,
  shard18,
  shard19,
] as const;

export const PINNED_MSRC_CSAF_RAW: unknown = {
  schema_version: manifestJson.schema_version,
  source_id: manifestJson.source_id,
  source_revision: manifestJson.source_revision,
  advisories_digest: manifestJson.advisories_digest,
  crosswalk_digest: manifestJson.crosswalk_digest,
  product_mappings: manifestJson.product_mappings,
  advisories: SHARDS.flatMap((shard) => shard.advisories),
  vulnerability_mappings: SHARDS.flatMap((shard) => shard.vulnerability_mappings),
};

export const PINNED_MSRC_CSAF_CATALOG: MsrcCsafCatalog = decodeMsrcCsafCatalog(PINNED_MSRC_CSAF_RAW);

export function filterMsrcCsafRows(
  rows: readonly MsrcCsafControlRow[],
  filters: MsrcCsafFilters,
): readonly MsrcCsafControlRow[] {
  const tokens = filters.q
    .trim()
    .toLowerCase()
    .split(/\s+/)
    .filter(Boolean);
  const filtered = rows.filter((row) => {
    if (filters.year && row.year !== filters.year) return false;
    if (filters.severity && row.severity !== filters.severity) return false;
    if (filters.exploit_status && row.exploit_status !== filters.exploit_status) return false;
    if (filters.disposition && row.disposition !== filters.disposition) return false;
    if (filters.mapping_state && row.mapping_state !== filters.mapping_state) return false;
    if (filters.resource_type && row.primary_resource_type !== filters.resource_type) return false;
    if (filters.exposure && row.exposure !== filters.exposure) return false;
    if (
      filters.attack_surface
      && !row.attack_surface_tags.includes(filters.attack_surface as MsrcCsafAttackSurfaceTag)
    ) {
      return false;
    }
    if (filters.kev_sla_tier && row.kev_sla_tier !== filters.kev_sla_tier) return false;
    if (tokens.length === 0) return true;
    // C32, V35 & TR48: Multi-token AND search across CVE, English/Korean title, product, rule, action, workaround, KB, SLA, and priority tier
    return tokens.every(
      (query) =>
        row.cve_id.toLowerCase().includes(query)
        || row.year.toLowerCase().includes(query)
        || row.title.toLowerCase().includes(query)
        || msrcCsafDisplayTitle(row, "ko").toLowerCase().includes(query)
        || row.advisory_tracking_id.toLowerCase().includes(query)
        || row.advisory_title.toLowerCase().includes(query)
        || row.primary_resource_type.toLowerCase().includes(query)
        || row.exploit_status.toLowerCase().includes(query)
        || row.kev_sla_tier.toLowerCase().includes(query)
        || computeCvePriorityTier(row).toLowerCase() === query
        || (row.existing_rule_id?.toLowerCase().includes(query) ?? false)
        || (row.candidate_action_type?.toLowerCase().includes(query) ?? false)
        || (row.workaround_property?.toLowerCase().includes(query) ?? false)
        || row.product_ids.some((pid) => pid.toLowerCase().includes(query))
        || row.products.some((prod) => prod.product_name.toLowerCase().includes(query))
        || row.remediations.some((rem) => rem.kb_article?.toLowerCase().includes(query) ?? false),
    );
  });
  if (!filters.sort || filters.sort === "threat") {
    return filtered;
  }
  const sorted = [...filtered];
  if (filters.sort === "cvss") {
    sorted.sort((a, b) => b.cvss_base_score - a.cvss_base_score || a.cve_id.localeCompare(b.cve_id));
  } else if (filters.sort === "risk_score") {
    sorted.sort((a, b) => b.risk_score - a.risk_score || b.cvss_base_score - a.cvss_base_score || a.cve_id.localeCompare(b.cve_id));
  } else if (filters.sort === "recent") {
    sorted.sort((a, b) => b.current_release_date.localeCompare(a.current_release_date) || a.cve_id.localeCompare(b.cve_id));
  } else if (filters.sort === "cve") {
    sorted.sort((a, b) => a.cve_id.localeCompare(b.cve_id));
  }
  return sorted;
}

export function buildMsrcCsafFacets(
  rows: readonly MsrcCsafControlRow[],
): Readonly<Record<string, Readonly<Record<string, number>>>> {
  const byYear: Record<string, number> = {};
  const bySeverity: Record<string, number> = {};
  const byExploit: Record<string, number> = {};
  const byDisposition: Record<string, number> = {};
  const byMapping: Record<string, number> = {};
  const byResourceType: Record<string, number> = {};
  const byExposure: Record<string, number> = {};
  const byEvalStatus: Record<string, number> = {};
  const byAttackSurface: Record<string, number> = {};
  const byKevSla: Record<string, number> = {};
  for (const row of rows) {
    byYear[row.year] = (byYear[row.year] ?? 0) + 1;
    bySeverity[row.severity] = (bySeverity[row.severity] ?? 0) + 1;
    byExploit[row.exploit_status] = (byExploit[row.exploit_status] ?? 0) + 1;
    byDisposition[row.disposition] = (byDisposition[row.disposition] ?? 0) + 1;
    byMapping[row.mapping_state] = (byMapping[row.mapping_state] ?? 0) + 1;
    byResourceType[row.primary_resource_type] = (byResourceType[row.primary_resource_type] ?? 0) + 1;
    byExposure[row.exposure] = (byExposure[row.exposure] ?? 0) + 1;
    byEvalStatus[row.evaluation_status] = (byEvalStatus[row.evaluation_status] ?? 0) + 1;
    byKevSla[row.kev_sla_tier] = (byKevSla[row.kev_sla_tier] ?? 0) + 1;
    for (const tag of row.attack_surface_tags) {
      byAttackSurface[tag] = (byAttackSurface[tag] ?? 0) + 1;
    }
  }
  return {
    by_year: byYear,
    by_severity: bySeverity,
    by_exploit_status: byExploit,
    by_disposition: byDisposition,
    by_mapping_state: byMapping,
    by_resource_type: byResourceType,
    by_exposure: byExposure,
    by_evaluation_status: byEvalStatus,
    by_attack_surface: byAttackSurface,
    by_kev_sla_tier: byKevSla,
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
      year: search.get("year") ?? "",
      severity: search.get("severity") ?? "",
      exploit_status: search.get("exploit_status") ?? "",
      disposition: search.get("disposition") ?? "",
      mapping_state: search.get("mapping_state") ?? "",
      resource_type: search.get("resource_type") ?? "",
      exposure: search.get("exposure") ?? "",
      attack_surface: search.get("attack_surface") ?? "",
      kev_sla_tier: search.get("kev_sla_tier") ?? "",
      sort: search.get("sort") ?? "",
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
      year: filters.year || undefined,
      severity: filters.severity || undefined,
      exploit_status: filters.exploit_status || undefined,
      disposition: filters.disposition || undefined,
      mapping_state: filters.mapping_state || undefined,
      resource_type: filters.resource_type || undefined,
      exposure: filters.exposure || undefined,
      attack_surface: filters.attack_surface || undefined,
      kev_sla_tier: filters.kev_sla_tier || undefined,
      sort: filters.sort || undefined,
      q: filters.q || undefined,
      cve: selected ?? undefined,
      offset: offset > 0 ? String(offset) : undefined,
    },
  });
}

export function mergeMsrcCsafProjection(
  baseCatalog: MsrcCsafCatalog,
  projectionRaw: unknown,
): MsrcCsafCatalog {
  const root = panelRecord(projectionRaw, "msrc_csaf_projection");
  const sourceId = panelNonEmptyString(root, "source_id", "msrc_csaf_projection");
  if (sourceId !== "msrc_csaf") {
    throw new OperatorApiError(502, `unexpected MSRC CSAF source_id: ${sourceId}`);
  }
  const sourceRevision = panelNonEmptyString(root, "source_revision", "msrc_csaf_projection");
  const advisoriesDigest = panelNonEmptyString(root, "advisories_digest", "msrc_csaf_projection");
  const crosswalkDigest = panelNonEmptyString(root, "crosswalk_digest", "msrc_csaf_projection");
  if (
    sourceRevision !== baseCatalog.source_revision
    || advisoriesDigest !== baseCatalog.advisories_digest
    || crosswalkDigest !== baseCatalog.crosswalk_digest
  ) {
    throw new OperatorApiError(502, "MSRC CSAF projection digest or revision mismatch");
  }
  // Q081: Validate zero_risk_assurance.execution_authority === false when present
  if (root["zero_risk_assurance"] !== undefined && root["zero_risk_assurance"] !== null) {
    const zra = panelRecord(root["zero_risk_assurance"], "msrc_csaf_projection.zero_risk_assurance");
    if (panelBoolean(zra, "execution_authority", "zero_risk_assurance") !== false) {
      throw new OperatorApiError(502, "MSRC CSAF zero_risk_assurance MUST NOT carry execution_authority");
    }
  }
  const knownCves = new Set(baseCatalog.rows.map((r) => r.cve_id));
  const overrides = new Map<
    string,
    {
      readonly evaluation_status: "evaluated" | "not_evaluated" | "blocked";
      readonly exposure: MsrcCsafExposure;
    }
  >();
  for (const [idx, item] of panelArray(root["controls"], "msrc_csaf_projection.controls").entries()) {
    const rec = panelRecord(item, `controls[${idx}]`);
    const cveId = panelNonEmptyString(rec, "cve_id", `controls[${idx}]`);
    // C34: Reject duplicate or uncataloged cve_ids in Operator projection
    if (!knownCves.has(cveId) || overrides.has(cveId)) {
      throw new OperatorApiError(502, `MSRC CSAF projection control ${cveId} is unknown or duplicated`);
    }
    const execAuth = panelBoolean(rec, "execution_authority", `controls[${idx}]`);
    if (execAuth !== false) {
      throw new OperatorApiError(502, `MSRC CSAF control ${cveId} MUST NOT carry execution_authority`);
    }
    const evalStatus = decodeEnum(
      panelNonEmptyString(rec, "evaluation_status", `controls[${idx}]`),
      ["evaluated", "not_evaluated", "blocked"] as const,
      `controls[${idx}].evaluation_status`,
    );
    const exposure = decodeEnum(
      panelNonEmptyString(rec, "exposure", `controls[${idx}]`),
      MSRC_CSAF_EXPOSURES,
      `controls[${idx}].exposure`,
    );
    overrides.set(cveId, { evaluation_status: evalStatus, exposure });
  }
  if (overrides.size === 0) {
    return baseCatalog;
  }
  return {
    ...baseCatalog,
    rows: baseCatalog.rows.map((row) => {
      const ov = overrides.get(row.cve_id);
      if (!ov) return row;
      const derived = deriveAttackSurfaceAndRisk(
        row.cvss_vector,
        row.cvss_base_score,
        row.severity,
        row.exploit_status,
        ov.exposure,
      );
      return {
        ...row,
        evaluation_status: ov.evaluation_status,
        exposure: ov.exposure,
        vex_justification: derived.vexJustification,
        risk_score: derived.riskScore,
      };
    }),
  };
}

export interface MsrcCsafPostureSummary {
  readonly total: number;
  readonly exploitedCount: number;
  readonly wormableCount: number;
  readonly zeroClickCount: number;
  readonly preAuthNetworkCount: number;
  readonly criticalCount: number;
  readonly immediate24hCount: number;
  readonly mappedCount: number;
}

export function summarizeMsrcCsafPosture(
  rows: readonly MsrcCsafControlRow[],
): MsrcCsafPostureSummary {
  let exploitedCount = 0;
  let wormableCount = 0;
  let zeroClickCount = 0;
  let preAuthNetworkCount = 0;
  let criticalCount = 0;
  let immediate24hCount = 0;
  let mappedCount = 0;
  for (const row of rows) {
    if (row.exploit_status === "exploited") exploitedCount += 1;
    if (row.attack_surface_tags.some((tag) => tag === "wormable")) wormableCount += 1;
    if (row.attack_surface_tags.some((tag) => tag === "zero_click")) zeroClickCount += 1;
    if (row.attack_surface_tags.some((tag) => tag === "pre_auth_network")) preAuthNetworkCount += 1;
    if (row.severity === "critical") criticalCount += 1;
    if (row.kev_sla_tier === "immediate_24h") immediate24hCount += 1;
    if (row.mapping_state === "full") mappedCount += 1;
  }
  return {
    total: rows.length,
    exploitedCount,
    wormableCount,
    zeroClickCount,
    preAuthNetworkCount,
    criticalCount,
    immediate24hCount,
    mappedCount,
  };
}

function escapeCsvCell(raw: string): string {
  const safe = /^[=+\-@\t\r]/.test(raw) ? `'${raw}` : raw;
  return `"${safe.replace(/"/g, '""')}"`;
}

export function exportMsrcCsafRowsCsv(rows: readonly MsrcCsafControlRow[]): string {
  const header = [
    "cve_id",
    "advisory_tracking_id",
    "year",
    "severity",
    "cvss_base_score",
    "risk_score",
    "exploit_status",
    "kev_sla_tier",
    "due_days",
    "primary_resource_type",
    "version_window",
    "disposition",
    "exposure",
    "vex_justification",
    "title",
  ].join(",");
  const lines = rows.map((row) =>
    [
      escapeCsvCell(row.cve_id),
      escapeCsvCell(row.advisory_tracking_id),
      escapeCsvCell(row.year),
      escapeCsvCell(row.severity),
      row.cvss_base_score.toFixed(1),
      row.risk_score.toFixed(1),
      escapeCsvCell(row.exploit_status),
      escapeCsvCell(row.kev_sla_tier),
      String(row.due_days),
      escapeCsvCell(row.primary_resource_type),
      escapeCsvCell(row.version_window),
      escapeCsvCell(row.disposition),
      escapeCsvCell(row.exposure),
      escapeCsvCell(row.vex_justification),
      escapeCsvCell(row.title),
    ].join(","),
  );
  return [header, ...lines].join("\n");
}

export function exportMsrcCsafRowsJson(
  catalog: MsrcCsafCatalog,
  rows: readonly MsrcCsafControlRow[],
): string {
  return JSON.stringify(
    {
      schema_version: catalog.schema_version,
      source_id: catalog.source_id,
      source_revision: catalog.source_revision,
      advisories_digest: catalog.advisories_digest,
      crosswalk_digest: catalog.crosswalk_digest,
      execution_authority: false,
      exported_count: rows.length,
      posture: summarizeMsrcCsafPosture(rows),
      rows: rows.map((r) => ({
        cve_id: r.cve_id,
        advisory_tracking_id: r.advisory_tracking_id,
        year: r.year,
        title: r.title,
        severity: r.severity,
        cvss_base_score: r.cvss_base_score,
        risk_score: r.risk_score,
        exploit_status: r.exploit_status,
        kev_sla_tier: r.kev_sla_tier,
        due_days: r.due_days,
        attack_surface_tags: r.attack_surface_tags,
        primary_resource_type: r.primary_resource_type,
        version_window: r.version_window,
        disposition: r.disposition,
        exposure: r.exposure,
        vex_justification: r.vex_justification,
        execution_authority: false,
      })),
    },
    null,
    2,
  );
}

export interface MsrcCsafSevenSafeguardPlan {
  readonly cve_id: string;
  readonly action_type: string;
  readonly stop_condition: string;
  readonly tested_rollback_plan: string;
  readonly blast_radius_limit: number;
  readonly dry_run_required: true;
  readonly logical_target_lock: string;
  readonly idempotency_key: string;
  readonly two_phase_audit_required: true;
  readonly distinct_approver_executor_required: true;
  readonly effect_verification_contract: string;
  readonly kev_sla_tier: MsrcCsafKevSlaTier;
  readonly due_days: number;
  readonly vex_justification: MsrcCsafVexJustification;
  readonly risk_score: number;
  readonly mode: "shadow";
  readonly execution_authority: false;
}

export function buildSevenSafeguardPlan(
  row: MsrcCsafControlRow,
  sourceRevision: string,
): MsrcCsafSevenSafeguardPlan {
  const actionType = row.candidate_action_type ?? "ops.apply-security-update";
  const isCanaryRequired = row.exploit_status === "exploited" || row.severity === "critical";
  const blastLimit = isCanaryRequired ? 1 : Math.max(1, Math.min(5, row.product_ids.length));
  return {
    cve_id: row.cve_id,
    action_type: actionType,
    stop_condition: `Abort immediately on health-probe failure, error-rate > 1%, or revision drift from ${sourceRevision}.`,
    tested_rollback_plan: `Restore pre-patch resource snapshot or version pin prior to ${row.cve_id} update (${row.version_window}).`,
    blast_radius_limit: blastLimit,
    dry_run_required: true,
    logical_target_lock: `lock:${row.primary_resource_type}:${row.cve_id}`,
    idempotency_key: `idem:${sourceRevision}:${row.cve_id}:${actionType}`,
    two_phase_audit_required: true,
    distinct_approver_executor_required: true,
    effect_verification_contract: `Observe independent post-action inventory generation and verify ${row.primary_resource_type} exits ${row.version_window}.`,
    kev_sla_tier: row.kev_sla_tier,
    due_days: row.due_days,
    vex_justification: row.vex_justification,
    risk_score: row.risk_score,
    mode: "shadow",
    execution_authority: false,
  };
}

export interface MsrcCsafZeroRiskAssuranceSummary {
  readonly status: "certified_zero_risk" | "at_risk" | "coverage_incomplete";
  readonly posture_score: number;
  readonly affected_count: number;
  readonly mitigated_count: number;
  readonly fixed_count: number;
  readonly unknown_count: number;
  readonly exploited_affected_count: number;
  readonly wormable_affected_count: number;
  readonly kev_sla_breach_count: number;
  readonly change_freeze_recommended: boolean;
  readonly execution_authority: false;
}

export function evaluateCatalogZeroRiskAssurance(
  rows: readonly MsrcCsafControlRow[],
): MsrcCsafZeroRiskAssuranceSummary {
  let affected = 0;
  let mitigated = 0;
  let fixed = 0;
  let unknown = 0;
  let exploitedAffected = 0;
  let wormableAffected = 0;
  let criticalAffected = 0;
  let kevSlaBreaches = 0;
  for (const row of rows) {
    if (row.exposure === "affected") {
      affected += 1;
      if (row.exploit_status === "exploited") exploitedAffected += 1;
      if (row.severity === "critical") criticalAffected += 1;
      if (row.attack_surface_tags.some((tag) => tag === "wormable")) wormableAffected += 1;
      if (row.kev_sla_tier === "immediate_24h" || row.kev_sla_tier === "urgent_72h") {
        kevSlaBreaches += 1;
      }
    } else if (row.exposure === "mitigated") {
      mitigated += 1;
    } else if (row.exposure === "fixed") {
      fixed += 1;
    } else if (row.exposure === "unknown") {
      unknown += 1;
    }
  }
  const status = affected > 0
    ? "at_risk"
    : unknown > 0
      ? "coverage_incomplete"
      : "certified_zero_risk";
  const deduction =
    exploitedAffected * 35
    + criticalAffected * 25
    + affected * 10
    + mitigated * 3
    + Math.min(20, unknown > 0 ? 15 : 0);
  return {
    status,
    posture_score: Math.max(0, 100 - Math.min(100, deduction)),
    affected_count: affected,
    mitigated_count: mitigated,
    fixed_count: fixed,
    unknown_count: unknown,
    exploited_affected_count: exploitedAffected,
    wormable_affected_count: wormableAffected,
    kev_sla_breach_count: kevSlaBreaches,
    change_freeze_recommended: exploitedAffected > 0 || wormableAffected > 0 || kevSlaBreaches > 0,
    execution_authority: false,
  };
}
