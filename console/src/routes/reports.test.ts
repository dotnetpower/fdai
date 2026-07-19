import { afterEach, describe, expect, test, vi } from "vitest";

import {
  aggregateEvidenceAsOf,
  defaultReport,
  reportVariableErrors,
  reportDownloadCanComplete,
  reportHeadlineState,
  triggerBlobDownload,
  updateReportVariable,
} from "./reports";
import type { ReportSummary } from "./reporting.model";

function report(
  id: string,
  variables: ReportSummary["variables"],
): ReportSummary {
  return {
    id,
    version: "1.0.0",
    name: id,
    description: id,
    tags: [],
    widget_count: 1,
    datasources: [],
    variables,
  };
}

describe("defaultReport", () => {
  test("prefers a report with explicit complete defaults", () => {
    const required = report("required", [{
      name: "process_id",
      default: null,
      values: [],
      description: "process",
    }]);
    const ready = report("ready", []);
    const defaulted = report("defaulted", [{
      name: "group_by",
      default: "mode",
      values: [],
      description: "group",
    }]);

    expect(defaultReport([required, ready, defaulted])?.id).toBe("defaulted");
  });

  test("falls back to a variable-free report", () => {
    const required = report("required", [{
      name: "process_id",
      default: null,
      values: [],
      description: "process",
    }]);
    const ready = report("ready", []);

    expect(defaultReport([required, ready])?.id).toBe("ready");
    expect(defaultReport([])).toBeNull();
  });

  test("deprioritizes reports whose declared datasource is unavailable", () => {
    const noop = { ...report("metric", []), datasources: ["metric"] };
    const audit = { ...report("audit", []), datasources: ["audit"] };
    const registry = {
      datasources: ["metric", "audit"],
      widgets: [],
      formats: [],
      datasource_provenance: [
        { datasource: "metric", source: "noop", availability: "unavailable" as const, synthetic: null, as_of: null },
        { datasource: "audit", source: "audit", availability: "available" as const, synthetic: false, as_of: null },
      ],
    };

    expect(defaultReport([noop, audit], registry)?.id).toBe("audit");
  });
});

describe("report variable evidence", () => {
  test("distinguishes an unavailable render from a rendered zero-widget report", () => {
    const selected = report("empty-report", []);

    expect(reportHeadlineState(selected, null)).toEqual({
      kind: "unavailable",
      name: "empty-report",
    });
    expect(reportHeadlineState(selected, { widgets: [] })).toEqual({
      kind: "rendered",
      name: "empty-report",
      count: 0,
    });
  });

  test("suppresses downloads after unmount or a newer request", () => {
    expect(reportDownloadCanComplete(false, 2, 2)).toBe(false);
    expect(reportDownloadCanComplete(true, 3, 2)).toBe(false);
    expect(reportDownloadCanComplete(true, 2, 2)).toBe(true);
  });

  test("rejects an unsupported enum query before rendering", () => {
    const selected = report("metric", [{
      name: "env",
      default: "prod",
      values: ["prod", "dev"],
      description: "environment",
    }]);
    expect(reportVariableErrors(selected, { env: "bogus" })).toEqual([
      "env has an unsupported value: bogus",
    ]);
    expect(reportVariableErrors(selected, { env: "prod" })).toEqual([]);
  });

  test("uses the oldest known source and abstains when any source time is unknown", () => {
    expect(aggregateEvidenceAsOf([
      { as_of: "2026-07-17T10:00:00Z" },
      { as_of: "2026-07-17T09:00:00Z" },
    ])).toBe("2026-07-17T09:00:00Z");
    expect(aggregateEvidenceAsOf([
      { as_of: "2026-07-17T10:00:00+09:00" },
      { as_of: "2026-07-17T02:00:00Z" },
    ])).toBe("2026-07-17T10:00:00+09:00");
    expect(aggregateEvidenceAsOf([
      { as_of: "2026-07-17T10:00:00Z" },
      { as_of: null },
    ])).toBeNull();
    expect(aggregateEvidenceAsOf([{ as_of: "2026-07-17" }])).toBeNull();
    expect(aggregateEvidenceAsOf([{ as_of: "2026-13-45T25:00:00Z" }])).toBeNull();
  });

  test("invalidates rendered evidence when a variable changes", () => {
    const selected = report("metric", [{
      name: "env",
      default: "prod",
      values: ["prod", "dev"],
      description: "environment",
    }]);
    const data = {
      catalog: { items: [selected], formats: ["pdf"] },
      registry: { datasources: [], datasource_provenance: [], widgets: [], formats: [] },
      selected,
      rendered: { id: "metric" } as never,
      variables: { env: "prod" },
      operationError: "previous failure",
    };

    expect(updateReportVariable(data, "env", "dev")).toMatchObject({
      variables: { env: "dev" },
      rendered: null,
      operationError: null,
    });
  });
});

describe("triggerBlobDownload", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  test("clicks an attached anchor before revoking the blob URL", () => {
    const events: string[] = [];
    let connected = false;
    let deferred: (() => void) | undefined;
    const anchor = {
      href: "",
      download: "",
      click: () => events.push(`click:${connected}`),
      remove: () => {
        connected = false;
        events.push("remove");
      },
    };
    vi.stubGlobal("URL", {
      createObjectURL: () => {
        events.push("create");
        return "blob:report";
      },
      revokeObjectURL: (url: string) => events.push(`revoke:${url}`),
    });
    vi.stubGlobal("document", {
      createElement: () => anchor,
      body: {
        append: () => {
          connected = true;
          events.push("append");
        },
      },
    });
    vi.stubGlobal("window", {
      setTimeout: (callback: () => void) => {
        deferred = callback;
        return 1;
      },
    });

    triggerBlobDownload(new Blob(["report"]), "report.pdf");

    expect(anchor.href).toBe("blob:report");
    expect(anchor.download).toBe("report.pdf");
    expect(events).toEqual(["create", "append", "click:true", "remove"]);
    deferred?.();
    expect(events).toEqual([
      "create",
      "append",
      "click:true",
      "remove",
      "revoke:blob:report",
    ]);
  });
});
