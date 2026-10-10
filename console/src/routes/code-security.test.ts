import { describe, expect, it, vi } from "vitest";
import { OperatorApiError } from "../api";
import type { OperatorApiClient } from "../api";
import { parseConsoleRoute } from "../router";
import { panelSourceClassification } from "../panel-sources";
import {
  buildCodeSecurityViewSnapshot,
  codeSecurityRefreshDelay,
  decodeCodeSecurityPacks,
  decodeCodeSecurityReviews,
  filterBySource,
  latestPerRepository,
  loadCodeSecurityState,
  packState,
  sourceCategory,
} from "./code-security";
import {
  decodeCodeSecurityRepositories,
  decodeCodeSecurityScanRequests,
  decodeCodeSecurityWorkerStatus,
  scanRequestIdempotencyKey,
} from "./code-security-requests";
import { decodeCodeSecurityIssues, issueReference } from "./code-security-issues";
import {
  normalizeGitHubLocation,
  registrationInputValid,
  repositoryAliasSuggestion,
  repositoryChangeIdempotencyKey,
} from "./code-security-registration";

function packEnvelope(packs: unknown[], gaps: unknown[] = []): Record<string, unknown> {
  return {
    surface: "code-security-packs",
    available: packs.length > 0,
    complete: gaps.length === 0,
    source: "postgresql:state_kv:code-security-pack",
    packs,
    gaps,
  };
}

function pack(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    pack_id: "0123456789ab",
    base_commit: "a".repeat(40),
    issue_count: 2,
    recorded_at: "2026-10-07T00:00:00+00:00",
    expires_at: "2099-10-14T00:00:00+00:00",
    revoked: false,
    latest_verification: {
      rescan_revision: "b".repeat(40),
      recorded_at: "2026-10-08T00:00:00+00:00",
      verdicts: { fixed_verified: 1, still_present: 1, inconclusive: 0, not_applicable: 0 },
    },
    adjudications: [
      {
        issue_id: "FDAI-SEC-ba9876543210",
        decision: "accepted",
        issue_disposition: "false_positive",
        adjudicator: "lead@example.com",
        decided_at: "2026-10-08T01:00:00+00:00",
      },
    ],
    ...overrides,
  };
}

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

  it("uses bounded refresh intervals for active and idle requests", () => {
    const base = {
      reviews: decodeCodeSecurityReviews(envelope([])),
      packs: decodeCodeSecurityPacks(packEnvelope([])),
    };
    expect(codeSecurityRefreshDelay({ status: "loading" })).toBeNull();
    expect(codeSecurityRefreshDelay({ status: "error", message: "temporary" })).toBe(15_000);
    expect(codeSecurityRefreshDelay({ status: "unavailable", message: "offline" })).toBe(15_000);
    expect(codeSecurityRefreshDelay({
      status: "ready",
      data: {
        ...base,
        requests: { requests: [], gaps: [] },
      },
    })).toBe(30_000);
    expect(codeSecurityRefreshDelay({
      status: "ready",
      data: {
        ...base,
        requests: {
          requests: [{
            request_id: `operator-${"a".repeat(32)}`,
            kind: "scan",
            action: null,
            location: null,
            repository_alias: "example-app",
            ref: null,
            status: "queued",
            accepted_at: "2026-10-10T01:00:00+00:00",
            closed_at: null,
            rejection_reason: null,
            result: null,
          }],
          gaps: [],
        },
      },
    })).toBe(5_000);
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
    const snapshot = buildCodeSecurityViewSnapshot({ reviews: data, packs: decodeCodeSecurityPacks(packEnvelope([])) });
    expect(snapshot.routeId).toBe("code-security");
    expect(snapshot.facts.find((fact) => fact.key === "urgent_count")?.value).toBe(0);
  });

  it("rejects contract drift instead of rendering it", () => {
    expect(() => decodeCodeSecurityReviews(envelope([review({ decision: "approved" })]))).toThrow();
    expect(() => decodeCodeSecurityReviews(envelope([review({ by_priority: { P0: 1 } })]))).toThrow();
    expect(() => decodeCodeSecurityReviews(envelope([], [{ reason_code: "unknown" }]))).toThrow();
  });

  it("reports withheld rows as gaps", async () => {
    const state = await loadCodeSecurityState(client(async (path) => {
      if (path === "/code-security/repositories") return { repositories: [], gaps: [] };
      if (path === "/code-security/scan-requests") return { requests: [], gaps: [] };
      if (path === "/code-security/worker-status") {
        return { available: false, complete: true, status: null, gaps: [] };
      }
      return path === "/code-security/packs"
        ? packEnvelope([], [{ reason_code: "code_security_pack_malformed" }])
        : envelope([], [{ reason_code: "code_security_review_malformed" }]);
    }));
    expect(state.status).toBe("ready");
    if (state.status === "ready") {
      expect(state.data.reviews.available).toBe(false);
      expect(state.data.reviews.gaps).toEqual(["code_security_review_malformed"]);
      expect(state.data.packs.gaps).toEqual(["code_security_pack_malformed"]);
    }
  });

  it("maps an unavailable Operator source to the unavailable state", async () => {
    const state = await loadCodeSecurityState(client(async () => {
      throw new OperatorApiError(503, "unavailable", "projection-unavailable");
    }));
    expect(state.status).toBe("unavailable");
  });

  it("decodes packs with verdict counts, adjudications, and lifecycle state", () => {
    const data = decodeCodeSecurityPacks(packEnvelope([
      pack(),
      pack({ pack_id: "ba9876543210", revoked: true, latest_verification: null, adjudications: [] }),
      pack({ pack_id: "aaaaaaaaaaaa", expires_at: "2020-01-01T00:00:00+00:00" }),
    ]));
    const now = new Date("2026-10-09T00:00:00Z");
    expect(data.packs.map((item) => packState(item, now))).toEqual(["active", "revoked", "expired"]);
    expect(data.packs[0]?.latest_verification?.verdicts.fixed_verified).toBe(1);
    expect(data.packs[1]?.latest_verification).toBeNull();
    expect(() => decodeCodeSecurityPacks(packEnvelope([pack({ adjudications: [{ decision: "maybe" }] })]))).toThrow();
  });

  it("decodes review sources and filters by source with legacy reviews kept visible", () => {
    const data = decodeCodeSecurityReviews(envelope([
      review({
        source: { kind: "external_sarif", provider: "mdash", revision_kind: "commit", trigger: "cli", request_id: null },
        producers: ["MDASH"],
      }),
      review({
        repository_alias: "local-app",
        source: { kind: "local_path", provider: "local", revision_kind: "snapshot", trigger: "cli", request_id: null },
        producers: ["Opengrep"],
      }),
      review({
        repository_alias: "repo-app",
        source: {
          kind: "git_repository",
          provider: "github",
          revision_kind: "commit",
          trigger: "console",
          request_id: `operator-${"a".repeat(32)}`,
        },
        producers: [],
      }),
      review({ repository_alias: "legacy-app", source: null, producers: [] }),
    ]));
    expect(data.reviews.map(sourceCategory)).toEqual(["external_sarif", "local_path", "git_repository", "legacy"]);
    expect(filterBySource(data.reviews, "external_sarif").map((item) => item.source?.provider)).toEqual(["mdash"]);
    expect(filterBySource(data.reviews, "legacy").map((item) => item.repository_alias)).toEqual(["legacy-app"]);
    expect(filterBySource(data.reviews, "all")).toHaveLength(4);
    expect(() => decodeCodeSecurityReviews(envelope([review({ source: { kind: "ftp" } })]))).toThrow();
  });

  it("loads registrations and requests without hiding reviews when they are unavailable", async () => {
    const state = await loadCodeSecurityState(client(async (path) => {
      if (
        path === "/code-security/repositories"
        || path === "/code-security/scan-requests"
        || path === "/code-security/worker-status"
      ) {
        throw new OperatorApiError(503, "unavailable", "projection-unavailable");
      }
      return path === "/code-security/packs" ? packEnvelope([]) : envelope([review()]);
    }));
    expect(state.status).toBe("ready");
    if (state.status === "ready") {
      expect(state.data.reviews.reviews).toHaveLength(1);
      expect(state.data.repositories).toBeNull();
      expect(state.data.requests).toBeNull();
      expect(state.data.worker).toBeNull();
    }
  });

  it("decodes registered repositories and scan requests strictly", () => {
    const repositories = decodeCodeSecurityRepositories({
      repositories: [{
        repository_alias: "example-app",
        provider: "github",
        location: "example/app",
        default_ref: "main",
        exposure: "exposed",
        enabled: true,
        registered_at: "2026-10-08T00:00:00+00:00",
      }],
      gaps: [],
    });
    expect(repositories.repositories[0]?.location).toBe("example/app");
    const base = {
      request_id: `operator-${"a".repeat(32)}`,
      kind: "scan",
      action: null,
      location: null,
      repository_alias: "example-app",
      ref: null,
      accepted_at: "2026-10-08T00:00:00+00:00",
      closed_at: null,
      rejection_reason: null,
      result: null,
    };
    const requests = decodeCodeSecurityScanRequests({
      requests: [
        { ...base, status: "queued" },
        {
          ...base,
          status: "completed",
          closed_at: "2026-10-08T00:05:00+00:00",
          result: { revision: "b".repeat(40), decision: "open", issue_count: 2, coverage_complete: true },
        },
        { ...base, status: "rejected", rejection_reason: "repository_disabled" },
      ],
      gaps: [],
    });
    expect(requests.requests.map((item) => item.status)).toEqual(["queued", "completed", "rejected"]);
    expect(() => decodeCodeSecurityScanRequests({ requests: [{ ...base, status: "completed" }], gaps: [] })).toThrow();
    expect(() => decodeCodeSecurityScanRequests({ requests: [{ ...base, status: "approved" }], gaps: [] })).toThrow();
    expect(() => decodeCodeSecurityRepositories({ repositories: [{ provider: "gitlab" }], gaps: [] })).toThrow();
  });

  it("derives a distinct idempotency key per deliberate submission", () => {
    expect(scanRequestIdempotencyKey("example-app", "", "n1")).toBe("code-security-scan:example-app:default:n1");
    expect(scanRequestIdempotencyKey("example-app", "v1", "n2")).not.toBe(
      scanRequestIdempotencyKey("example-app", "v1", "n3"),
    );
  });

  it("decodes repository change requests next to scans", () => {
    const requests = decodeCodeSecurityScanRequests({
      requests: [
        {
          request_id: `operator-${"b".repeat(32)}`,
          kind: "repository_change",
          action: "register",
          location: "example/app",
          repository_alias: "example-app",
          ref: null,
          status: "completed",
          accepted_at: "2026-10-08T00:00:00+00:00",
          closed_at: "2026-10-08T00:01:00+00:00",
          rejection_reason: null,
          result: { enabled: true },
        },
        {
          request_id: `operator-${"c".repeat(32)}`,
          kind: "repository_change",
          action: "enable",
          location: null,
          repository_alias: "other",
          ref: null,
          status: "rejected",
          accepted_at: "2026-10-08T00:00:00+00:00",
          closed_at: "2026-10-08T00:01:00+00:00",
          rejection_reason: "repository_conflict",
          result: null,
        },
      ],
      gaps: [],
    });
    expect(requests.requests.map((item) => [item.kind, item.action])).toEqual([
      ["repository_change", "register"],
      ["repository_change", "enable"],
    ]);
    expect(requests.requests[0]?.result).toEqual({ enabled: true });
    expect(() => decodeCodeSecurityScanRequests({ requests: [{ kind: "delete" }], gaps: [] })).toThrow();
  });

  it("decodes automatic initial scans and worker status", () => {
    const requests = decodeCodeSecurityScanRequests({
      requests: [{
        request_id: `operator-${"d".repeat(32)}`,
        kind: "repository_change",
        action: "register",
        location: "example/app",
        repository_alias: "example-app",
        ref: null,
        status: "completed",
        accepted_at: "2026-10-10T01:00:00+00:00",
        closed_at: "2026-10-10T01:01:00+00:00",
        rejection_reason: null,
        result: {
          enabled: true,
          initial_scan: {
            status: "completed",
            revision: "a".repeat(40),
            decision: "clear",
            issue_count: 0,
            coverage_complete: true,
          },
        },
      }],
      gaps: [],
    });
    expect(requests.requests[0]?.result).toEqual({
      enabled: true,
      initial_scan: {
        status: "completed",
        revision: "a".repeat(40),
        decision: "clear",
        issue_count: 0,
        coverage_complete: true,
      },
    });
    const worker = decodeCodeSecurityWorkerStatus({
      available: true,
      complete: true,
      status: {
        state: "ready",
        phase: "idle",
        fresh: true,
        recorded_at: "2026-10-10T01:00:00+00:00",
        next_request_at: "2026-10-10T01:00:05+00:00",
        next_schedule_at: "2026-10-10T01:05:00+00:00",
        request_interval_seconds: 5,
        schedule_interval_seconds: 300,
        request_processed: 1,
        schedule_checked: 2,
        schedule_scanned: 1,
        schedule_unchanged: 1,
        schedule_failed: 0,
      },
      gaps: [],
    });
    expect(worker.status?.fresh).toBe(true);
  });

  it("decodes issue summaries and renders their reference without paths", () => {
    const data = decodeCodeSecurityIssues({
      available: true,
      issues: [
        {
          issue_id: "FDAI-SEC-0123456789ab",
          priority: "P1",
          due_days: 7,
          severity: "high",
          confidence: "verified",
          weakness_class: "command_injection",
          cwe_ids: [78],
          advisory_ids: [],
          package: null,
          producers: ["Opengrep"],
          known_exploited: false,
        },
        {
          issue_id: "FDAI-SEC-ba9876543210",
          priority: "P3",
          due_days: 90,
          severity: "medium",
          confidence: "corroborated",
          weakness_class: "vulnerable_dependency",
          cwe_ids: [],
          advisory_ids: ["CVE-2026-0001"],
          package: "flask",
          producers: ["Trivy", "osv-scanner"],
          known_exploited: true,
        },
      ],
      artifacts: {
        mode: "full",
        html: "<!doctype html><title>report</title>",
        sarif: '{"version":"2.1.0","runs":[]}',
      },
      gaps: [{ reason_code: "code_security_issues_truncated" }],
    });
    expect(data.issues.map(issueReference)).toEqual(["CWE-78", "flask CVE-2026-0001"]);
    expect(data.gaps).toEqual(["code_security_issues_truncated"]);
    expect(data.artifacts?.html).toContain("<!doctype html>");
    expect(() => decodeCodeSecurityIssues({ available: true, issues: [{ priority: "P9" }], gaps: [] })).toThrow();
  });

  it("validates registration input before submitting an Owner change", () => {
    expect(registrationInputValid("example-app", "example/app", "")).toBe(true);
    expect(registrationInputValid("example-app", "example/app", "release/1")).toBe(true);
    expect(registrationInputValid("bad alias", "example/app", "")).toBe(false);
    expect(registrationInputValid("a", "https://github.com/example/app", "")).toBe(false);
    expect(registrationInputValid("a", "example/app", "../main")).toBe(false);
    expect(normalizeGitHubLocation("https://github.com/example/app.git")).toBe("example/app");
    expect(normalizeGitHubLocation("https://github.com/example/app/?tab=readme")).toBe(
      "https://github.com/example/app/?tab=readme",
    );
    expect(repositoryAliasSuggestion("https://github.com/example/new-service")).toBe("new-service");
    expect(repositoryChangeIdempotencyKey({ action: "disable", repository_alias: "a" }, "n1"))
      .toBe("code-security-repository:disable:a:n1");
  });
});
