import { describe, expect, it, vi } from "vitest";
import { OperatorApiError } from "../api";
import type { OperatorApiClient } from "../api";
import { parseConsoleRoute } from "../router";
import { panelSourceClassification } from "../panel-sources";
import {
  buildCodeSecurityViewSnapshot,
  decodeCodeSecurityReviews,
  latestPerRepository,
  loadCodeSecurityState,
} from "./code-security";

function review(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    repository_alias: "example-service",
    revision: "a".repeat(40),
    review_digest: "4".repeat(64),
    recorded_at: "2026-10-07T00:00:00+00:00",
    issue_count: 2,
    by_priority: { P0: 1, P1: 1, P2: 0, P3: 0, P4: 0 },
    by_severity: { critical: 1, high: 0, medium: 0, low: 0, undetermined: 1 },
    by_confidence: { hypothesis: 0, reported: 1, corroborated: 0, verified: 1, proven: 0 },
    known_exploited_count: 0,
    exposure: "exposed",
    coverage_complete: true,
    top_issue_ids: ["FDAI-SEC-0123456789ab"],
    decision: "urgent",
    ...overrides,
  };
}

function envelope(reviews: unknown[], gaps: unknown[] = []): Record<string, unknown> {
  return {
    surface: "code-security-reviews",
    available: reviews.length > 0,
    complete: gaps.length === 0,
    source: "postgresql:state_kv:code-security-review",
    reviews,
    gaps,
  };
}

function client(panel: (path: string) => Promise<unknown>): Pick<OperatorApiClient, "panel"> {
  return { panel: vi.fn(panel) as unknown as OperatorApiClient["panel"] };
}

describe("code-security route", () => {
  it("registers a dedicated route and its single read source", () => {
    expect(parseConsoleRoute("/code-security").panelId).toBe("code-security");
    expect(panelSourceClassification("code-security")).toBe("operator-api");
  });

  it("decodes reviews and keeps the newest review per repository", () => {
    const data = decodeCodeSecurityReviews(envelope([
      review({ revision: "b".repeat(40), recorded_at: "2026-10-08T00:00:00+00:00", decision: "clear", issue_count: 0 }),
      review(),
      review({ repository_alias: "other-service", decision: "coverage_incomplete", coverage_complete: false }),
    ]));
    expect(data.reviews).toHaveLength(3);
    const latest = latestPerRepository(data.reviews);
    expect(latest.map((item) => [item.repository_alias, item.decision])).toEqual([
      ["example-service", "clear"],
      ["other-service", "coverage_incomplete"],
    ]);
    const snapshot = buildCodeSecurityViewSnapshot(data);
    expect(snapshot.routeId).toBe("code-security");
    expect(snapshot.facts.find((fact) => fact.key === "urgent_count")?.value).toBe(0);
  });

  it("rejects contract drift instead of rendering it", () => {
    expect(() => decodeCodeSecurityReviews(envelope([review({ decision: "approved" })]))).toThrow();
    expect(() => decodeCodeSecurityReviews(envelope([review({ by_priority: { P0: 1 } })]))).toThrow();
    expect(() => decodeCodeSecurityReviews(envelope([], [{ reason_code: "unknown" }]))).toThrow();
  });

  it("reports withheld rows as gaps", async () => {
    const state = await loadCodeSecurityState(client(async () =>
      envelope([], [{ reason_code: "code_security_review_malformed" }])));
    expect(state.status).toBe("ready");
    if (state.status === "ready") {
      expect(state.data.available).toBe(false);
      expect(state.data.gaps).toEqual(["code_security_review_malformed"]);
    }
  });

  it("maps an unavailable Operator source to the unavailable state", async () => {
    const state = await loadCodeSecurityState(client(async () => {
      throw new OperatorApiError(503, "unavailable", "projection-unavailable");
    }));
    expect(state.status).toBe("unavailable");
  });
});
