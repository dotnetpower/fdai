import { describe, expect, test } from "vitest";
import { decodeRuntimeSettings, initialRuntimeDraft } from "./settings-runtime.model";

const payload = {
  revision: 2,
  can_manage: true,
  updated_at: "2026-07-24T00:00:00Z",
  updated_by: "owner-1",
  integrations: [
    { key: "chatops", configured: true, ready: true, mode: "enabled", reason: null },
  ],
  runtime: {
    environment: "prod",
    state_store_durable: true,
    autonomy_default: "shadow",
    pantheon_enabled: true,
    workflow_observation_enabled: true,
    primary_transport_configured: true,
    auxiliary_transport_configured: true,
    case_history_configured: false,
  },
  settings: [
    {
      key: "irp.enabled",
      group: "investigation",
      value_type: "boolean",
      environment_value: false,
      override_value: true,
      effective_value: true,
      minimum: null,
      maximum: null,
      options: [],
      restart_required: false,
      available: true,
      unavailable_reason: null,
    },
    {
      key: "analyzer.budget_seconds",
      group: "analysis",
      value_type: "number",
      environment_value: 60,
      override_value: null,
      effective_value: 60,
      minimum: 1,
      maximum: 3600,
      options: [],
      restart_required: false,
      available: true,
      unavailable_reason: null,
    },
  ],
};

describe("runtime settings model", () => {
  test("decodes source, effective values, and initial draft", () => {
    const view = decodeRuntimeSettings(payload);

    expect(view.revision).toBe(2);
    expect(view.settings[0]?.overrideValue).toBe(true);
    expect(view.integrations[0]?.ready).toBe(true);
    expect(view.runtime.autonomyDefault).toBe("shadow");
    expect(initialRuntimeDraft(view)).toEqual({
      "irp.enabled": true,
      "analyzer.budget_seconds": 60,
    });
  });

  test("rejects duplicate keys", () => {
    expect(() => decodeRuntimeSettings({
      ...payload,
      settings: [payload.settings[0], payload.settings[0]],
    })).toThrow(/unique/);
  });

  test("rejects out-of-range and non-integer values", () => {
    expect(() => decodeRuntimeSettings({
      ...payload,
      settings: [{
        ...payload.settings[1],
        effective_value: 5000,
      }],
    })).toThrow(/above maximum/);
    expect(() => decodeRuntimeSettings({
      ...payload,
      settings: [{
        ...payload.settings[1],
        value_type: "integer",
        effective_value: 1.5,
      }],
    })).toThrow(/integer/);
  });

  test("rejects unsafe runtime and integration status values", () => {
    expect(() => decodeRuntimeSettings({
      ...payload,
      integrations: [{ ...payload.integrations[0], mode: "execute" }],
    })).toThrow(/mode is invalid/);
    expect(() => decodeRuntimeSettings({
      ...payload,
      runtime: { ...payload.runtime, environment: "customer-a" },
    })).toThrow(/environment is invalid/);
  });
});
