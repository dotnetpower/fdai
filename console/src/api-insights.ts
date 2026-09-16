import type { AutonomyPayload, DashboardKpi, EffectiveScope } from "./types";
import { decodeDashboardComparison } from "./dashboard-comparison";
import {
  apiBoolean,
  apiNonNegativeInteger,
  apiNullableString,
  apiNumber,
  apiNumberRecord,
  apiPositiveInteger,
  apiRatio,
  apiRecord,
  apiString,
  contractError,
} from "./api-contract";

export function decodeDashboardKpi(value: unknown): DashboardKpi {
  const root = apiRecord(value, "dashboard KPI");
  const eventCount = apiNonNegativeInteger(root, "event_count", "dashboard KPI");
  const auditSample = decodeAuditSample(root["audit_sample"], eventCount);
  const routingSample = decodeRoutingSample(root["routing_sample"]);
  const byTier = apiNumberRecord(root["by_tier"], "dashboard KPI.by_tier");
  const byOutcome = apiNumberRecord(root["by_outcome"], "dashboard KPI.by_outcome");
  if (routingSample !== undefined) {
    const counts = [...Object.values(byTier), ...Object.values(byOutcome)];
    if (counts.some((count) => !Number.isSafeInteger(count) || count < 0) ||
        Object.values(byOutcome).reduce((sum, count) => sum + count, 0) !== routingSample.row_count ||
        Object.values(byTier).reduce((sum, count) => sum + count, 0) > routingSample.row_count) {
      throw contractError("dashboard routing distribution contradicts its canonical sample");
    }
  }
  return {
    event_count: eventCount,
    shadow_share: apiRatio(root, "shadow_share", "dashboard KPI"),
    enforce_share: apiRatio(root, "enforce_share", "dashboard KPI"),
    hil_pending: apiNonNegativeInteger(root, "hil_pending", "dashboard KPI"),
    by_action_kind: apiNumberRecord(root["by_action_kind"], "dashboard KPI.by_action_kind"),
    by_outcome: byOutcome,
    by_tier: byTier,
    last_recorded_at: apiNullableString(root, "last_recorded_at", "dashboard KPI"),
    audit_sample: auditSample,
    ...(routingSample ? { routing_sample: routingSample } : {}),
  };
}

function decodeRoutingSample(value: unknown): DashboardKpi["routing_sample"] {
  if (value === undefined) return undefined;
  const context = "dashboard KPI.routing_sample";
  const row = apiRecord(value, context);
  const count = apiNonNegativeInteger(row, "row_count", context);
  const sample = decodeAuditSample(value, count);
  if (sample === null || row["action_kind"] !== "measurement.control_loop.v1") {
    throw contractError("dashboard KPI routing source is invalid");
  }
  return {
    ...sample,
    action_kind: "measurement.control_loop.v1",
    window_days: apiPositiveInteger(row, "window_days", context),
  };
}

function decodeAuditSample(value: unknown, eventCount: number): DashboardKpi["audit_sample"] {
  if (value === undefined || value === null) return null;
  const sample = apiRecord(value, "dashboard KPI.audit_sample");
  const context = "dashboard KPI.audit_sample";
  const result = {
    from_seq: sample["from_seq"] === null ? null : apiPositiveInteger(sample, "from_seq", context),
    through_seq: sample["through_seq"] === null ? null : apiPositiveInteger(sample, "through_seq", context),
    row_count: apiNonNegativeInteger(sample, "row_count", context),
    limit: apiPositiveInteger(sample, "limit", context),
  };
  const empty = result.row_count === 0;
  if (
    result.row_count !== eventCount || result.row_count > result.limit ||
    empty !== (result.from_seq === null && result.through_seq === null) ||
    (!empty && (
      result.from_seq === null || result.through_seq === null ||
      result.from_seq > result.through_seq
    ))
  ) throw contractError("dashboard KPI.audit_sample is inconsistent");
  return result;
}

export function decodeAutonomyPayload(value: unknown): AutonomyPayload {
  const root = apiRecord(value, "autonomy measurement");
  if (root["schema_version"] !== "1.0.0") {
    throw contractError("autonomy measurement.schema_version MUST be 1.0.0");
  }
  const sampleSize = apiNonNegativeInteger(root, "sample_size", "autonomy measurement");
  const source = apiRecord(root["source"], "autonomy measurement.source");
  const sourceKind = apiString(source, "kind", "autonomy measurement.source");
  if (sourceKind !== "audit" && sourceKind !== "measurement" && sourceKind !== "synthetic") {
    throw contractError("autonomy measurement.source.kind MUST be audit, measurement, or synthetic");
  }
  const success = apiRecord(root["success"], "autonomy measurement.success");
  const leading = apiRecord(root["leading"], "autonomy measurement.leading");
  const rules = apiRecord(root["rules"], "autonomy measurement.rules");
  const tier = apiRecord(root["tier"], "autonomy measurement.tier");
  const bands = apiRecord(tier["bands"], "autonomy measurement.tier.bands");
  const attribution = apiRecord(root["attribution"], "autonomy measurement.attribution");
  const finalization = apiRecord(root["finalization"], "autonomy measurement.finalization");
  if (!Array.isArray(root["guards"])) {
    throw contractError("autonomy measurement.guards MUST be an array");
  }
  if (!Array.isArray(root["verticals"])) {
    throw contractError("autonomy measurement.verticals MUST be an array");
  }
  const autoResolution = decodeMetric(
    success["auto_resolution_rate"],
    "success.auto_resolution_rate",
    "higher",
    true,
  );
  const humanTouchpoints = decodeMetric(
    success["human_touchpoints_per_100"],
    "success.human_touchpoints_per_100",
    "lower",
  );
  const mttr = decodeMetric(success["mttr_seconds"], "success.mttr_seconds", "lower");
  const changeLeadTime = decodeMetric(
    success["change_lead_time_seconds"],
    "success.change_lead_time_seconds",
    "lower",
  );
  const costPerResolved = decodeMetric(
    success["cost_per_resolved_event_usd"],
    "success.cost_per_resolved_event_usd",
    "lower",
  );
  const metricSamples = decodeMetricSamples(root["metric_samples"]);
  const measurementGaps = decodeMeasurementGaps(root["measurement_gaps"]);
  const disagreement = decodeMetric(
    leading["mixed_model_disagreement_rate"],
    "leading.mixed_model_disagreement_rate",
    "lower",
    true,
  );
  const verifierFailure = decodeMetric(
    leading["verifier_failure_rate"],
    "leading.verifier_failure_rate",
    "lower",
    true,
  );
  const shadowDivergence = decodeMetric(
    leading["shadow_divergence_rate"],
    "leading.shadow_divergence_rate",
    "lower",
    true,
  );
  const verticals = root["verticals"].map((raw, index) => {
    const item = apiRecord(raw, `autonomy measurement.verticals[${index}]`);
    return {
      key: apiString(item, "key", "autonomy vertical"),
      events: apiNonNegativeInteger(item, "events", "autonomy vertical"),
      auto_resolved: apiNonNegativeInteger(item, "auto_resolved", "autonomy vertical"),
      open_risks: apiNonNegativeInteger(item, "open_risks", "autonomy vertical"),
      monthly_savings: apiNumber(item, "monthly_savings", "autonomy vertical"),
    };
  });
  const allowedVerticalKeys = new Set(["resilience", "change_safety", "cost", "unattributed"]);
  if (verticals.some((vertical) => !allowedVerticalKeys.has(vertical.key))) {
    throw contractError("autonomy measurement.verticals contains an unknown key");
  }
  if (new Set(verticals.map((vertical) => vertical.key)).size !== verticals.length) {
    throw contractError("autonomy measurement.verticals MUST have unique keys");
  }
  if (verticals.some((vertical) => vertical.auto_resolved > vertical.events)) {
    throw contractError("autonomy measurement.vertical auto_resolved exceeds events");
  }
  const attributedEvents = apiNonNegativeInteger(
    attribution,
    "attributed_events",
    "autonomy measurement.attribution",
  );
  const unattributedEvents = apiNonNegativeInteger(
    attribution,
    "unattributed_events",
    "autonomy measurement.attribution",
  );
  const attributionCoverage = attribution["coverage"] === null
    ? null
    : apiRatio(attribution, "coverage", "autonomy measurement.attribution");
  const attributionTotal = attributedEvents + unattributedEvents;
  const expectedCoverage = attributionTotal === 0 ? null : attributedEvents / attributionTotal;
  const verticalTotal = verticals.reduce((total, vertical) => total + vertical.events, 0);
  const unattributedVerticalEvents = verticals
    .filter((vertical) => vertical.key === "unattributed")
    .reduce((total, vertical) => total + vertical.events, 0);
  const attributedVerticalEvents = verticalTotal - unattributedVerticalEvents;
  if (
    verticalTotal !== sampleSize ||
    verticalTotal !== attributionTotal ||
    attributedVerticalEvents !== attributedEvents ||
    unattributedVerticalEvents !== unattributedEvents ||
    (expectedCoverage === null) !== (attributionCoverage === null) ||
    (expectedCoverage !== null && Math.abs(attributionCoverage! - expectedCoverage) > 1e-12)
  ) throw contractError("autonomy measurement.attribution is inconsistent");
  const finalizedEvents = apiNonNegativeInteger(
    finalization,
    "finalized_events",
    "autonomy measurement.finalization",
  );
  const pendingEvents = apiNonNegativeInteger(
    finalization,
    "pending_events",
    "autonomy measurement.finalization",
  );
  const adverseEvents = apiNonNegativeInteger(
    finalization,
    "adverse_events",
    "autonomy measurement.finalization",
  );
  if (adverseEvents > finalizedEvents || finalizedEvents + pendingEvents > attributionTotal) {
    throw contractError("autonomy measurement.finalization is inconsistent");
  }
  const autoResolvedEvents = verticals.reduce(
    (total, vertical) => total + vertical.auto_resolved,
    0,
  );
  if (autoResolvedEvents !== finalizedEvents - adverseEvents) {
    throw contractError("autonomy measurement finalized outcomes are inconsistent");
  }
  const expectedAutoResolution = sampleSize === 0 ? null : autoResolvedEvents / sampleSize;
  if (
    autoResolution.value !== null &&
    (expectedAutoResolution === null ||
      Math.abs(autoResolution.value - expectedAutoResolution) > 1e-12)
  ) {
    throw contractError("autonomy measurement auto-resolution rate is inconsistent");
  }
  const tierMix = decodeFiniteNumberRecord(tier["mix"], "autonomy measurement.tier.mix");
  const tierKeys = new Set(["t0", "t1", "t2"]);
  if (
    Object.entries(tierMix).some(([key, share]) =>
      !tierKeys.has(key) || share < 0 || share > 1
    ) ||
    Object.values(tierMix).reduce((sum, share) => sum + share, 0) > 1 + 1e-12
  ) {
    throw contractError("autonomy measurement.tier.mix is inconsistent");
  }
  const tierBands = Object.fromEntries(
    Object.entries(bands).map(([key, raw]) => {
      if (
        !tierKeys.has(key) ||
        !Array.isArray(raw) ||
        raw.length !== 2 ||
        raw.some((item) => typeof item !== "number" || !Number.isFinite(item)) ||
        raw[0] < 0 ||
        raw[1] > 1 ||
        raw[0] > raw[1]
      ) {
        throw contractError(`autonomy measurement.tier.bands.${key} is invalid`);
      }
      return [key, [raw[0], raw[1]] as const];
    }),
  );
  const rulesEvidence = root["rules_evidence"];
  if (rulesEvidence !== undefined && rulesEvidence !== "measured" && rulesEvidence !== "unavailable") {
    throw contractError("autonomy rule evidence state is invalid");
  }
  return {
    synthetic: apiBoolean(root, "synthetic", "autonomy measurement"),
    ...(root["comparison"] !== undefined
      ? { comparison: decodeDashboardComparison(root["comparison"]) }
      : {}),
    ...(rulesEvidence !== undefined ? { rules_evidence: rulesEvidence } : {}),
    window_days: apiPositiveInteger(root, "window_days", "autonomy measurement"),
    sample_size: sampleSize,
    confidence: root["confidence"] === null
      ? null
      : apiRatio(root, "confidence", "autonomy measurement"),
    source: {
      name: apiString(source, "name", "autonomy measurement.source"),
      kind: sourceKind,
      as_of: apiNullableString(source, "as_of", "autonomy measurement.source"),
    },
    rules: {
      active: apiNonNegativeInteger(rules, "active", "autonomy measurement.rules"),
      candidates_30d: apiNonNegativeInteger(rules, "candidates_30d", "autonomy measurement.rules"),
      promoted_30d: apiNonNegativeInteger(rules, "promoted_30d", "autonomy measurement.rules"),
    },
    success: {
      auto_resolution_rate: autoResolution,
      human_touchpoints_per_100: humanTouchpoints,
      mttr_seconds: mttr,
      change_lead_time_seconds: changeLeadTime,
      cost_per_resolved_event_usd: costPerResolved,
    },
    metric_samples: metricSamples,
    measurement_gaps: measurementGaps,
    leading: {
      mixed_model_disagreement_rate: disagreement,
      verifier_failure_rate: verifierFailure,
      shadow_divergence_rate: shadowDivergence,
    },
    guards: root["guards"].map((raw, index) => {
      const item = apiRecord(raw, `autonomy measurement.guards[${index}]`);
      return {
        key: apiString(item, "key", "autonomy guard"),
        value: apiNumber(item, "value", "autonomy guard"),
        baseline: apiNumber(item, "baseline", "autonomy guard"),
        threshold: apiNumber(item, "threshold", "autonomy guard"),
        ok: apiBoolean(item, "ok", "autonomy guard"),
      };
    }),
    finalization: {
      finalized_events: finalizedEvents,
      pending_events: pendingEvents,
      adverse_events: adverseEvents,
    },
    attribution: {
      attributed_events: attributedEvents,
      unattributed_events: unattributedEvents,
      coverage: attributionCoverage,
    },
    verticals,
    tier: {
      mix: tierMix,
      bands: tierBands,
    },
    trend: Object.fromEntries(
      Object.entries(apiRecord(root["trend"], "autonomy measurement.trend")).map(([key, raw]) => {
        if (!Array.isArray(raw) || raw.some((item) => typeof item !== "number" || !Number.isFinite(item))) {
          throw contractError(`autonomy measurement.trend.${key} MUST be finite numbers`);
        }
        return [key, raw];
      }),
    ),
  };
}

function decodeMetricSamples(value: unknown): AutonomyPayload["metric_samples"] {
  const samples = apiRecord(value, "autonomy measurement.metric_samples");
  const context = "autonomy measurement.metric_samples";
  const result = {
    auto_resolution_rate: apiNonNegativeInteger(samples, "auto_resolution_rate", context),
    human_touchpoints_per_100: apiNonNegativeInteger(
      samples,
      "human_touchpoints_per_100",
      context,
    ),
    mttr_seconds: apiNonNegativeInteger(samples, "mttr_seconds", context),
    change_lead_time_seconds: apiNonNegativeInteger(
      samples,
      "change_lead_time_seconds",
      context,
    ),
    cost_per_resolved_event_usd: apiNonNegativeInteger(
      samples,
      "cost_per_resolved_event_usd",
      context,
    ),
  };
  if (Object.keys(samples).length !== Object.keys(result).length) {
    throw contractError("autonomy measurement.metric_samples contains unknown metrics");
  }
  return result;
}

function decodeMeasurementGaps(value: unknown): readonly string[] {
  if (!Array.isArray(value) || value.some((item) => typeof item !== "string" || !item)) {
    throw contractError("autonomy measurement.measurement_gaps MUST be non-empty strings");
  }
  const gaps = value as string[];
  if (new Set(gaps).size !== gaps.length) {
    throw contractError("autonomy measurement.measurement_gaps MUST be unique");
  }
  const sourceMetrics = new Set([
    "mttr_seconds",
    "change_lead_time_seconds",
    "attributed_cost_usd",
  ]);
  for (const gap of gaps) {
    if (gap === "unattributed_human_input") continue;
    const [reason, metricId, extra] = gap.split(":");
    if (
      extra !== undefined
      || !["incomplete", "mixed_context", "missing_source"].includes(reason ?? "")
      || !sourceMetrics.has(metricId ?? "")
    ) {
      throw contractError(`autonomy measurement.measurement_gaps contains ${gap}`);
    }
  }
  return gaps;
}

function decodeMetric(
  value: unknown,
  label: string,
  expectedDirection: "higher" | "lower",
  ratio = false,
): AutonomyPayload["success"]["auto_resolution_rate"] {
  const item = apiRecord(value, `autonomy measurement.${label}`);
  const direction = apiString(item, "direction", `autonomy measurement.${label}`);
  if (direction !== expectedDirection) {
    throw contractError(
      `autonomy measurement.${label}.direction MUST be ${expectedDirection}`,
    );
  }
  const current = item["value"] === null
    ? null
    : apiNumber(item, "value", `autonomy measurement.${label}`);
  const baseline = item["baseline"] === null
    ? null
    : apiNumber(item, "baseline", `autonomy measurement.${label}`);
  if (
    current !== null && (current < 0 || (ratio && current > 1)) ||
    baseline !== null && (baseline < 0 || (ratio && baseline > 1))
  ) {
    throw contractError(`autonomy measurement.${label} is outside its valid range`);
  }
  return {
    value: current,
    baseline,
    direction,
  };
}

function decodeFiniteNumberRecord(value: unknown, label: string): Record<string, number> {
  const raw = apiRecord(value, label);
  const result: Record<string, number> = {};
  for (const [key, item] of Object.entries(raw)) {
    if (typeof item !== "number" || !Number.isFinite(item)) {
      throw contractError(`${label}.${key} MUST be a finite number`);
    }
    result[key] = item;
  }
  return result;
}

export function decodeScopeView(value: unknown): EffectiveScope {
  const root = apiRecord(value, "scope view");
  return {
    monitoring: decodeScopeAxis(root["monitoring"], "monitoring"),
    action: decodeScopeAxis(root["action"], "action"),
    executor_boundary: decodeExecutorBoundary(root["executor_boundary"]),
  };
}

function decodeScopeAxis(value: unknown, expected: "monitoring" | "action"): EffectiveScope["monitoring"] {
  const root = apiRecord(value, `scope view.${expected}`);
  const axis = root["axis"];
  if (axis !== expected) throw contractError(`scope view.${expected}.axis MUST be ${expected}`);
  if (!Array.isArray(root["entries"])) {
    throw contractError(`scope view.${expected}.entries MUST be an array`);
  }
  return {
    axis: expected,
    entries: root["entries"].map((raw, index) => {
      const item = apiRecord(raw, `scope view.${expected}.entries[${index}]`);
      return {
        address: apiString(item, "address", "scope entry"),
        level: apiScopeLevel(item["level"]),
        subscription: apiString(item, "subscription", "scope entry"),
        resource_group: apiNullableString(item, "resource_group", "scope entry"),
        state: apiScopeState(item["state"]),
      };
    }),
  };
}

function decodeExecutorBoundary(value: unknown): EffectiveScope["executor_boundary"] {
  const root = apiRecord(value, "scope view.executor_boundary");
  if (!Array.isArray(root["resource_groups"])) {
    throw contractError("scope view.executor_boundary.resource_groups MUST be an array");
  }
  return {
    resource_groups: root["resource_groups"].map((raw, index) => {
      if (typeof raw !== "string") {
        throw contractError(`scope view.executor_boundary.resource_groups[${index}] MUST be a string`);
      }
      return raw;
    }),
    note: apiNullableString(root, "note", "scope view.executor_boundary"),
  };
}

function apiScopeLevel(value: unknown): "subscription" | "resource_group" {
  if (value === "subscription" || value === "resource_group") return value;
  throw contractError("scope entry.level MUST be subscription or resource_group");
}

function apiScopeState(value: unknown): "included" | "excluded" {
  if (value === "included" || value === "excluded") return value;
  throw contractError("scope entry.state MUST be included or excluded");
}
