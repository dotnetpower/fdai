import { readFileSync } from "node:fs";
import { describe, expect, it, vi } from "vitest";
import { OperatorApiError } from "../api";
import type { OperatorApiClient } from "../api";
import { parseConsoleRoute } from "../router";
import {
  assuranceTwinReviewHref,
  assuranceTwinReviewIdFromSearch,
  buildAssuranceTwinViewSnapshot,
  loadAssuranceTwinReviewDetail,
  loadAssuranceTwinState,
  type AssuranceTwinFinding,
  type AssuranceTwinPostureReport,
  type AssuranceTwinReviewSummary,
} from "./assurance-twin";

const consoleStyles = readFileSync(new URL("../styles.css", import.meta.url), "utf8");
const routeSource = readFileSync(new URL("./assurance-twin.tsx", import.meta.url), "utf8");

const provenance = {
  activity_id: "assurance-twin.change-review:Review_Key-1:completed",
  correlation_id: "correlation-1",
  evidence_digest: "sha256:1111111111111111111111111111111111111111111111111111111111111111",
  evidence_source_revision: "sha256:2222222222222222222222222222222222222222222222222222222222222222",
};

const finding: AssuranceTwinFinding = {
  rule_id: "r-1",
  resource_type: "compute.vm",
  resource_ref: "vm-a",
  severity: "high",
  reason: "reason",
  evidence_refs: [],
};

const report: AssuranceTwinPostureReport = {
  ...provenance,
  scope: "sub/00000000-0000-0000-0000-000000000001",
  generated_at: "2026-07-07T00:00:00Z",
  mode: "shadow",
  verdict: "blocked",
  blocks_action: false,
  resource_count: 1,
  rule_count: 1,
  highest_severity: "high",
  severity_counts: { low: 0, medium: 0, high: 1, critical: 0 },
  finding_count: 1,
  findings: [finding],
  freshness: "fresh",
  reason_codes: [],
};

const postureResponse = () => ({
  surface: "assurance-twin-posture",
  available: true,
  complete: true,
  source: "postgresql:state_kv:assurance-twin-posture",
  reports: [report],
  gaps: [],
});

const reviewSummary: AssuranceTwinReviewSummary = {
  ...provenance,
  review_key: "Review_Key-1",
  pr_ref: "owner/repo#1",
  generated_at: "2026-07-07T00:00:00Z",
  mode: "shadow",
  verdict: "needs_review",
  finding_count: 1,
  freshness: "fresh",
  reason_codes: [],
};

const reviewsResponse = () => ({
  surface: "assurance-twin-review",
  available: true,
  complete: true,
  source: "postgresql:state_kv:assurance-twin-review",
  reviews: [reviewSummary],
  gaps: [],
});

const reviewDetailResponse = () => ({
  surface: "assurance-twin-review-detail",
  source: "postgresql:state_kv:assurance-twin-review",
  available: true,
  review: { ...reviewSummary, findings: [finding] },
  gap: null,
});

function panelClient(
  handler: (path: string, params?: Record<string, string>) => Promise<unknown>,
): Pick<OperatorApiClient, "panel"> {
  return {
    async panel<T>(path: string, params?: Record<string, string>): Promise<T> {
      return await handler(path, params) as T;
    },
  };
}

describe("assurance twin decoder", () => {
  it("decodes a posture report and review list into one ready state", async () => {
    const handler = vi.fn(async (path: string) => {
      if (path === "/assurance-twin/posture") return postureResponse();
      if (path === "/assurance-twin/reviews") return reviewsResponse();
      throw new Error(`unexpected path ${path}`);
    });
    const state = await loadAssuranceTwinState(panelClient(handler));
    expect(state.status).toBe("ready");
    if (state.status !== "ready") throw new Error("expected ready state");
    expect(state.data.posture.reports[0]?.verdict).toBe("blocked");
    expect(state.data.posture.complete).toBe(true);
    expect(state.data.reviews.reviews[0]?.review_key).toBe("Review_Key-1");

    const snapshot = buildAssuranceTwinViewSnapshot(state.data);
    expect(snapshot).toMatchObject({
      routeId: "assurance-twin",
      facts: expect.arrayContaining([
        expect.objectContaining({ key: "blocked_count", value: 1 }),
      ]),
    });
  });

  it("exposes the replay provenance of every rendered record", async () => {
    const handler = vi.fn(async (path: string) => (
      path === "/assurance-twin/posture" ? postureResponse() : reviewsResponse()
    ));
    const state = await loadAssuranceTwinState(panelClient(handler));
    if (state.status !== "ready") throw new Error("expected ready state");
    expect(state.data.posture.reports[0]?.activity_id).toBe(provenance.activity_id);
    expect(state.data.posture.reports[0]?.evidence_digest).toBe(provenance.evidence_digest);
    expect(state.data.reviews.reviews[0]?.evidence_source_revision)
      .toBe(provenance.evidence_source_revision);
  });

  it("summarizes every posture scope without hiding a blocked report", async () => {
    const data = postureResponse();
    const snapshot = buildAssuranceTwinViewSnapshot({
      posture: {
        ...data,
        reports: [
          { ...report, scope: "scope-clear", verdict: "clear" },
          { ...report, scope: "scope-blocked", verdict: "blocked" },
        ],
      },
      reviews: reviewsResponse(),
    });

    expect(snapshot.facts).toEqual(expect.arrayContaining([
      expect.objectContaining({ key: "posture_report_count", value: 2 }),
      expect.objectContaining({ key: "blocked_count", value: 1 }),
      expect.objectContaining({ key: "clear_count", value: 1 }),
    ]));
  });

  it("classifies an unavailable Operator API as unavailable, not an error", async () => {
    const handler = vi.fn(async () => {
      throw new OperatorApiError(503, "unavailable", "projection-unavailable");
    });
    await expect(loadAssuranceTwinState(panelClient(handler))).resolves.toMatchObject({
      status: "unavailable",
    });
  });

  it("renders withheld evidence as an explicit gap instead of a clear posture", async () => {
    const handler = vi.fn(async (path: string) => {
      if (path === "/assurance-twin/posture") {
        return {
          ...postureResponse(),
          available: false,
          complete: false,
          reports: [],
          gaps: [{
            identity: "sub/00000000-0000-0000-0000-000000000001",
            freshness: "stale",
            reason_code: "evidence_not_fresh",
            reason_codes: ["inventory_freshness_ttl_exceeded"],
          }],
        };
      }
      return reviewsResponse();
    });
    const state = await loadAssuranceTwinState(panelClient(handler));
    if (state.status !== "ready") throw new Error("expected ready state");
    expect(state.data.posture.available).toBe(false);
    expect(state.data.posture.complete).toBe(false);
    expect(state.data.posture.reports).toHaveLength(0);
    expect(state.data.posture.gaps[0]?.reason_code).toBe("evidence_not_fresh");
  });

  it("rejects an envelope that claims availability without any usable report", async () => {
    const handler = vi.fn(async (path: string) => {
      if (path === "/assurance-twin/posture") {
        return { ...postureResponse(), reports: [] };
      }
      return reviewsResponse();
    });
    await expect(loadAssuranceTwinState(panelClient(handler))).resolves.toMatchObject({
      status: "error",
    });
  });

  it("rejects an envelope that claims completeness while reporting gaps", async () => {
    const handler = vi.fn(async (path: string) => {
      if (path === "/assurance-twin/posture") {
        return {
          ...postureResponse(),
          gaps: [{
            identity: null,
            freshness: null,
            reason_code: "evidence_malformed",
            reason_codes: [],
          }],
        };
      }
      return reviewsResponse();
    });
    await expect(loadAssuranceTwinState(panelClient(handler))).resolves.toMatchObject({
      status: "error",
    });
  });

  it("rejects a posture report with an incomplete severity_counts shape", async () => {
    const handler = vi.fn(async (path: string) => {
      if (path === "/assurance-twin/posture") {
        return {
          ...postureResponse(),
          reports: [{ ...report, severity_counts: { low: 0 } }],
        };
      }
      return reviewsResponse();
    });
    await expect(loadAssuranceTwinState(panelClient(handler))).resolves.toMatchObject({
      status: "error",
    });
  });

  it("rejects a posture report whose finding_count does not match its findings", async () => {
    const handler = vi.fn(async (path: string) => {
      if (path === "/assurance-twin/posture") {
        return { ...postureResponse(), reports: [{ ...report, finding_count: 2 }] };
      }
      return reviewsResponse();
    });
    await expect(loadAssuranceTwinState(panelClient(handler))).resolves.toMatchObject({
      status: "error",
    });
  });

  it("decodes one review detail with its finding evidence", async () => {
    const handler = vi.fn(async (path: string, params?: Record<string, string>) => {
      expect(path).toBe("/assurance-twin/review");
      expect(params).toEqual({ review_key: "Review_Key-1" });
      return reviewDetailResponse();
    });
    const state = await loadAssuranceTwinReviewDetail(panelClient(handler), "Review_Key-1");
    expect(state.status).toBe("ready");
    if (state.status !== "ready") throw new Error("expected ready state");
    expect(state.data.available).toBe(true);
    expect(state.data.review?.findings[0]?.rule_id).toBe("r-1");
  });

  it("decodes an explicitly unavailable review detail without inventing a review", async () => {
    const handler = vi.fn(async () => ({
      surface: "assurance-twin-review-detail",
      source: "postgresql:state_kv:assurance-twin-review",
      available: false,
      review: null,
      gap: {
        identity: "Review_Key-1",
        freshness: "unavailable",
        reason_code: "evidence_digest_mismatch",
        reason_codes: [],
      },
    }));
    const state = await loadAssuranceTwinReviewDetail(panelClient(handler), "Review_Key-1");
    if (state.status !== "ready") throw new Error("expected ready state");
    expect(state.data.available).toBe(false);
    expect(state.data.review).toBeNull();
    expect(state.data.gap?.reason_code).toBe("evidence_digest_mismatch");
  });

  it("rejects an unavailable detail envelope that still carries a review", async () => {
    const handler = vi.fn(async () => ({ ...reviewDetailResponse(), available: false }));
    await expect(
      loadAssuranceTwinReviewDetail(panelClient(handler), "Review_Key-1"),
    ).resolves.toMatchObject({ status: "error" });
  });

  it("classifies a not-found review detail as unavailable", async () => {
    const handler = vi.fn(async () => {
      throw new OperatorApiError(404, "not found");
    });
    await expect(
      loadAssuranceTwinReviewDetail(panelClient(handler), "missing"),
    ).resolves.toMatchObject({ status: "unavailable" });
  });
});

describe("assurance twin review identity", () => {
  it("carries an opaque review key as an exact query value", () => {
    expect(assuranceTwinReviewHref("Review_Key-1")).toBe("/assurance-twin?review=Review_Key-1");
    expect(assuranceTwinReviewHref("owner/repo#7 KEY_a"))
      .toBe("/assurance-twin?review=owner%2Frepo%237+KEY_a");
  });

  it("round-trips a slash-bearing review key through the router byte for byte", () => {
    const key = "Owner/Repo#12:Change_A";
    const href = assuranceTwinReviewHref(key);
    const [pathname = "", search = ""] = href.split("?", 2);
    const route = parseConsoleRoute(pathname, search);
    expect(route.panelId).toBe("assurance-twin");
    expect(route.segments).toEqual([]);
    expect(route.canonicalPathname).toBe("/assurance-twin");
    expect(assuranceTwinReviewIdFromSearch(route.search)).toBe(key);
  });

  it("never normalises or lowercases the review key", () => {
    const key = "Owner/Repo#12:Change_A";
    const [, search = ""] = assuranceTwinReviewHref(key).split("?", 2);
    const decoded = assuranceTwinReviewIdFromSearch(new URLSearchParams(search));
    expect(decoded).toBe(key);
    expect(decoded).not.toBe(key.toLowerCase());
  });

  it("treats an absent or empty review parameter as the list view", () => {
    expect(assuranceTwinReviewIdFromSearch(new URLSearchParams(""))).toBeNull();
    expect(assuranceTwinReviewIdFromSearch(new URLSearchParams("review="))).toBeNull();
  });

  it("requests the detail endpoint with the exact unencoded key", async () => {
    const key = "Owner/Repo#12:Change_A";
    const handler = vi.fn(async (path: string, params?: Record<string, string>) => {
      expect(path).toBe("/assurance-twin/review");
      expect(params).toEqual({ review_key: key });
      return {
        ...reviewDetailResponse(),
        review: { ...reviewSummary, review_key: key, findings: [finding] },
      };
    });
    const state = await loadAssuranceTwinReviewDetail(panelClient(handler), key);
    if (state.status !== "ready") throw new Error("expected ready state");
    expect(state.data.review?.review_key).toBe(key);
    expect(handler).toHaveBeenCalledOnce();
  });
});

describe("assurance twin responsive evidence", () => {
  it("wraps opaque provenance without expanding the primary content viewport", () => {
    expect(consoleStyles).toMatch(
      /\.assurance-twin-provenance\s*\{[^}]*min-width:\s*0;[^}]*\}/,
    );
    expect(consoleStyles).toMatch(
      /\.assurance-twin-provenance dd\s*\{[^}]*min-width:\s*0;[^}]*overflow-wrap:\s*anywhere;[^}]*\}/,
    );
  });

  it("keeps primary mobile navigation links at touch-target height", () => {
    expect(routeSource.match(
      /<a class="assurance-twin-back-link" href=\{routeHref\("assurance-twin"\)\}>/g,
    )).toHaveLength(2);
    expect(routeSource).toContain(
      '<a class="mono assurance-twin-review-link" href={assuranceTwinReviewHref(row.review_key)}>',
    );

    const mobileTouchRule = [
      "@media (max-width: 640px) {",
      "  .assurance-twin-back-link,",
      "  .assurance-twin-review-link {",
      "    display: inline-flex;",
      "    min-height: 44px;",
      "    width: fit-content;",
      "    align-items: center;",
      "  }",
      "}",
    ].join("\n");
    expect(consoleStyles).toContain(mobileTouchRule);
    expect(consoleStyles.replace(mobileTouchRule, "")).not.toMatch(
      /\.assurance-twin-back-link\s*,\s*\.assurance-twin-review-link\s*\{[^}]*min-height:\s*44px;/,
    );
  });
});
