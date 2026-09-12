import { apiBoolean, apiNumber, apiPositiveInteger, apiRecord, apiString, contractError } from "./api-contract";

export interface ComparisonMetric {
  readonly metric_id: string;
  readonly absolute_value: number;
  readonly sample_size: number;
  readonly lower_bound: number;
  readonly upper_bound: number;
}

export interface ComparisonArm {
  readonly sample_count: number;
  readonly window_start: string;
  readonly window_end: string;
  readonly metrics: readonly ComparisonMetric[];
}

export interface DashboardComparison {
  readonly publication_id: string;
  readonly cohort_id: string;
  readonly fdai_revision: string;
  readonly measurement_protocol_version: string;
  readonly published_at: string;
  readonly valid_until: string;
  readonly baseline: ComparisonArm;
  readonly treatment: ComparisonArm;
}

/** Decode display facts only; admission remains owned by the protected Core publisher. */
export function decodeDashboardComparison(value: unknown): DashboardComparison | null {
  if (value === undefined || value === null) return null;
  const label = "dashboard cohort comparison";
  const row = apiRecord(value, label);
  if (row["schema_version"] !== "1.0.0" || row["artifact_origin"] !== "governed_external" ||
      apiBoolean(row, "synthetic", label) ||
      apiBoolean(row, "execution_authority", label) ||
      apiBoolean(row, "promotion_authority", label)) {
    throw contractError("dashboard comparison is not governed authority-free evidence");
  }
  const baseline = decodeArm(row["baseline"], "baseline");
  const treatment = decodeArm(row["treatment"], "treatment");
  if (baseline.metrics.map((metric) => metric.metric_id).join("\n") !==
      treatment.metrics.map((metric) => metric.metric_id).join("\n")) {
    throw contractError("dashboard comparison metric identities differ between arms");
  }
  const publishedAt = timestamp(row, "published_at");
  const validUntil = timestamp(row, "valid_until");
  if (Date.parse(publishedAt) >= Date.parse(validUntil)) {
    throw contractError("dashboard comparison lifetime is invalid");
  }
  return {
    publication_id: apiString(row, "publication_id", label),
    cohort_id: apiString(row, "cohort_id", label),
    fdai_revision: apiString(row, "fdai_revision", label),
    measurement_protocol_version: apiString(row, "measurement_protocol_version", label),
    published_at: publishedAt,
    valid_until: validUntil,
    baseline,
    treatment,
  };
}

function decodeArm(value: unknown, arm: "baseline" | "treatment"): ComparisonArm {
  const label = `dashboard comparison ${arm}`;
  const row = apiRecord(value, label);
  const sampleCount = apiPositiveInteger(row, "sample_count", label);
  if (row["arm"] !== arm || sampleCount < 30 || !Array.isArray(row["metrics"]) ||
      row["metrics"].length === 0 || row["metrics"].length > 32 ||
      !Array.isArray(row["guards"]) || row["guards"].length === 0 || row["guards"].length > 32) {
    throw contractError("dashboard comparison arm is incomplete");
  }
  for (const raw of row["guards"]) {
    const guard = apiRecord(raw, label);
    if (apiBoolean(guard, "breached", label) || guard["observed_basis_points"] !== 0 ||
        guard["maximum_basis_points"] !== 0 ||
        apiPositiveInteger(guard, "sample_size", label) < sampleCount) {
      throw contractError("dashboard comparison guard evidence is incomplete or breached");
    }
  }
  const metrics = row["metrics"].map((raw): ComparisonMetric => {
    const metric = apiRecord(raw, label);
    const sampleSize = apiPositiveInteger(metric, "sample_size", label);
    const absolute = apiNumber(metric, "absolute_value", label);
    const lower = apiNumber(metric, "lower_bound", label);
    const upper = apiNumber(metric, "upper_bound", label);
    const id = apiString(metric, "metric_id", label);
    if (sampleSize < sampleCount || lower < 0 || lower > absolute || absolute > upper ||
        metric["confidence_level_basis_points"] !== 9500 ||
        (id === "auto_resolution_rate" && upper > 1)) {
      throw contractError("dashboard comparison interval or sample is inconsistent");
    }
    return {
      metric_id: id,
      absolute_value: absolute,
      sample_size: sampleSize,
      lower_bound: lower,
      upper_bound: upper,
    };
  });
  const keys = metrics.map((metric) => metric.metric_id);
  if (new Set(keys).size !== keys.length || keys.join("\n") !== [...keys].sort().join("\n")) {
    throw contractError("dashboard comparison metrics must be unique and ordered");
  }
  const start = timestamp(row, "window_start");
  const end = timestamp(row, "window_end");
  if (Date.parse(start) > Date.parse(end)) throw contractError("comparison evidence window is reversed");
  return { sample_count: sampleCount, window_start: start, window_end: end, metrics };
}

function timestamp(row: Record<string, unknown>, key: string): string {
  const value = apiString(row, key, "dashboard comparison");
  if (!/(Z|[+-]\d{2}:\d{2})$/.test(value) || !Number.isFinite(Date.parse(value))) {
    throw contractError("dashboard comparison timestamps require an explicit timezone");
  }
  return value;
}
