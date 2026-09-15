import { describe, expect, it } from "vitest";
import {
  ALERT_QUALITY_MAX_REVISION, alertQualitySettingsOwner, buildAlertQualitySettingsUpdate, decodeAlertQualitySettings,
} from "./alert-quality.settings.model";
import fixture from "./alert-quality.settings.fixture.json";
import type { IamOverview } from "./settings-iam.model";

// Exact synthetic AlertQualitySettingsResponse shape, including the default/null fields
// asserted by the real Operator HTTP tests. No runtime store or identity provider is contacted.
const scope = fixture.scope_ref;
const recorded = { ...fixture, enabled: false, preference_state: "recorded", revision: 1, recorded_at: "2026-09-14T10:30:00Z" };
const unavailable = { ...fixture, available: false, enabled: null, revision: null, recorded_at: null,
  preference_state: "unavailable", unavailable_reason: "preference_store_unavailable",
  prerequisites: { ...fixture.prerequisites, preference_store_available: false } };

describe("actual serialized Settings response", () => {
  it("keeps unsaved defaults, recorded state and unavailable state distinct", () => {
    expect(decodeAlertQualitySettings(JSON.parse(JSON.stringify(fixture)), scope)).toEqual(fixture);
    expect(decodeAlertQualitySettings(recorded, scope)).toEqual(recorded);
    expect(decodeAlertQualitySettings(unavailable, scope)).toEqual(unavailable);
    expect(decodeAlertQualitySettings({ ...recorded, revision: ALERT_QUALITY_MAX_REVISION }, scope).revision)
      .toBe(ALERT_QUALITY_MAX_REVISION);
  });

  it("preserves the enabled preference when another prerequisite is unavailable", () => {
    for (const [key, reason] of [["source_bound", "source_unavailable"], ["writer_bound", "writer_unavailable"],
      ["producer_ready", "producer_not_ready"]] as const) {
      const data = decodeAlertQualitySettings({ ...fixture, available: false, unavailable_reason: reason,
        prerequisites: { ...fixture.prerequisites, [key]: false } }, scope);
      expect(data.enabled).toBe(true);
      expect(data.available).toBe(false);
      expect(data.mode).toBe("shadow");
      expect(buildAlertQualitySettingsUpdate(data, scope, false, 0)).toEqual({ scope_ref: scope, enabled: false, expected_revision: 0 });
    }
  });

  it.each([
    null, [], {}, { ...fixture, enabled: 1 }, { ...fixture, available: "true" },
    { ...fixture, mode: "enforce" }, { ...fixture, execution_authority: true },
    { ...fixture, requestable: true }, { ...fixture, principal: { roles: ["Owner"] } },
    { ...fixture, revision: "0" }, { ...fixture, revision: -1 }, { ...fixture, revision: 0.5 },
    { ...fixture, revision: Number.MAX_SAFE_INTEGER + 1 }, { ...fixture, revision: null },
    { ...fixture, recorded_at: "2026-09-14T10:00:00Z" }, { ...fixture, preference_state: "recorded" },
    { ...recorded, recorded_at: null }, { ...recorded, recorded_at: "2026-02-30T10:00:00Z" },
    { ...recorded, recorded_at: "2026-09-14T10:00:00-00:00" },
    { ...fixture, unavailable_reason: "producer_not_ready" }, { ...fixture, available: false },
    { ...fixture, prerequisites: { ...fixture.prerequisites, producer_ready: "true" } },
    { ...fixture, prerequisites: { ...fixture.prerequisites, owner: true } },
    { ...unavailable, enabled: false }, { ...unavailable, revision: 0 },
    { ...unavailable, unavailable_reason: "source_unavailable" },
  ])("rejects malformed, coerced, contradictory or authority-bearing state", (value) => {
    expect(() => decodeAlertQualitySettings(value, scope)).toThrow();
  });

  it("requires every nullable key and an exact scope, without repairing the projection", () => {
    for (const key of Object.keys(fixture)) {
      const value: Record<string, unknown> = { ...fixture };
      delete value[key];
      expect(() => decodeAlertQualitySettings(value, scope)).toThrow();
    }
    for (const selected of ["scope:other", `${scope}\n`, "", "/subscriptions/example"]) {
      expect(() => decodeAlertQualitySettings(fixture, selected)).toThrow();
    }
    expect(() => decodeAlertQualitySettings({ ...fixture, scope_ref: `${scope} ` }, scope)).toThrow();
  });
});

describe("exact revision input and server-reported Owner veto", () => {
  it("builds only scope, strict enabled and body revision, without authority or If-Match fields", () => {
    const settings = decodeAlertQualitySettings(fixture, scope);
    expect(buildAlertQualitySettingsUpdate(settings, scope, false, 0))
      .toEqual({ scope_ref: scope, enabled: false, expected_revision: 0 });
    for (const enabled of [null, undefined, 0, 1, "false", "true", true]) {
      expect(buildAlertQualitySettingsUpdate(settings, scope, enabled, 0)).toBeNull();
    }
    for (const revision of [null, undefined, "0", true, -1, 0.5, 1, NaN, Infinity, ALERT_QUALITY_MAX_REVISION]) {
      expect(buildAlertQualitySettingsUpdate(settings, scope, false, revision)).toBeNull();
    }
    expect(buildAlertQualitySettingsUpdate(settings, "scope:other", false, 0)).toBeNull();
    expect(buildAlertQualitySettingsUpdate(decodeAlertQualitySettings(unavailable, scope), scope, false, 0)).toBeNull();
  });

  it("accepts the final writable revision but never sends a revision beyond the exact integer range", () => {
    const last = decodeAlertQualitySettings({ ...recorded, revision: ALERT_QUALITY_MAX_REVISION - 1 }, scope);
    expect(buildAlertQualitySettingsUpdate(last, scope, true, last.revision)?.expected_revision).toBe(ALERT_QUALITY_MAX_REVISION - 1);
    const exhausted = decodeAlertQualitySettings({ ...recorded, revision: ALERT_QUALITY_MAX_REVISION }, scope);
    expect(buildAlertQualitySettingsUpdate(exhausted, scope, true, exhausted.revision)).toBeNull();
  });

  it("uses the matching /iam principal's exact Owner role, never a capability or authority boolean alone", () => {
    const overview: IamOverview = {
      principal: { oid: "example-account", roles: ["Owner"], capabilities: [] }, roles: [],
      assignmentBoundary: "identity-provider-group",
      authority: { source: "server-verified", isOwner: true, canManageGroupMembership: false },
      directory: { source: "not-configured", availability: "unavailable", observedAt: null, detail: null },
      workflow: { accessRequestAuthority: "proposal_only", assignmentAuthority: "observation_only", providerMutation: "promotion_required" },
    };
    expect(alertQualitySettingsOwner(overview, "example-account")).toBe(true);
    expect(alertQualitySettingsOwner(overview, "other-account")).toBe(false);
    expect(alertQualitySettingsOwner(overview, null)).toBe(false);
    expect(alertQualitySettingsOwner(null, "example-account")).toBe(false);
    for (const roles of [[], ["Reader"], ["Contributor"], ["Approver"], ["BreakGlass"]] as const) {
      expect(alertQualitySettingsOwner({ ...overview,
        principal: { ...overview.principal, roles, capabilities: ["manage-runtime-settings"] } }, "example-account")).toBe(false);
    }
  });
});
