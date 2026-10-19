import { afterEach, describe, expect, test } from "vitest";
import { setLocale, t } from "../i18n";
import { ForecastHistorySourceDetails } from "./settings-forecast-history";
import { decodeRuntimeSettings } from "./settings-runtime.model";

const sources = ["actions", "changes", "excluded_windows", "resource_lifecycle"].map((kind) => ({
  kind,
  reader: `reader:${kind}`,
  bound: true,
  positive_checkpoint: false,
  limitation: `${kind} proof unavailable`,
}));
const integration = {
  key: "forecast-history",
  source: "core-control-plane",
  observed: true,
  configured: true,
  ready: false,
  mode: "disabled",
  reason: "independent history proofs unavailable",
  sources,
  prerequisites: [
    { name: "reviewed_sources", satisfied: true },
    { name: "independent_proofs", satisfied: false },
  ],
};

function decode(value: unknown = integration) {
  return decodeRuntimeSettings({
    revision: 0,
    can_manage: false,
    updated_at: null,
    updated_by: null,
    settings: [],
    integrations: [value],
    runtime: {
      environment: "dev",
      state_store_durable: true,
      autonomy_default: "shadow",
      pantheon_enabled: true,
      workflow_observation_enabled: true,
      primary_transport_configured: true,
      auxiliary_transport_configured: false,
      case_history_configured: false,
    },
  }).integrations[0]!;
}

afterEach(() => setLocale("en"));

describe("forecast history Settings details", () => {
  test("keeps all four source bindings distinct from unavailable completeness", () => {
    const result = decode();
    expect(result.ready).toBe(false);
    expect(result.mode).toBe("disabled");
    expect(result.forecastHistory?.sources).toHaveLength(4);
    expect(result.forecastHistory?.sources.every((source) => source.bound)).toBe(true);
    expect(result.forecastHistory?.sources.some((source) => source.positiveCheckpoint)).toBe(false);
    expect(result.forecastHistory?.prerequisites[1]?.satisfied).toBe(false);
  });

  test.each([
    sources.slice(0, 3),
    [...sources.slice(0, 3), sources[0]],
    [{ ...sources[0], kind: "unknown" }, ...sources.slice(1)],
    [{ ...sources[0], bound: "true" }, ...sources.slice(1)],
    [{ ...sources[0], positive_checkpoint: 1 }, ...sources.slice(1)],
  ].map((value) => ({ sources: value })))("refuses malformed or incomplete source detail", (invalid) => {
    expect(() => decode({ ...integration, sources: invalid.sources })).toThrow();
  });

  test("refuses duplicate or unbounded prerequisites", () => {
    expect(() => decode({
      ...integration,
      prerequisites: [integration.prerequisites[0], integration.prerequisites[0]],
    })).toThrow("unique");
    expect(() => decode({
      ...integration,
      prerequisites: Array.from({ length: 17 }, (_, index) => ({
        name: `prerequisite-${index}`, satisfied: false,
      })),
    })).toThrow("bounded");
  });

  test("keeps legacy rows without source details readable", () => {
    expect(decode({ ...integration, sources: undefined }).forecastHistory).toBeUndefined();
    expect(ForecastHistorySourceDetails({ details: undefined })).toBeNull();
  });

  test.each(["en", "ko"] as const)("renders native source disclosure with %s labels", (locale) => {
    setLocale(locale);
    const view = ForecastHistorySourceDetails({ details: decode().forecastHistory });
    expect(view?.type).toBe("details");
    const content = JSON.stringify(view);
    expect(content).toContain(t("settings.forecastHistory.details"));
    expect(content).toContain(t("settings.forecastHistory.checkpointMissing"));
    expect(content).toContain(t("settings.forecastHistory.boundary"));
    expect(content).toContain("actions proof unavailable");
    expect(t("settings.runtimePolicies.fields.forecast.history_collection.enabled.label"))
      .not.toBe("settings.runtimePolicies.fields.forecast.history_collection.enabled.label");
  });
});
