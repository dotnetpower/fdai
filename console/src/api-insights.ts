import type { AutonomyPayload, DashboardKpi, EffectiveScope } from "./types";
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
  return {
    event_count: eventCount,
    shadow_share: apiRatio(root, "shadow_share", "dashboard KPI"),
    enforce_share: apiRatio(root, "enforce_share", "dashboard KPI"),
    hil_pending: apiNonNegativeInteger(root, "hil_pending", "dashboard KPI"),
    by_action_kind: apiNumberRecord(root["by_action_kind"], "dashboard KPI.by_action_kind"),
    by_outcome: apiNumberRecord(root["by_outcome"], "dashboard KPI.by_outcome"),
    by_tier: apiNumberRecord(root["by_tier"], "dashboard KPI.by_tier"),
    last_recorded_at: apiNullableString(root, "last_recorded_at", "dashboard KPI"),
    audit_sample: auditSample,
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
    (!empty && result.from_seq! > result.through_seq!)
  ) throw contractError("dashboard KPI.audit_sample is inconsistent");
  return result;
}

export function decodeAutonomyPayload(value: unknown): AutonomyPayload {
  const root = apiRecord(value, "autonomy measurement");
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
  if (!Array.isArray(root["guards"])) {
    throw contractError("autonomy measurement.guards MUST be an array");
  }
  if (!Array.isArray(root["verticals"])) {
    throw contractError("autonomy measurement.verticals MUST be an array");
  }
  return {
    synthetic: apiBoolean(root, "synthetic", "autonomy measurement"),
    window_days: apiPositiveInteger(root, "window_days", "autonomy measurement"),
    sample_size: apiNonNegativeInteger(root, "sample_size", "autonomy measurement"),
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
      auto_resolution_rate: decodeMetric(success["auto_resolution_rate"], "success.auto_resolution_rate"),
      human_touchpoints_per_100: decodeMetric(success["human_touchpoints_per_100"], "success.human_touchpoints_per_100"),
      mttr_seconds: decodeMetric(success["mttr_seconds"], "success.mttr_seconds"),
      change_lead_time_seconds: decodeMetric(success["change_lead_time_seconds"], "success.change_lead_time_seconds"),
      cost_per_resolved_event_usd: decodeMetric(success["cost_per_resolved_event_usd"], "success.cost_per_resolved_event_usd"),
    },
    leading: {
      mixed_model_disagreement_rate: decodeMetric(leading["mixed_model_disagreement_rate"], "leading.mixed_model_disagreement_rate"),
      verifier_failure_rate: decodeMetric(leading["verifier_failure_rate"], "leading.verifier_failure_rate"),
      shadow_divergence_rate: decodeMetric(leading["shadow_divergence_rate"], "leading.shadow_divergence_rate"),
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
    verticals: root["verticals"].map((raw, index) => {
      const item = apiRecord(raw, `autonomy measurement.verticals[${index}]`);
      return {
        key: apiString(item, "key", "autonomy vertical"),
        events: apiNonNegativeInteger(item, "events", "autonomy vertical"),
        auto_resolved: apiNonNegativeInteger(item, "auto_resolved", "autonomy vertical"),
        open_risks: apiNonNegativeInteger(item, "open_risks", "autonomy vertical"),
        monthly_savings: apiNumber(item, "monthly_savings", "autonomy vertical"),
      };
    }),
    tier: {
      mix: decodeFiniteNumberRecord(tier["mix"], "autonomy measurement.tier.mix"),
      bands: Object.fromEntries(
        Object.entries(bands).map(([key, raw]) => {
          if (!Array.isArray(raw) || raw.length !== 2 || raw.some((item) => typeof item !== "number" || !Number.isFinite(item))) {
            throw contractError(`autonomy measurement.tier.bands.${key} MUST be two finite numbers`);
          }
          return [key, [raw[0], raw[1]] as const];
        }),
      ),
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

function decodeMetric(value: unknown, label: string): AutonomyPayload["success"]["auto_resolution_rate"] {
  const item = apiRecord(value, `autonomy measurement.${label}`);
  const direction = apiString(item, "direction", `autonomy measurement.${label}`);
  if (direction !== "higher" && direction !== "lower") {
    throw contractError(`autonomy measurement.${label}.direction MUST be higher or lower`);
  }
  return {
    value: apiNumber(item, "value", `autonomy measurement.${label}`),
    baseline: apiNumber(item, "baseline", `autonomy measurement.${label}`),
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
