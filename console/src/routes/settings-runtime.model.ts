export type RuntimeSettingValue = boolean | number | string;
export type RuntimeSettingValueType = "boolean" | "integer" | "number" | "enum";

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
}

export interface RuntimeIntegrationView {
  readonly key: string;
  readonly configured: boolean;
  readonly ready: boolean;
  readonly mode: "disabled" | "enabled" | "shadow" | "enforce";
  readonly reason: string | null;
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
  return {
    revision,
    canManage: boolean(root["can_manage"], "runtime settings.can_manage"),
    updatedAt: nullableString(root["updated_at"], "runtime settings.updated_at"),
    updatedBy: nullableString(root["updated_by"], "runtime settings.updated_by"),
    integrations,
    runtime: decodeRuntimeDiagnostics(root["runtime"]),
    settings,
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
  return {
    key: nonEmptyString(item["key"], `${path}.key`),
    configured: boolean(item["configured"], `${path}.configured`),
    ready: boolean(item["ready"], `${path}.ready`),
    mode,
    reason: nullableString(item["reason"], `${path}.reason`),
  };
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
  if (value === "boolean" || value === "integer" || value === "number" || value === "enum") {
    return value;
  }
  throw new Error(`${path} is invalid`);
}

function settingValue(
  value: unknown,
  valueType: RuntimeSettingValueType,
  path: string,
): RuntimeSettingValue {
  if (valueType === "boolean") return boolean(value, path);
  if (valueType === "enum") return nonEmptyString(value, path);
  if (typeof value !== "number" || !Number.isFinite(value)) throw new Error(`${path} MUST be finite`);
  if (valueType === "integer" && !Number.isInteger(value)) throw new Error(`${path} MUST be an integer`);
  return value;
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
