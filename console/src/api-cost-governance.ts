import {
  panelArray,
  panelBoolean,
  panelNonNegativeInteger,
  panelRecord,
  panelString,
} from "./routes/panel-decode";

export type CostGovernanceSurface =
  | "overview"
  | "resource-efficiency"
  | "optimization-cases"
  | "outcomes";

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

export interface CostGovernanceProjection {
  readonly surface: CostGovernanceSurface;
  readonly complete: boolean;
  readonly source_authority: string;
  readonly items: readonly Readonly<Record<string, unknown>>[];
  readonly suppressed_count: number;
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

export function decodeCostGovernanceProjection(value: unknown): CostGovernanceProjection {
  const record = panelRecord(value, "cost governance projection");
  const surface = panelString(record, "surface", "cost governance projection");
  if (!["overview", "resource-efficiency", "optimization-cases", "outcomes"].includes(surface)) {
    throw new Error("Unknown Cost Governance surface");
  }
  return {
    surface: surface as CostGovernanceSurface,
    complete: panelBoolean(record, "complete", "cost governance projection"),
    source_authority: panelString(record, "source_authority", "cost governance projection"),
    items: panelArray(record["items"], "items").map((item) => panelRecord(item, "item")),
    suppressed_count: panelNonNegativeInteger(
      record,
      "suppressed_count",
      "cost governance projection",
    ),
  };
}
