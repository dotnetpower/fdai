import {
  panelArray,
  panelBoolean,
  panelNonNegativeInteger,
  panelRecord,
  panelString,
} from "./routes/panel-decode";

export type {
  CostGovernanceAnalytics,
  CostGovernanceBudget,
  CostGovernanceProjection,
  CostGovernanceRecommendation,
  CostGovernanceSurface,
  CostGovernanceTrendPoint,
} from "./api-cost-governance-projection";

export interface CostGovernanceAvailability {
  readonly available: boolean;
  readonly enabled: boolean;
  readonly access_allowed: boolean;
  readonly availability_reasons: readonly string[];
  readonly reason: string | null;
  readonly activation_revision: number | null;
  readonly package_version: string | null;
  readonly image_digest: string | null;
  readonly asset_manifest_digest: string | null;
  readonly semantic_profile_digest: string | null;
  readonly ontology_release_digest: string | null;
}

export interface CostGovernanceSettings {
  readonly available: boolean;
  readonly enabled: boolean;
  readonly can_manage: boolean;
  readonly activation_revision: number | null;
  readonly availability_reasons: readonly string[];
  readonly package_version: string | null;
}

export function decodeCostGovernanceAvailability(value: unknown): CostGovernanceAvailability {
  const record = panelRecord(value, "cost governance availability");
  const revision = record["activation_revision"];
  const optionalString = (key: string): string | null => record[key] === null
    ? null
    : panelString(record, key, "cost governance availability");
  return {
    available: panelBoolean(record, "available", "cost governance availability"),
    enabled: panelBoolean(record, "enabled", "cost governance availability"),
    access_allowed: panelBoolean(record, "access_allowed", "cost governance availability"),
    availability_reasons: panelArray(
      record["availability_reasons"],
      "availability_reasons",
    ).map((item) => {
      if (typeof item !== "string") throw new Error("Invalid Cost Governance availability reason");
      return item;
    }),
    reason: record["reason"] === null
      ? null
      : panelString(record, "reason", "cost governance availability"),
    activation_revision: revision === null
      ? null
      : panelNonNegativeInteger(record, "activation_revision", "cost governance availability"),
    package_version: optionalString("package_version"),
    image_digest: optionalString("image_digest"),
    asset_manifest_digest: optionalString("asset_manifest_digest"),
    semantic_profile_digest: optionalString("semantic_profile_digest"),
    ontology_release_digest: optionalString("ontology_release_digest"),
  };
}

export function decodeCostGovernanceSettings(value: unknown): CostGovernanceSettings {
  const record = panelRecord(value, "cost governance settings");
  const revision = record["activation_revision"];
  return {
    available: panelBoolean(record, "available", "cost governance settings"),
    enabled: panelBoolean(record, "enabled", "cost governance settings"),
    can_manage: panelBoolean(record, "can_manage", "cost governance settings"),
    activation_revision: revision === null
      ? null
      : panelNonNegativeInteger(record, "activation_revision", "cost governance settings"),
    availability_reasons: panelArray(
      record["availability_reasons"],
      "availability_reasons",
    ).map((item) => {
      if (typeof item !== "string") throw new Error("Invalid Cost Governance settings reason");
      return item;
    }),
    package_version: record["package_version"] === null
      ? null
      : panelString(record, "package_version", "cost governance settings"),
  };
}
