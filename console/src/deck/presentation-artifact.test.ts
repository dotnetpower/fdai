import { describe, expect, it } from "vitest";
import type { AnswerVerification } from "./backend-types";
import {
  parsePresentationArtifact,
  parsePersistedPresentationArtifact,
  presentationArtifactToWire,
  presentationArtifactSupersedesText,
} from "./presentation-artifact";

const ref = "subscription-health:test@2026-08-05T00:00:00Z";
const verification: AnswerVerification = {
  status: "verified",
  authority: "server_subscription_health",
  checks_completed: 1,
  checks_total: 1,
  evidence_refs: [ref],
  reason_code: "subscription_health_grounded",
};

function artifact(): Record<string, unknown> {
  return {
    schema_version: 1,
    layout: "stack",
    evidence_refs: [ref],
    blocks: [
      {
        slot_id: "overview",
        kind: "summary",
        title: "Azure scope health",
        emphasis: "primary",
        collapsed: false,
        evidence_refs: [ref],
        data: {
          items: [{ label: "Resources checked", value: "454", tone: "neutral" }],
        },
      },
      {
        slot_id: "coverage",
        kind: "coverage",
        title: "Metric observation coverage",
        emphasis: "secondary",
        collapsed: false,
        evidence_refs: [ref],
        data: {
          items: [
            { label: "Checked", value: 11, tone: "positive" },
            { label: "Unavailable", value: 5, tone: "warning" },
            { label: "Unsupported", value: 413, tone: "neutral" },
          ],
        },
      },
    ],
  };
}

function timeSeriesArtifact(): Record<string, unknown> {
  return {
    schema_version: 2,
    layout: "stack",
    evidence_refs: [ref],
    blocks: [
      {
        slot_id: "trend",
        kind: "time_series",
        title: "Verified trend",
        emphasis: "primary",
        collapsed: false,
        evidence_refs: [ref],
        data: {
          description: "Ordered request observations.",
          metric: "requests",
          unit: "count",
          points: [
            { timestamp: "2026-08-19T00:00:00Z", value: 1 },
            { timestamp: "2026-08-19T00:01:00Z", value: 3 },
            { timestamp: "2026-08-19T00:02:00Z", value: 2 },
          ],
          exact_table: {
            columns: [
              { key: "c0", label: "timestamp" },
              { key: "c1", label: "value" },
            ],
            rows: [
              { c0: "2026-08-19T00:00:00Z", c1: "1" },
              { c0: "2026-08-19T00:01:00Z", c1: "3" },
              { c0: "2026-08-19T00:02:00Z", c1: "2" },
            ],
            status_key: null,
          },
        },
      },
    ],
  };
}

function exactTable(): Record<string, unknown> {
  return {
    columns: [{ key: "value", label: "Value" }],
    rows: [{ value: "1" }],
    status_key: null,
  };
}

function visualArtifact(slot: string, kind: string, data: Record<string, unknown>) {
  return {
    schema_version: 2,
    layout: "stack",
    evidence_refs: [ref],
    blocks: [{
      slot_id: slot,
      kind,
      title: "Verified visualization",
      emphasis: "primary",
      collapsed: false,
      evidence_refs: [ref],
      data,
    }],
  };
}

describe("presentation artifact boundary", () => {
  it("accepts bounded blocks whose refs are verified", () => {
    const parsed = parsePresentationArtifact(artifact(), verification);

    expect(parsed?.blocks.map((block) => block.slotId)).toEqual(["overview", "coverage"]);
    expect(parsed?.blocks[1]?.kind).toBe("coverage");
  });

  it("accepts recorded root cause, impact, and citation blocks", () => {
    const raw = artifact();
    raw.blocks = [
      {
        slot_id: "root_cause",
        kind: "summary",
        title: "Root cause",
        emphasis: "primary",
        collapsed: false,
        evidence_refs: [ref],
        data: { items: [{ label: "Cause", value: "Owner tag missing", tone: "neutral" }] },
      },
      {
        slot_id: "impact",
        kind: "table",
        title: "Impact evidence",
        emphasis: "secondary",
        collapsed: false,
        evidence_refs: [ref],
        data: {
          columns: [{ key: "metric", label: "Metric" }],
          rows: [{ metric: "noncompliant_resources" }],
          status_key: null,
        },
      },
      {
        slot_id: "citations",
        kind: "table",
        title: "Grounded citations",
        emphasis: "supporting",
        collapsed: false,
        evidence_refs: [ref],
        data: {
          columns: [{ key: "ref", label: "Reference" }],
          rows: [{ ref: "object-storage.owner-tag.required" }],
          status_key: null,
        },
      },
    ];

    const parsed = parsePresentationArtifact(raw, verification);

    expect(parsed?.blocks.map((block) => [block.slotId, block.kind])).toEqual([
      ["root_cause", "summary"],
      ["impact", "table"],
      ["citations", "table"],
    ]);
  });

  it("rejects refs outside terminal verification", () => {
    const raw = artifact();
    raw.evidence_refs = ["subscription-health:other@2026-08-05T00:00:00Z"];

    expect(parsePresentationArtifact(raw, verification)).toBeUndefined();
  });

  it("rejects duplicate slots and unknown blocks", () => {
    const duplicate = artifact();
    const blocks = duplicate.blocks as Record<string, unknown>[];
    blocks[1] = { ...blocks[1], slot_id: "overview" };
    expect(parsePresentationArtifact(duplicate, verification)).toBeUndefined();

    const unknown = artifact();
    (unknown.blocks as Record<string, unknown>[])[0]!.kind = "html";
    expect(parsePresentationArtifact(unknown, verification)).toBeUndefined();
  });

  it("rejects a valid generic kind on the wrong semantic slot", () => {
    const raw = artifact();
    const blocks = raw.blocks as Record<string, unknown>[];
    blocks[0] = { ...blocks[1], slot_id: "overview" };

    expect(parsePresentationArtifact(raw, verification)).toBeUndefined();
  });

  it("rejects oversized rows and unsafe text", () => {
    const raw = artifact();
    const blocks = raw.blocks as Record<string, unknown>[];
    blocks[0]!.title = "x".repeat(513);
    expect(parsePresentationArtifact(raw, verification)).toBeUndefined();

    const control = artifact();
    (control.blocks as Record<string, unknown>[])[0]!.title = "bad\u0000title";
    expect(parsePresentationArtifact(control, verification)).toBeUndefined();
  });

  it("keeps partial verified facts renderable under unverified status", () => {
    const parsed = parsePresentationArtifact(artifact(), {
      ...verification,
      status: "unverified",
      checks_completed: 0,
      reason_code: "subscription_health_partial",
    });

    expect(parsed).toBeDefined();
  });

  it("rejects duplicate item labels used as renderer keys", () => {
    const raw = artifact();
    const blocks = raw.blocks as Record<string, unknown>[];
    const data = blocks[1]!.data as { items: Record<string, unknown>[] };
    data.items[1]!.label = "Checked";

    expect(parsePresentationArtifact(raw, verification)).toBeUndefined();
  });

  it("supersedes the answer text only when it carries content beyond the overview", () => {
    const withCoverage = parsePresentationArtifact(artifact(), verification);
    const overviewOnly = artifact();
    overviewOnly.blocks = (overviewOnly.blocks as unknown[]).slice(0, 1);
    const parsedOverviewOnly = parsePresentationArtifact(overviewOnly, verification);

    expect(withCoverage && presentationArtifactSupersedesText(withCoverage)).toBe(true);
    expect(parsedOverviewOnly && presentationArtifactSupersedesText(parsedOverviewOnly))
      .toBe(false);
  });

  it("accepts an accessible v2 time series and preserves its wire round trip", () => {
    const parsed = parsePresentationArtifact(timeSeriesArtifact(), verification);

    expect(parsed?.schemaVersion).toBe(2);
    expect(parsed?.blocks[0]?.kind).toBe("time_series");
    expect(parsed && presentationArtifactToWire(parsed)).toEqual(timeSeriesArtifact());
    expect(parsed && parsePersistedPresentationArtifact(parsed, verification)).toEqual(parsed);
  });

  it("rejects v2-only kinds under the v1 schema", () => {
    const raw = timeSeriesArtifact();
    raw.schema_version = 1;

    expect(parsePresentationArtifact(raw, verification)).toBeUndefined();
  });

  it("rejects unordered timestamps and unknown v2 data keys", () => {
    const unordered = timeSeriesArtifact();
    const unorderedData = ((unordered.blocks as Record<string, unknown>[])[0]!.data) as {
      points: { timestamp: string; value: number }[];
    };
    unorderedData.points[1]!.timestamp = "2026-08-18T23:59:00Z";
    expect(parsePresentationArtifact(unordered, verification)).toBeUndefined();

    const unknown = timeSeriesArtifact();
    const unknownData = ((unknown.blocks as Record<string, unknown>[])[0]!.data) as
      Record<string, unknown>;
    unknownData.color = "blue";
    expect(parsePresentationArtifact(unknown, verification)).toBeUndefined();
  });

  it("rejects a v2 chart without its exact-value fallback", () => {
    const raw = timeSeriesArtifact();
    const data = ((raw.blocks as Record<string, unknown>[])[0]!.data) as
      Record<string, unknown>;
    delete data.exact_table;

    expect(parsePresentationArtifact(raw, verification)).toBeUndefined();
  });

  it.each([
    ["distribution", "bar", "bar", {
      description: "Values", unit: "count", visualization: "bar",
      items: [{ label: "A", value: 1, tone: "neutral" }], exact_table: exactTable(),
    }],
    ["distribution", "bar", "bar_list", {
      description: "Values", unit: "count", visualization: "bar_list",
      items: [{ label: "A", value: 1, tone: "neutral" }], exact_table: exactTable(),
    }],
    ["distribution", "bar", "donut", {
      description: "Values", unit: "count", visualization: "donut",
      items: [{ label: "A", value: 1, tone: "neutral" }], exact_table: exactTable(),
    }],
    ["coverage", "coverage", "category_bar", {
      description: "Coverage", unit: "ratio", visualization: "category_bar",
      items: [{ label: "A", value: 1, total: 2, tone: "neutral" }], exact_table: exactTable(),
    }],
    ["trend", "time_series", "line", {
      description: "Trend", metric: "requests", unit: "count", visualization: "line",
      points: [
        { timestamp: "2026-08-19T00:00:00Z", value: 1 },
        { timestamp: "2026-08-19T00:01:00Z", value: 2 },
        { timestamp: "2026-08-19T00:02:00Z", value: 3 },
      ], exact_table: exactTable(),
    }],
    ["trend", "time_series", "area", {
      description: "Trend", metric: "requests", unit: "count", visualization: "area",
      points: [
        { timestamp: "2026-08-19T00:00:00Z", value: 1 },
        { timestamp: "2026-08-19T00:01:00Z", value: 2 },
        { timestamp: "2026-08-19T00:02:00Z", value: 3 },
      ], exact_table: exactTable(),
    }],
    ["comparison", "comparison", "comparison_bar", {
      description: "Comparison", metric: "requests", unit: "count",
      visualization: "comparison_bar", items: [
        { role: "baseline", label: "Before", value: 1 },
        { role: "current", label: "Now", value: 2 },
      ], exact_table: exactTable(),
    }],
    ["timeline", "timeline", "tracker", {
      description: "Events", visualization: "tracker", items: [
        { timestamp: "2026-08-19T00:00:00Z", label: "Started" },
        { timestamp: "2026-08-19T00:01:00Z", label: "Completed" },
      ], exact_table: exactTable(),
    }],
    ["correlation", "scatter", undefined, {
      description: "Correlation", x_label: "latency", y_label: "errors", points: [
        { label: "A", x: 1, y: 2 }, { label: "B", x: 2, y: 4 },
      ], exact_table: exactTable(),
    }],
    ["matrix", "heatmap", undefined, {
      description: "Matrix", row_label: "service", column_label: "region", cells: [
        { row: "API", column: "east", value: 1 },
        { row: "API", column: "west", value: 2 },
      ], exact_table: exactTable(),
    }],
  ])("accepts %s/%s with the %s visualization", (slot, kind, visualization, data) => {
    const raw = visualArtifact(slot, kind, data);
    const parsed = parsePresentationArtifact(raw, verification);

    expect(parsed?.blocks[0]?.kind).toBe(kind);
    if (visualization) expect(parsed?.blocks[0]?.data).toMatchObject({ visualization });
    expect(parsed && presentationArtifactToWire(parsed)).toEqual(raw);
  });

  it("rejects a chart hint outside the kind-specific visualization allowlist", () => {
    const raw = visualArtifact("trend", "time_series", {
      description: "Trend", metric: "requests", unit: "count", visualization: "donut",
      points: [
        { timestamp: "2026-08-19T00:00:00Z", value: 1 },
        { timestamp: "2026-08-19T00:01:00Z", value: 2 },
        { timestamp: "2026-08-19T00:02:00Z", value: 3 },
      ], exact_table: exactTable(),
    });

    expect(parsePresentationArtifact(raw, verification)).toBeUndefined();
  });
});
