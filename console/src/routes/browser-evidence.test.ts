import { describe, expect, it, vi } from "vitest";
import { OperatorApiError } from "../api";
import type { OperatorApiClient } from "../api";
import { browserEvidenceRequest } from "./browser-evidence.model";
import {
  buildBrowserEvidenceViewSnapshot,
  loadBrowserEvidenceState,
} from "./browser-evidence";

const page = {
  schema_version: "2.0.0",
  surface: "browser-evidence-workspace",
  consistency: "drift_aware",
  summary_scope: "filtered_and_snapshot",
  observed_at: "2026-09-15T12:00:00Z",
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
    security_finding_count: 0,
    legal_hold_count: 0,
    expiring_count: 0,
    expired_pending_purge_count: 0,
    retained_count: 1,
  },
  has_more: false,
  next_cursor: null,
  page_complete: true,
  items: [{
    artifact_id: `sha256:${"a".repeat(64)}`,
    policy_id: "dashboard",
    policy_version: 4,
    source_host: "dashboard.example",
    final_host: "dashboard.example",
    redirected: false,
    captured_at: "2026-09-14T12:00:00Z",
    expires_at: "2026-10-15T12:00:00Z",
    selector_count: 1,
    redaction_count: 1,
    prompt_injection_finding_count: 0,
    digest_presence: {
      screenshot: false,
      text: true,
      accessibility_snapshot: false,
    },
    browser_version: "chromium-test",
    custody_audit_ref: "00000000-0000-0000-0000-000000000000",
    retention_state: "retained",
    legal_hold: false,
    legal_hold_ref: null,
    legal_hold_at: null,
    audit: {
      state: "missing",
      sequence: null,
      correlation_id: null,
    },
    isolation_verified: true,
    untrusted: true,
    can_authorize_action: false,
  }],
};

function panelClient(
  handler: (
    path: string,
    params?: Record<string, string>,
  ) => Promise<unknown>,
): Pick<OperatorApiClient, "panel"> {
  return {
    async panel<T>(path: string, params?: Record<string, string>): Promise<T> {
      return await handler(path, params) as T;
    },
  };
}

describe("Browser evidence route loading", () => {
  it("requires the versioned workspace and preserves exact filters", async () => {
    const handler = vi.fn(async () => page);
    const request = browserEvidenceRequest(new URLSearchParams(
      "host=dashboard.example&retention=retained",
    ));

    const state = await loadBrowserEvidenceState(panelClient(handler), request);

    expect(state.status).toBe("ready");
    expect(handler).toHaveBeenCalledWith("/browser-evidence/snapshot", {
      limit: "25",
      host: "dashboard.example",
      retention: "retained",
    });
  });

  it("does not turn a missing v2 route into v1-shaped evidence", async () => {
    const handler = vi.fn(async () => {
      throw new OperatorApiError(404, "missing");
    });

    await expect(loadBrowserEvidenceState(
      panelClient(handler),
      browserEvidenceRequest(new URLSearchParams()),
    )).resolves.toMatchObject({ status: "unavailable" });
    expect(handler).toHaveBeenCalledTimes(1);
  });

  it("keeps malformed workspace data as an error", async () => {
    const handler = vi.fn(async () => ({ ...page, loaded_count: 0 }));

    await expect(loadBrowserEvidenceState(
      panelClient(handler),
      browserEvidenceRequest(new URLSearchParams()),
    )).resolves.toMatchObject({ status: "error" });
  });

  it("publishes only visible metadata at the authoritative observation time", async () => {
    const state = await loadBrowserEvidenceState(
      panelClient(async () => page),
      browserEvidenceRequest(new URLSearchParams()),
    );
    if (state.status !== "ready") throw new Error("expected ready state");

    const snapshot = buildBrowserEvidenceViewSnapshot(
      state.data,
      page.items[0]!.artifact_id,
    );

    expect(snapshot.capturedAt).toBe(page.observed_at);
    expect(snapshot).toMatchObject({
      routeId: "browser-evidence",
      facts: expect.arrayContaining([
        expect.objectContaining({ key: "matching_admitted_count", value: 1 }),
        expect.objectContaining({ key: "snapshot_withheld_count", value: 1 }),
      ]),
    });
    expect(snapshot.records?.["selected_artifact"]?.[0]).toMatchObject({
      artifact_id: page.items[0]!.artifact_id,
      browser_version: "chromium-test",
      can_authorize_action: false,
    });
    expect(snapshot.records?.["artifacts"]?.[0]).not.toHaveProperty("artifact_id");
    expect(JSON.stringify(snapshot)).not.toContain("visible_text");
  });
});
