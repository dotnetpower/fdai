import { describe, expect, it } from "vitest";
import {
  appendBrowserEvidencePage,
  browserEvidenceRequest,
  decodeBrowserEvidenceWorkspace,
} from "./browser-evidence.model";

const observedAt = "2026-09-15T12:00:00Z";

describe("Browser evidence workspace model", () => {
  it("decodes a reconciled payload-free workspace page", () => {
    const page = decodeBrowserEvidenceWorkspace(response());

    expect(page.loaded_count).toBe(1);
    expect(page.snapshot_withheld_count).toBe(1);
    expect(page.items[0]).toMatchObject({
      source_host: "dashboard.example",
      final_host: "status.example",
      redirected: true,
      retention_state: "held",
      digest_presence: {
        screenshot: true,
        text: true,
        accessibility_snapshot: false,
      },
      audit: {
        state: "exact",
        sequence: "42",
        correlation_id: "correlation-1",
      },
      can_authorize_action: false,
    });
  });

  it("rejects hidden payloads, mismatched counts, and invalid retention", () => {
    expect(() => decodeBrowserEvidenceWorkspace({
      ...response(),
      visible_text: "private",
    })).toThrow(/fields are invalid/);
    expect(() => decodeBrowserEvidenceWorkspace({
      ...response(),
      loaded_count: 0,
    })).toThrow(/counts do not reconcile/);
    expect(() => decodeBrowserEvidenceWorkspace(response({
      retention_state: "retained",
    }))).toThrow(/retention state/);
  });

  it("accepts server-canonical machine hosts and rejects invalid label bounds", () => {
    expect(decodeBrowserEvidenceWorkspace(response({
      source_host: "my_host.example",
      final_host: "2001:db8::192.168.0.1",
    })).items[0]).toMatchObject({
      source_host: "my_host.example",
      final_host: "2001:db8::192.168.0.1",
    });

    expect(() => decodeBrowserEvidenceWorkspace(response({
      source_host: `${"a".repeat(64)}.example`,
    }))).toThrow(/source_host is not canonical/);
    expect(() => decodeBrowserEvidenceWorkspace(response({
      source_host: "source..example",
    }))).toThrow(/source_host is not canonical/);
  });

  it("rejects non-exact audit identity and unordered attention rows", () => {
    expect(() => decodeBrowserEvidenceWorkspace(response({
      audit: {
        state: "ambiguous",
        sequence: "42",
        correlation_id: "correlation-1",
      },
    }))).toThrow(/non-exact audit/);

    const first = item({
      artifact_id: `sha256:${"a".repeat(64)}`,
      prompt_injection_finding_count: 0,
      legal_hold: false,
      legal_hold_ref: null,
      legal_hold_at: null,
      retention_state: "retained",
    });
    const second = item({
      artifact_id: `sha256:${"b".repeat(64)}`,
      prompt_injection_finding_count: 1,
    });
    expect(() => decodeBrowserEvidenceWorkspace({
      ...response(),
      loaded_count: 2,
      matching_admitted_count: 2,
      snapshot_total_count: 3,
      snapshot_admitted_count: 2,
      summary: {
        security_finding_count: 1,
        legal_hold_count: 1,
        expiring_count: 0,
        expired_pending_purge_count: 0,
        retained_count: 1,
      },
      items: [first, second],
    })).toThrow(/not ordered by attention/);
  });

  it("builds bounded server parameters and identifies invalid route filters", () => {
    const valid = browserEvidenceRequest(new URLSearchParams(
      `host=dashboard.example&host_scope=requested&policy=dashboard&policy_version=4`
      + `&from=2026-09-01T00%3A00%3A00Z&before=2026-09-15T00%3A00%3A00Z`
      + `&retention=expiring&finding=present&sort=newest`,
    ));
    expect(valid.invalid).toEqual([]);
    expect(valid.sort).toBe("newest");
    expect(valid.params).toMatchObject({
      limit: "25",
      host: "dashboard.example",
      policy_version: "4",
    });

    const invalid = browserEvidenceRequest(new URLSearchParams(
      "host=Dashboard.Example&policy_version=0&retention=expired&sort=oldest&unknown=1",
    ));
    expect(invalid.invalid).toEqual([
      "unknown",
      "sort",
      "host",
      "policy_version",
      "retention",
    ]);
  });

  it("appends drift-aware pages without duplicating changed records", () => {
    const first = decodeBrowserEvidenceWorkspace({
      ...response(),
      matching_admitted_count: 2,
      snapshot_total_count: 3,
      snapshot_admitted_count: 2,
      summary: {
        security_finding_count: 2,
        legal_hold_count: 2,
        expiring_count: 0,
        expired_pending_purge_count: 0,
        retained_count: 0,
      },
      has_more: true,
      next_cursor: "cursor-one",
      page_complete: false,
    });
    const second = decodeBrowserEvidenceWorkspace({
      ...response({
        artifact_id: `sha256:${"b".repeat(64)}`,
        captured_at: "2026-09-14T10:00:00Z",
      }),
      matching_admitted_count: 2,
      snapshot_total_count: 3,
      snapshot_admitted_count: 2,
      summary: {
        security_finding_count: 2,
        legal_hold_count: 2,
        expiring_count: 0,
        expired_pending_purge_count: 0,
        retained_count: 0,
      },
    });
    const current = { page: first, items: first.items };

    expect(appendBrowserEvidencePage(current, "cursor-one", second).items).toHaveLength(2);
    expect(() => appendBrowserEvidencePage(current, "other", second)).toThrow(
      /cursor changed/,
    );
    expect(() => appendBrowserEvidencePage(
      current,
      "cursor-one",
      decodeBrowserEvidenceWorkspace({
        ...response({ browser_version: "changed" }),
        matching_admitted_count: 2,
        snapshot_total_count: 3,
        snapshot_admitted_count: 2,
        summary: {
          security_finding_count: 2,
          legal_hold_count: 2,
          expiring_count: 0,
          expired_pending_purge_count: 0,
          retained_count: 0,
        },
      }),
    )).toThrow(/changed while loading/);
    expect(() => appendBrowserEvidencePage(
      current,
      "cursor-one",
      decodeBrowserEvidenceWorkspace({
        ...response({
          artifact_id: `sha256:${"b".repeat(64)}`,
          captured_at: "2026-09-14T10:00:00Z",
        }),
        matching_admitted_count: 1,
      }),
    )).toThrow(/changed while loading/);
  });

  it("accepts 500 unique rows and rejects 501 rows", () => {
    const items = Array.from({ length: 501 }, (_, index) => retainedItem(index));
    const envelope = {
      ...response(),
      loaded_count: 500,
      matching_admitted_count: 500,
      snapshot_total_count: 501,
      snapshot_admitted_count: 500,
      summary: {
        security_finding_count: 0,
        legal_hold_count: 0,
        expiring_count: 0,
        expired_pending_purge_count: 0,
        retained_count: 500,
      },
      items: items.slice(0, 500),
    };

    expect(decodeBrowserEvidenceWorkspace(envelope).items).toHaveLength(500);
    expect(() => decodeBrowserEvidenceWorkspace({
      ...envelope,
      loaded_count: 501,
      matching_admitted_count: 501,
      snapshot_total_count: 502,
      snapshot_admitted_count: 501,
      summary: {
        security_finding_count: 0,
        legal_hold_count: 0,
        expiring_count: 0,
        expired_pending_purge_count: 0,
        retained_count: 501,
      },
      items,
    })).toThrow(/at most 500/);
  });
});

function response(overrides: Record<string, unknown> = {}) {
  return {
    schema_version: "2.0.0",
    surface: "browser-evidence-workspace",
    consistency: "drift_aware",
    summary_scope: "filtered_and_snapshot",
    observed_at: observedAt,
    source_observed_at: "2026-09-15T11:59:00Z",
    loaded_count: 1,
    matching_admitted_count: 1,
    snapshot_total_count: 2,
    snapshot_admitted_count: 1,
    snapshot_withheld_count: 1,
    withheld_reasons: {
      invalid_metadata: 1,
      trust_invalid: 0,
      isolation_unverified: 0,
    },
    summary: {
      security_finding_count: 1,
      legal_hold_count: 1,
      expiring_count: 0,
      expired_pending_purge_count: 0,
      retained_count: 0,
    },
    has_more: false,
    next_cursor: null,
    page_complete: true,
    items: [item(overrides)],
  };
}

function item(overrides: Record<string, unknown> = {}) {
  return {
    artifact_id: `sha256:${"a".repeat(64)}`,
    policy_id: "dashboard",
    policy_version: 4,
    source_host: "dashboard.example",
    final_host: "status.example",
    redirected: true,
    captured_at: "2026-09-14T12:00:00Z",
    expires_at: "2026-10-15T12:00:00Z",
    selector_count: 18,
    redaction_count: 7,
    prompt_injection_finding_count: 1,
    digest_presence: {
      screenshot: true,
      text: true,
      accessibility_snapshot: false,
    },
    browser_version: "chromium-test",
    custody_audit_ref: "00000000-0000-0000-0000-000000000000",
    retention_state: "held",
    legal_hold: true,
    legal_hold_ref: "case:example",
    legal_hold_at: "2026-09-15T11:00:00Z",
    audit: {
      state: "exact",
      sequence: "42",
      correlation_id: "correlation-1",
    },
    isolation_verified: true,
    untrusted: true,
    can_authorize_action: false,
    ...overrides,
  };
}

function retainedItem(index: number) {
  const digest = index.toString(16).padStart(64, "0");
  return item({
    artifact_id: `sha256:${digest}`,
    source_host: `source-${index}.example`,
    final_host: `source-${index}.example`,
    redirected: false,
    captured_at: new Date(Date.parse(observedAt) - index * 60_000).toISOString(),
    prompt_injection_finding_count: 0,
    retention_state: "retained",
    legal_hold: false,
    legal_hold_ref: null,
    legal_hold_at: null,
    audit: { state: "missing", sequence: null, correlation_id: null },
  });
}
