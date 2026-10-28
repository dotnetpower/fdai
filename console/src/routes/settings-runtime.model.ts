export type RuntimeSettingValue = boolean | number | string | Readonly<Record<string, unknown>>;
export type RuntimeSettingValueType = "boolean" | "integer" | "number" | "enum" | "object";

export interface RuntimeSettingView {
  readonly key: string;
  readonly group: string;
  readonly valueType: RuntimeSettingValueType;
  readonly environmentValue: RuntimeSettingValue;
  readonly overrideValue: RuntimeSettingValue | null;
  readonly effectiveValue: RuntimeSettingValue;
  readonly minimum: number | null;
  readonly maximum: number | null;
  readonly options: readonly string[];
  readonly restartRequired: boolean;
  readonly available: boolean;
  readonly unavailableReason: string | null;
}

export interface RuntimeSettingsView {
  readonly revision: number;
  readonly canManage: boolean;
  readonly updatedAt: string | null;
  readonly updatedBy: string | null;
  readonly integrations: readonly RuntimeIntegrationView[];
  readonly runtime: RuntimeDiagnosticsView;
  readonly settings: readonly RuntimeSettingView[];
  readonly teamsA1Onboarding: TeamsA1OnboardingView;
}

export interface TeamsA1OnboardingView {
  readonly revision: number;
  readonly state: "not-configured" | "plan-requested";
  readonly environment: "dev" | "staging" | "prod" | "unspecified";
  readonly canManage: boolean;
  readonly executionAuthority: false;
}

export interface RuntimeIntegrationView {
  readonly key: string;
  /** Runtime that owns this integration's prerequisites. */
  readonly source: "core-control-plane" | "operator-service" | "unspecified";
  /** False when the projecting runtime could not observe the prerequisites at all. */
  readonly observed: boolean;
  readonly configured: boolean;
  readonly ready: boolean;
  readonly mode: "disabled" | "enabled" | "shadow" | "enforce";
  readonly reason: string | null;
  readonly forecastHistory?: ForecastHistoryDetails;
}

export interface ForecastHistoryDetails {
  readonly sources: readonly {
    readonly kind: "actions" | "changes" | "excluded_windows" | "resource_lifecycle";
    readonly reader: string;
    readonly bound: boolean;
    readonly positiveCheckpoint: boolean;
    readonly limitation: string;
  }[];
  readonly prerequisites: readonly { readonly name: string; readonly satisfied: boolean }[];
}

export interface RuntimeDiagnosticsView {
  readonly environment: "dev" | "staging" | "prod" | "unspecified";
  readonly stateStoreDurable: boolean;
  readonly autonomyDefault: string;
  readonly pantheonEnabled: boolean;
  readonly workflowObservationEnabled: boolean;
  readonly primaryTransportConfigured: boolean;
  readonly auxiliaryTransportConfigured: boolean;
  readonly caseHistoryConfigured: boolean;
}

export function decodeRuntimeSettings(value: unknown): RuntimeSettingsView {
  const root = record(value, "runtime settings");
  const revision = integer(root["revision"], "runtime settings.revision", 0);
  const settingsRaw = root["settings"];
  if (!Array.isArray(settingsRaw)) throw new Error("runtime settings.settings MUST be an array");
  const settings = settingsRaw.map((item, index) => decodeSetting(item, index));
  if (new Set(settings.map((setting) => setting.key)).size !== settings.length) {
    throw new Error("runtime settings keys MUST be unique");
  }
  const integrationsRaw = root["integrations"];
  if (!Array.isArray(integrationsRaw)) {
    throw new Error("runtime settings.integrations MUST be an array");
  }
  const integrations = integrationsRaw.map((item, index) => decodeIntegration(item, index));
  if (new Set(integrations.map((integration) => integration.key)).size !== integrations.length) {
    throw new Error("runtime integration keys MUST be unique");
  }
  const runtime = decodeRuntimeDiagnostics(root["runtime"]);
  return {
    revision,
    canManage: boolean(root["can_manage"], "runtime settings.can_manage"),
    updatedAt: nullableString(root["updated_at"], "runtime settings.updated_at"),
    updatedBy: nullableString(root["updated_by"], "runtime settings.updated_by"),
    integrations,
    runtime,
    settings,
    teamsA1Onboarding: decodeTeamsA1Onboarding(root["teams_a1_onboarding"], runtime.environment),
  };
}

function decodeTeamsA1Onboarding(
  value: unknown,
  fallbackEnvironment: RuntimeDiagnosticsView["environment"],
): TeamsA1OnboardingView {
  if (value === undefined) {
    return {
      revision: 0,
      state: "not-configured",
      environment: fallbackEnvironment,
      canManage: false,
      executionAuthority: false,
    };
  }
  const item = record(value, "runtime settings.teams_a1_onboarding");
  const state = item["state"];
  if (state !== "not-configured" && state !== "plan-requested") {
    throw new Error("runtime settings.teams_a1_onboarding.state is invalid");
  }
  const environment = item["environment"];
  if (
    environment !== "dev"
    && environment !== "staging"
    && environment !== "prod"
    && environment !== "unspecified"
  ) {
    throw new Error("runtime settings.teams_a1_onboarding.environment is invalid");
  }
  if (item["execution_authority"] !== false) {
    throw new Error("runtime settings.teams_a1_onboarding MUST NOT grant execution authority");
  }
  return {
    revision: integer(item["revision"], "runtime settings.teams_a1_onboarding.revision", 0),
    state,
    environment,
    canManage: boolean(item["can_manage"], "runtime settings.teams_a1_onboarding.can_manage"),
    executionAuthority: false,
  };
}

export function initialRuntimeDraft(
  view: RuntimeSettingsView,
): Readonly<Record<string, RuntimeSettingValue>> {
  return Object.fromEntries(
    view.settings.map((setting) => [
      setting.key,
      setting.overrideValue ?? setting.effectiveValue,
    ]),
  );
}

function decodeSetting(value: unknown, index: number): RuntimeSettingView {
  const path = `runtime settings.settings[${index}]`;
  const item = record(value, path);
  const valueType = settingType(item["value_type"], `${path}.value_type`);
  const minimum = nullableNumber(item["minimum"], `${path}.minimum`);
  const maximum = nullableNumber(item["maximum"], `${path}.maximum`);
  if (minimum !== null && maximum !== null && maximum < minimum) {
    throw new Error(`${path}.maximum MUST be >= minimum`);
  }
  const options = stringArray(item["options"], `${path}.options`);
  if (valueType === "enum" && options.length === 0) {
    throw new Error(`${path}.options MUST be non-empty for enum settings`);
  }
  const environmentValue = settingValue(
    item["environment_value"],
    valueType,
    `${path}.environment_value`,
  );
  const effectiveValue = settingValue(
    item["effective_value"],
    valueType,
    `${path}.effective_value`,
  );
  const overrideValue = item["override_value"] === null
    ? null
    : settingValue(item["override_value"], valueType, `${path}.override_value`);
  for (const candidate of [environmentValue, effectiveValue, overrideValue]) {
    if (candidate === null || typeof candidate !== "number") continue;
    if (minimum !== null && candidate < minimum) throw new Error(`${path} value is below minimum`);
    if (maximum !== null && candidate > maximum) throw new Error(`${path} value is above maximum`);
  }
  return {
    key: nonEmptyString(item["key"], `${path}.key`),
    group: nonEmptyString(item["group"], `${path}.group`),
    valueType,
    environmentValue,
    overrideValue,
    effectiveValue,
    minimum,
    maximum,
    options,
    restartRequired: boolean(item["restart_required"], `${path}.restart_required`),
    available: boolean(item["available"], `${path}.available`),
    unavailableReason: nullableString(item["unavailable_reason"], `${path}.unavailable_reason`),
  };
}

function decodeIntegration(value: unknown, index: number): RuntimeIntegrationView {
  const path = `runtime settings.integrations[${index}]`;
  const item = record(value, path);
  const mode = item["mode"];
  if (mode !== "disabled" && mode !== "enabled" && mode !== "shadow" && mode !== "enforce") {
    throw new Error(`${path}.mode is invalid`);
  }
  const source = item["source"];
  if (
    source !== undefined
    && source !== "core-control-plane"
    && source !== "operator-service"
    && source !== "unspecified"
  ) {
    throw new Error(`${path}.source is invalid`);
  }
  const observed = item["observed"];
  if (observed !== undefined && typeof observed !== "boolean") {
    throw new Error(`${path}.observed MUST be a boolean`);
  }
  return {
    key: nonEmptyString(item["key"], `${path}.key`),
    source: source ?? "unspecified",
    observed: observed ?? true,
    configured: boolean(item["configured"], `${path}.configured`),
    ready: boolean(item["ready"], `${path}.ready`),
    mode,
    reason: nullableString(item["reason"], `${path}.reason`),
    ...(item["key"] === "forecast-history" && item["sources"] !== undefined
      ? { forecastHistory: decodeForecastHistoryDetails(item, path) }
      : {}),
  };
}

function decodeForecastHistoryDetails(
  item: Record<string, unknown>,
  path: string,
): ForecastHistoryDetails {
  const sourceRows = item["sources"];
  const prerequisiteRows = item["prerequisites"];
  if (!Array.isArray(sourceRows) || sourceRows.length !== 4) {
    throw new Error(`${path}.sources MUST contain exactly four history kinds`);
  }
  if (!Array.isArray(prerequisiteRows) || prerequisiteRows.length > 16) {
    throw new Error(`${path}.prerequisites MUST be a bounded array`);
  }
  const sources = sourceRows.map((raw, index): ForecastHistoryDetails["sources"][number] => {
    const source = record(raw, `${path}.sources[${index}]`);
    const kind = source["kind"];
    if (kind !== "actions" && kind !== "changes"
      && kind !== "excluded_windows" && kind !== "resource_lifecycle") {
      throw new Error(`${path}.sources[${index}].kind is invalid`);
    }
    return {
      kind,
      reader: nonEmptyString(source["reader"], `${path}.sources[${index}].reader`),
      bound: boolean(source["bound"], `${path}.sources[${index}].bound`),
      positiveCheckpoint: boolean(
        source["positive_checkpoint"], `${path}.sources[${index}].positive_checkpoint`,
      ),
      limitation: nonEmptyString(source["limitation"], `${path}.sources[${index}].limitation`),
    };
  });
  if (new Set(sources.map((source) => source.kind)).size !== 4) {
    throw new Error(`${path}.sources MUST contain unique history kinds`);
  }
  const prerequisites = prerequisiteRows.map((raw, index) => {
    const prerequisite = record(raw, `${path}.prerequisites[${index}]`);
    return {
      name: nonEmptyString(prerequisite["name"], `${path}.prerequisites[${index}].name`),
      satisfied: boolean(prerequisite["satisfied"], `${path}.prerequisites[${index}].satisfied`),
    };
  });
  if (new Set(prerequisites.map((value) => value.name)).size !== prerequisites.length) {
    throw new Error(`${path}.prerequisites MUST contain unique names`);
  }
  return { sources, prerequisites };
}

function decodeRuntimeDiagnostics(value: unknown): RuntimeDiagnosticsView {
  const path = "runtime settings.runtime";
  const item = record(value, path);
  const environment = item["environment"];
  if (
    environment !== "dev"
    && environment !== "staging"
    && environment !== "prod"
    && environment !== "unspecified"
  ) {
    throw new Error(`${path}.environment is invalid`);
  }
  return {
    environment,
    stateStoreDurable: boolean(item["state_store_durable"], `${path}.state_store_durable`),
    autonomyDefault: nonEmptyString(item["autonomy_default"], `${path}.autonomy_default`),
    pantheonEnabled: boolean(item["pantheon_enabled"], `${path}.pantheon_enabled`),
    workflowObservationEnabled: boolean(
      item["workflow_observation_enabled"],
      `${path}.workflow_observation_enabled`,
    ),
    primaryTransportConfigured: boolean(
      item["primary_transport_configured"],
      `${path}.primary_transport_configured`,
    ),
    auxiliaryTransportConfigured: boolean(
      item["auxiliary_transport_configured"],
      `${path}.auxiliary_transport_configured`,
    ),
    caseHistoryConfigured: boolean(
      item["case_history_configured"],
      `${path}.case_history_configured`,
    ),
  };
}

function settingType(value: unknown, path: string): RuntimeSettingValueType {
  if (value === "boolean" || value === "integer" || value === "number" || value === "enum" || value === "object") {
    return value;
  }
  throw new Error(`${path} is invalid`);
}

function settingValue(
  value: unknown,
  valueType: RuntimeSettingValueType,
  path: string,
): RuntimeSettingValue {
  if (valueType === "object") return record(value, path);
  if (valueType === "boolean") return boolean(value, path);
  if (valueType === "enum") return nonEmptyString(value, path);
  if (typeof value !== "number" || !Number.isFinite(value)) throw new Error(`${path} MUST be finite`);
  if (valueType === "integer" && !Number.isInteger(value)) throw new Error(`${path} MUST be an integer`);
  return value;
}

export function normalizeRuntimeSettingChanges(
  view: Pick<RuntimeSettingsView, "settings">,
  changes: Readonly<Record<string, RuntimeSettingValue | null>>,
): Readonly<Record<string, RuntimeSettingValue | null>> {
  return Object.fromEntries(Object.entries(changes).map(([key, value]) => {
    const setting = view.settings.find((entry) => entry.key === key);
    if (setting?.valueType !== "object" || value === null) return [key, value];
    const parsed: unknown = typeof value === "string" ? JSON.parse(value) : value;
    return [key, record(parsed, key)];
  }));
}

function record(value: unknown, path: string): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error(`${path} MUST be an object`);
  }
  return value as Record<string, unknown>;
}

function boolean(value: unknown, path: string): boolean {
  if (typeof value !== "boolean") throw new Error(`${path} MUST be a boolean`);
  return value;
}

function integer(value: unknown, path: string, minimum: number): number {
  if (!Number.isInteger(value) || (value as number) < minimum) {
    throw new Error(`${path} MUST be an integer >= ${minimum}`);
  }
  return value as number;
}

function nonEmptyString(value: unknown, path: string): string {
  if (typeof value !== "string" || value.length === 0) throw new Error(`${path} MUST be non-empty`);
  return value;
}

function nullableString(value: unknown, path: string): string | null {
  if (value === null) return null;
  return nonEmptyString(value, path);
}

function nullableNumber(value: unknown, path: string): number | null {
  if (value === null) return null;
  if (typeof value !== "number" || !Number.isFinite(value)) throw new Error(`${path} MUST be finite`);
  return value;
}

function stringArray(value: unknown, path: string): readonly string[] {
  if (!Array.isArray(value) || !value.every((item) => typeof item === "string" && item.length > 0)) {
    throw new Error(`${path} MUST be a string array`);
  }
  return value;
}
