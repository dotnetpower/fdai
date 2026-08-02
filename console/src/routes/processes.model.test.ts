import { describe, expect, it } from "vitest";
import { OperatorApiError } from "../api";
import {
  assertProcessDetailSelection,
  decodeProcessJournal,
  decodeProcessList,
  decodeRenderedProcessView,
  defaultProcessId,
  displayValue,
  INITIAL_PROCESS_REFRESH,
  processHref,
  processEventHref,
  processIdFromHash,
  processListFailure,
  processTone,
  reduceProcessRefresh,
} from "./processes.model";

describe("process view route model", () => {
  it("builds a clean process detail path and accepts legacy queries", () => {
    const href = processHref("process:review-1");
    expect(href).toBe("/processes/process%3Areview-1");
    expect(processHref("Run_A")).toBe("/processes/Run_A");
    expect(processEventHref("Run_A", "Event/1")).toBe(
      "/processes/Run_A?event=Event%2F1",
    );
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
    expect(processListFailure(new OperatorApiError(404, "Not Found"))).toEqual({
      status: "unavailable",
      message: "Process projections are not wired on this deployment.",
    });
    expect(processListFailure(new OperatorApiError(501, "Not Implemented")).status).toBe("unavailable");
  });

  it("keeps operational process API failures visible as errors", () => {
    expect(processListFailure(new OperatorApiError(503, "upstream unavailable"))).toEqual({
      status: "error",
      message: "upstream unavailable",
    });
  });

  it("preserves a current selection and defaults to the newest process", () => {
    const items = [summary("unsupported", false), summary("ready", true)];
    expect(defaultProcessId(items, "#/processes?process=chosen")).toBe("chosen");
    expect(defaultProcessId(items, "#/processes")).toBe("unsupported");
  });

  it("coalesces refresh starts until the matching generation finishes", () => {
    const started = reduceProcessRefresh(INITIAL_PROCESS_REFRESH, { type: "start" });
    expect(started).toEqual({ generation: 1, refreshing: true });
    expect(reduceProcessRefresh(started, { type: "start" })).toBe(started);
    expect(reduceProcessRefresh(started, { type: "finish", generation: 0 })).toBe(started);

    const finished = reduceProcessRefresh(started, { type: "finish", generation: 1 });
    expect(finished).toEqual({ generation: 1, refreshing: false });
    expect(reduceProcessRefresh(finished, { type: "start" })).toEqual({
      generation: 2,
      refreshing: true,
    });
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

  it("decodes a process snapshot and append-only journal", () => {
    const decoded = decodeProcessJournal({
      process: {
        ...summary("process-1", false),
        started_at: "2026-07-15T09:30:00Z",
        correlation_id: "correlation-1",
        revision: 3,
      },
      events: [{
        event_id: "event-1",
        kind: "step.completed",
        recorded_at: "2026-07-15T09:30:01Z",
        correlation_id: "correlation-1",
        causation_id: null,
        step_id: "inspect",
        attempt: 1,
        payload: { outcome: "success" },
      }],
      count: 1,
    });

    expect(decoded.process.has_view).toBe(false);
    expect(decoded.events[0]?.step_id).toBe("inspect");
    expect(decoded.events[0]?.payload["outcome"]).toBe("success");
    expect(() => assertProcessDetailSelection("process-1", decoded, null)).not.toThrow();
  });

  it("rejects duplicate process and journal identities", () => {
    const repeated = summary("process-1", false);
    expect(() => decodeProcessList({ items: [repeated, repeated] })).toThrow(/ids MUST be unique/);
    const journal = validJournal();
    expect(() => decodeProcessJournal({ ...journal, events: [journal.events[0], journal.events[0]], count: 2 }))
      .toThrow(/event ids MUST be unique/);
  });

  it("rejects contradictory journal counts, correlations, and numeric fields", () => {
    const journal = validJournal();
    expect(() => decodeProcessJournal({ ...journal, count: 2 })).toThrow(/count MUST equal/);
    expect(() => decodeProcessJournal({
      ...journal,
      events: [{ ...journal.events[0], correlation_id: "other" }],
    })).toThrow(/correlation_id/);
    expect(() => decodeProcessJournal({
      ...journal,
      process: { ...journal.process, revision: -1 },
    })).toThrow(/non-negative integer/);
    expect(() => decodeProcessJournal({
      ...journal,
      events: [{ ...journal.events[0], attempt: 0.5 }],
    })).toThrow(/non-negative integer/);
  });

  it("rejects evidence for a different selected process", () => {
    const journal = decodeProcessJournal(validJournal());
    expect(() => assertProcessDetailSelection("other", journal, null)).toThrow(/journal id/);
    const view = decodeRenderedProcessView(validView());
    expect(() => assertProcessDetailSelection("process-1", journal, view)).not.toThrow();
    expect(() => assertProcessDetailSelection("other", journal, view)).toThrow();
  });

  it("rejects duplicate or invalid ViewSpec layout identities", () => {
    const view = validView();
    expect(() => decodeRenderedProcessView({
      ...view,
      regions: [view.regions[0], view.regions[0]],
    })).toThrow(/region ids MUST be unique/);
    expect(() => decodeRenderedProcessView({
      ...view,
      regions: [{ ...view.regions[0], column_span: 13 }],
    })).toThrow(/between 1 and 12/);
  });
});

function validJournal() {
  return {
    process: {
      ...summary("process-1", false),
      started_at: "2026-07-15T09:30:00Z",
      correlation_id: "correlation-1",
      revision: 3,
    },
    events: [{
      event_id: "event-1",
      kind: "step.completed",
      recorded_at: "2026-07-15T09:30:01Z",
      correlation_id: "correlation-1",
      causation_id: null,
      step_id: "inspect",
      attempt: 1,
      payload: { outcome: "success" },
    }],
    count: 1,
  };
}

function validView() {
  return {
    id: "view-1", version: "1", name: "View", description: "Description", route: "/processes",
    process: {
      ...summary("process-1", true),
      started_at: "2026-07-13T00:00:00Z",
      correlation_id: "correlation-1",
      revision: 2,
    },
    regions: [{
      id: "summary", column_span: 12,
      report: {
        id: "report-1", name: "Report", description: "Description", generated_at: "2026-07-13T00:00:00Z",
        widgets: [{ id: "status", type: "query_value", title: "Status", data: { value: "waiting" }, options: {} }],
      },
    }],
  };
}

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
