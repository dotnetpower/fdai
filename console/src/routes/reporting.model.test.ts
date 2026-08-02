import { describe, expect, test } from "vitest";
import { OperatorApiError } from "../api";
import {
  decodeRenderedReport,
  decodeReportingRegistry,
  decodeReportList,
} from "./reporting.model";

const summary = {
  id: "shadow-mode-daily",
  version: "1.0.0",
  name: "Shadow Mode Daily",
  description: "Daily evidence.",
  tags: ["shadow"],
  widget_count: 2,
  datasources: ["audit"],
  variables: [{ name: "env", default: "prod", values: ["prod"], description: "Environment" }],
};

describe("reporting wire decoders", () => {
  test("decodes catalog, registry, and rendered widgets", () => {
    expect(decodeReportList({ items: [summary], formats: ["json"] }).items[0]?.id)
      .toBe("shadow-mode-daily");
    expect(decodeReportingRegistry({
      datasources: ["audit"],
      datasource_provenance: [{
        datasource: "audit",
        source: "synthetic-dev",
        availability: "available",
        synthetic: true,
        as_of: "2026-07-15T00:00:00Z",
      }],
      widgets: ["query_value", "bar_chart"],
      formats: ["json"],
    }).widgets).toEqual(["query_value", "bar_chart"]);
    const rendered = decodeRenderedReport({
      ...summary,
      generated_at: "2026-07-15T00:00:00Z",
      time_range: { since: "2026-07-14T00:00:00Z" },
      variables: { env: "prod" },
      widgets: [
        { id: "total", type: "query_value", title: "Total", data: { value: 3 }, options: {} },
        { id: "mode", type: "bar_chart", title: "By mode", data: { bars: [] }, options: {} },
      ],
      provenance: {
        availability: "available",
        synthetic: true,
        sources: [{
          datasource: "audit",
          source: "synthetic-dev",
          availability: "available",
          synthetic: true,
          as_of: "2026-07-15T00:00:00Z",
        }],
      },
    });
    expect(rendered.widgets.map((widget) => widget.type)).toEqual(["query_value", "bar_chart"]);
    expect(rendered.provenance.synthetic).toBe(true);
  });

  test("rejects malformed report payloads at the API boundary", () => {
    expect(() => decodeReportList({ items: [{ ...summary, widget_count: -1 }], formats: [] }))
      .toThrow();
    expect(() => decodeRenderedReport({ ...summary, generated_at: null }))
      .toThrow();
    expect(() => decodeReportingRegistry({ widgets: [1], datasources: [], formats: [] }))
      .toThrow();
  });

  test("API decoder failures normalize to OperatorApiError when called by the client", () => {
    expect(new OperatorApiError(502, "invalid reporting response").status).toBe(502);
  });
});
