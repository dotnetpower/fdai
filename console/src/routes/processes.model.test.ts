import { describe, expect, it } from "vitest";
import { ReadApiError } from "../api";
import {
  decodeProcessList,
  decodeRenderedProcessView,
  defaultProcessId,
  displayValue,
  processHref,
  processIdFromHash,
  processListFailure,
  processTone,
} from "./processes.model";

describe("process view route model", () => {
  it("round-trips a process id through the hash query", () => {
    const href = processHref("process:review-1");
    expect(processIdFromHash(href)).toBe("process:review-1");
    expect(processIdFromHash("#%2Fprocesses%3Fprocess%3Dprocess-1")).toBe("process-1");
  });

  it("returns null when no process query exists", () => {
    expect(processIdFromHash("#/processes")).toBeNull();
  });

  it("maps terminal and waiting states to stable tones", () => {
    expect(processTone("succeeded")).toBe("success");
    expect(processTone("waiting")).toBe("warning");
    expect(processTone("failed")).toBe("danger");
    expect(processTone("running")).toBe("info");
  });

  it("formats empty and structured values without throwing", () => {
    expect(displayValue(null)).toBe("-");
    expect(displayValue({ status: "ready" })).toBe('{"status":"ready"}');
  });

  it("classifies an unwired optional process API as unavailable", () => {
    expect(processListFailure(new ReadApiError(404, "Not Found"))).toEqual({
      status: "unavailable",
      message: "Process projections are not wired on this deployment.",
    });
    expect(processListFailure(new ReadApiError(501, "Not Implemented")).status).toBe("unavailable");
  });

  it("keeps operational process API failures visible as errors", () => {
    expect(processListFailure(new ReadApiError(503, "upstream unavailable"))).toEqual({
      status: "error",
      message: "upstream unavailable",
    });
  });

  it("preserves a current selection and defaults to the first renderable process", () => {
    const items = [summary("unsupported", false), summary("ready", true)];
    expect(defaultProcessId(items, "#/processes?process=chosen")).toBe("chosen");
    expect(defaultProcessId(items, "#/processes")).toBe("ready");
  });

  it("rejects malformed list and detail payloads at the boundary", () => {
    expect(() => decodeProcessList({})).toThrow(/items MUST be an array/);
    expect(() => decodeProcessList({ items: [{ id: "partial" }] })).toThrow(/workflow_ref/);
    expect(() => decodeRenderedProcessView({ process: {}, regions: null })).toThrow(/regions MUST be an array/);
  });

  it("decodes a minimal valid process view", () => {
    const decoded = decodeRenderedProcessView({
      id: "view-1", version: "1", name: "View", description: "Description", route: "/processes",
      process: {
        id: "process-1", workflow_ref: "review", workflow_version: "1", status: "waiting",
        current_step: "evidence", target_resource_id: "resource-1", updated_at: "2026-07-13T00:00:00Z",
        started_at: "2026-07-13T00:00:00Z", correlation_id: "correlation-1", revision: 2,
      },
      regions: [{
        id: "summary", column_span: 12,
        report: {
          id: "report-1", name: "Report", description: "Description", generated_at: "2026-07-13T00:00:00Z",
          widgets: [{ id: "status", type: "query_value", title: "Status", data: { value: "waiting" }, options: {} }],
        },
      }],
    });
    expect(decoded.process.revision).toBe(2);
    expect(decoded.regions[0]?.report.widgets[0]?.id).toBe("status");
  });
});

function summary(id: string, hasView: boolean) {
  return {
    id,
    workflow_ref: "review",
    workflow_version: "1",
    status: "waiting",
    current_step: "evidence",
    target_resource_id: "resource-1",
    updated_at: "2026-07-13T00:00:00Z",
    has_view: hasView,
  };
}