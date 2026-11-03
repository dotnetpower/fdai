import { describe, expect, test } from "vitest";
import {
  diagnosticBooleanKind, diagnosticSummary, diagnosticSupportSummary, observeDiagnostic,
} from "./settings-diagnostics.model";
import { filterIamRoster } from "./settings-iam-users";
import { filterIamRequests, isRoleAssigned } from "./settings-iam-requests";
import { referencedUsers } from "./settings-iam";
import { confirmsTeamsWorkflowPreferences } from "./settings-teams-workflow.model";
import type { IamAccessRequest, IamOverview, IdentityRosterItem } from "./settings-iam.model";
import iamEn from "./i18n/settings-iam.en.json";
import iamKo from "./i18n/settings-iam.ko.json";
import integrationsEn from "./i18n/settings-integrations.en.json";
import integrationsKo from "./i18n/settings-integrations.ko.json";
import diagnosticsEn from "./i18n/settings-diagnostics.en.json";
import diagnosticsKo from "./i18n/settings-diagnostics.ko.json";

const person: IdentityRosterItem = {
  provider: "entra", subjectId: "person-1", displayName: "Example Analyst",
  username: "analyst@example.com", principalType: "person", roles: ["Reader"], active: true,
};
const request: IamAccessRequest = {
  requestId: "request-1", idempotencyKey: "intent-1", requesterOid: "owner-1",
  identityProvider: "entra", targetSubjectId: person.subjectId, targetUsername: person.username!,
  operation: "grant", role: "Reader", justification: "A synthetic governed access request.",
  requestedAt: "2026-01-01T00:00:00Z", status: "pending", reviewedBy: null,
  reviewedAt: null, reviewJustification: null,
};

describe("IAM observed facts and local triage", () => {
  test("I03 never fabricates requested roles or activity for referenced identities", () => {
    const overview = {
      principal: { oid: "current-1", roles: ["Reader"], capabilities: ["view-console"] },
    } as unknown as IamOverview;
    const items = referencedUsers(overview, null, [
      { ...request, role: "Owner" }, { ...request, status: "rejected" },
    ]);
    expect(items).toHaveLength(1);
    expect(items[0]).toMatchObject({ subjectId: "current-1", roles: ["Reader"] });
    expect(items.some((item) => item.subjectId === person.subjectId)).toBe(false);
  });
  test("I04 membership snapshots never call a revoke assigned", () => {
    expect(isRoleAssigned({ ...request, status: "approved" }, [person])).toBe(true);
    expect(isRoleAssigned({ ...request, status: "approved", operation: "revoke" }, [person])).toBe(false);
    expect(isRoleAssigned({ ...request, status: "approved", role: "Owner" }, [person])).toBe(false);
  });
  test("I06 status and identity search cover only loaded requests", () => {
    const loaded = [request, { ...request, requestId: "request-2", status: "approved" as const }];
    expect(filterIamRequests(loaded, "pending", " ANALYST ", [person])).toEqual([request]);
    expect(filterIamRequests(loaded, "approved", "request-2", [person])).toHaveLength(1);
    expect(filterIamRequests(loaded, "all", "missing", [person])).toEqual([]);
    expect(filterIamRequests(loaded, "all", "", [person])).toEqual(loaded);
  });
  test("I07 local roster filters combine type, case-insensitive name, email and subject", () => {
    const group = { ...person, subjectId: "group-1", principalType: "group" as const, username: null };
    expect(filterIamRoster([person, group], "person", " EXAMPLE ")).toEqual([person]);
    expect(filterIamRoster([person, group], "all", "analyst@")).toEqual([person]);
    expect(filterIamRoster([person, group], "group", "GROUP-1")).toEqual([group]);
    expect(filterIamRoster([person, group], "all", "   ")).toHaveLength(2);
  });
});

describe("independent diagnostic observations", () => {
  test("D02 commits a fast probe without waiting for a slow read", async () => {
    let release!: (value: unknown) => void;
    const slow = observeDiagnostic(() => new Promise((resolve) => { release = resolve; }));
    let completed = false;
    void slow.then(() => { completed = true; });
    expect((await observeDiagnostic(async () => ({ status: "ok" }))).status).toBe("available");
    expect(completed).toBe(false);
    release({});
    expect((await slow).status).toBe("available");
  });
  test("D03 D05 D06 retain safe status, actual completion time and monotonic elapsed time", async () => {
    let tick = 30;
    const failed = await observeDiagnostic(
      async () => { tick = 81; throw new Error("private.example.com credential=do-not-export"); },
      undefined, () => tick, () => "2026-01-01T00:00:01Z",
    );
    expect(failed).toEqual({ status: "unavailable", checkedAt: "2026-01-01T00:00:01Z", durationMs: 51 });
    expect(JSON.stringify(failed)).not.toContain("private");
    expect((await observeDiagnostic(async () => ({ status: "degraded" }), () => false)).status).toBe("unavailable");
  });
  test("D07 uses prerequisite-specific semantics rather than enabling everything", () => {
    expect(diagnosticBooleanKind("stateStore")).toBe("durable");
    for (const key of ["primaryTransport", "auxiliaryTransport", "caseHistory"]) {
      expect(diagnosticBooleanKind(key)).toBe("configured");
    }
    expect(diagnosticBooleanKind("pantheon")).toBe("enabled");
  });
  test("D08 exports an allowlist, not the original runtime or identity object", () => {
    const runtime = {
      environment: "dev", stateStoreDurable: true, autonomyDefault: "private-value",
      pantheonEnabled: true, workflowObservationEnabled: false,
      primaryTransportConfigured: false, auxiliaryTransportConfigured: false, caseHistoryConfigured: true,
      username: "private@example.com", token: "secret", webhookUrl: "private.example.com",
    } as const;
    const output = diagnosticSupportSummary(null, null, runtime, "2026-01-01T00:00:00Z", true);
    expect(JSON.parse(output)).toMatchObject({ runtime_stale: true, runtime: { state_store_durable: true } });
    expect(output).not.toMatch(/private|secret|username|token|webhook/);
  });
  test("D11 pending observations do not inflate available or failed counts", () => {
    const result = { status: "available", checkedAt: "2026-01-01T00:00:00Z", durationMs: 1 } as const;
    expect(diagnosticSummary([result, null], [false, true])).toEqual({ available: 1, unavailable: 0, checking: 1 });
    expect(diagnosticSummary([result, { ...result, status: "unavailable" }], [true, false]))
      .toEqual({ available: 0, unavailable: 1, checking: 1 });
  });
});

test("N05 never labels omitted or mismatched preference readback confirmed", () => {
  const binding = {
    visible: true as const, configured: true as const, bindingVersion: "version-1",
    endpointIdentifier: "synthetic-binding", observedAt: "2026-01-01T00:00:00Z", savedAt: null,
  };
  expect(confirmsTeamsWorkflowPreferences(binding, { deliveryTargets: ["email"] })).toBe(false);
  expect(confirmsTeamsWorkflowPreferences({ ...binding, deliveryTargets: ["email"] }, { deliveryTargets: ["console-inbox"] })).toBe(false);
  expect(confirmsTeamsWorkflowPreferences({ ...binding, deliveryTargets: ["email", "console-inbox"] }, { deliveryTargets: ["console-inbox", "email"] })).toBe(true);
  expect(confirmsTeamsWorkflowPreferences(binding, { selectedChannelIds: ["channel-1"] })).toBe(false);
  expect(confirmsTeamsWorkflowPreferences(binding, { emailRecipientMode: "custom", customEmail: "recipient@example.com" })).toBe(false);
});

test.each([
  ["IAM", iamEn, iamKo], ["Integrations", integrationsEn, integrationsKo],
  ["Diagnostics", diagnosticsEn, diagnosticsKo],
])("%s local catalogs have matching keys and interpolation", (_name, en, ko) => {
  expect(Object.keys(en).sort()).toEqual(Object.keys(ko).sort());
  for (const key of Object.keys(en)) {
    const english = en[key as keyof typeof en] as string;
    const korean = ko[key as keyof typeof ko] as string;
    expect(korean.trim()).not.toBe("");
    expect((korean.match(/\{\w+\}/g) ?? []).sort()).toEqual((english.match(/\{\w+\}/g) ?? []).sort());
  }
});
