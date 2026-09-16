import { readFileSync } from "node:fs";
import { describe, expect, test } from "vitest";
import {
  decodeReportLineContactRequests,
  decodeReportingLineProjection,
} from "./report-lines.model";

function projection() {
  return {
    schema_version: "1.0.0",
    graph_revision: "a".repeat(64),
    items: [{
      operator_case_id: `operator-${"b".repeat(32)}`,
      case_id: "00000000-0000-0000-0000-000000000001",
      candidate_id: `report-line-${"c".repeat(32)}`,
      upload_id: "00000000-0000-0000-0000-000000000002",
      requester_ref: "uploader",
      subject_ref: "person-a",
      manager_ref: "person-b",
      state: "pending_confirmation",
      revision: 1,
      edge_digest: "d".repeat(64),
      directory_comparison: "matched",
      can_confirm: true,
      can_review: false,
      effective_from: "2026-09-16T01:00:00Z",
      effective_until: "2026-12-15T01:00:00Z",
      execution_authority: false,
      approval_authority: false,
    }],
    total: 1,
    next_cursor: null,
    summary: {
      active: 0,
      pending_confirmation: 1,
      pending_owner_review: 0,
      activation_pending: 0,
      conflict: 0,
      awaiting_core: 0,
    },
    execution_authority: false,
    approval_authority: false,
  };
}

describe("reporting-line projection", () => {
  test("decodes exact edge identity, review permissions, and summary", () => {
    const value = decodeReportingLineProjection(projection());

    expect(value.graphRevision).toHaveLength(64);
    expect(value.items[0]).toMatchObject({
      subjectRef: "person-a",
      managerRef: "person-b",
      state: "pending_confirmation",
      canConfirm: true,
      canReview: false,
    });
    expect(value.summary.pendingConfirmation).toBe(1);
  });

  test("rejects an unknown lifecycle state", () => {
    const value = projection();
    value.items[0]!.state = "approved";

    expect(() => decodeReportingLineProjection(value)).toThrow(/unsupported value/);
  });

  test("rejects authority-bearing graph and edge projections", () => {
    const graph = projection();
    graph.execution_authority = true;
    expect(() => decodeReportingLineProjection(graph)).toThrow(/cannot grant/);

    const edge = projection();
    edge.items[0]!.approval_authority = true;
    expect(() => decodeReportingLineProjection(edge)).toThrow(/cannot grant/);
  });

  test("decodes requester-only contact consent without approval authority", () => {
    const requests = decodeReportLineContactRequests({
      items: [{
        approval_id: "approval-1",
        consent_id: "consent-1",
        consent_revision: 0,
        action_type: "ops.restart-service",
        target_ref: "scope://service/example",
        route_subjects: ["manager-a"],
        expires_at: "2026-09-16T01:05:00Z",
        approval_authority: false,
        execution_authority: false,
      }],
      total: 1,
    });

    expect(requests[0]).toMatchObject({
      approvalId: "approval-1",
      consentRevision: 0,
      routeSubjects: ["manager-a"],
    });
  });

  test("rejects an authority-bearing contact request", () => {
    expect(() => decodeReportLineContactRequests({
      items: [{
        approval_id: "approval-1",
        consent_id: "consent-1",
        consent_revision: 0,
        action_type: "ops.restart-service",
        target_ref: "scope://service/example",
        route_subjects: ["manager-a"],
        expires_at: "2026-09-16T01:05:00Z",
        approval_authority: true,
        execution_authority: false,
      }],
      total: 1,
    })).toThrow(/cannot grant/);
  });
});

describe("reporting-line workspace safety", () => {
  test("uses the explicit document purpose and edge-level commands", () => {
    const source = readFileSync(new URL("./report-lines.tsx", import.meta.url), "utf8");

    expect(source).toContain('purposes: ["report_line_bootstrap"]');
    expect(source).toContain("candidate.candidate_id");
    expect(source).toContain('operation: "confirm" | "review"');
    expect(source).toContain("edge_digest: item.edgeDigest");
    expect(source).toContain("selected.size === 0");
  });

  test("exposes accessible native controls and technical evidence", () => {
    const source = readFileSync(new URL("./report-lines.tsx", import.meta.url), "utf8");

    expect(source).toContain('type="file"');
    expect(source).toContain('type="checkbox"');
    expect(source).toContain("<details>");
    expect(source).toContain('role="alert"');
  });
});
