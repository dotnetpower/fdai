import { useEffect, useState } from "preact/hooks";

import {
  isOptionalOperatorApiUnavailable,
  type OperatorApiClient,
} from "../api";
import type { ConsoleDataMode } from "../console-data-mode";
import type { AsyncState } from "../components/ui";
import type { RenderedReportView } from "./reporting.model";

export const CHAOS_RESULTS_REPORT_ID = "chaos-enforce-results";

export interface ChaosResultSummary {
  readonly experiments: number;
  readonly validated: number;
  readonly detectionGaps: number;
  readonly rollbackFailures: number;
  readonly detected: number;
  readonly reverted: number;
  readonly source: string;
  readonly asOf: string | null;
}

type ChaosResultSummaryClient = Pick<OperatorApiClient, "renderReport">;

export function useChaosResultSummary(
  client: ChaosResultSummaryClient,
  dataMode: ConsoleDataMode,
  unavailableMessage: string,
  windowDays = 30,
): AsyncState<ChaosResultSummary> {
  const [state, setState] = useState<AsyncState<ChaosResultSummary>>(
    dataMode === "sample"
      ? { status: "unavailable", message: unavailableMessage }
      : { status: "loading" },
  );

  useEffect(() => {
    let active = true;
    // Sample mode must not mix synthetic presentation with measured report evidence.
    if (dataMode === "sample") {
      setState({ status: "unavailable", message: unavailableMessage });
      return () => { active = false; };
    }
    setState({ status: "loading" });
    void loadChaosResultSummary(client, windowDays, unavailableMessage).then((nextState) => {
      if (active) setState(nextState);
    });
    return () => { active = false; };
  }, [client, dataMode, unavailableMessage, windowDays]);

  return state;
}

export async function loadChaosResultSummary(
  client: ChaosResultSummaryClient,
  windowDays = 30,
  unavailableMessage = "Measured chaos result evidence is unavailable.",
): Promise<AsyncState<ChaosResultSummary>> {
  try {
    const report = await client.renderReport(
      CHAOS_RESULTS_REPORT_ID,
      { window_days: String(windowDays) },
    );
    return { status: "ready", data: decodeChaosResultSummary(report) };
  } catch (error) {
    return isOptionalOperatorApiUnavailable(error)
      ? { status: "unavailable", message: unavailableMessage }
      : { status: "error", message: error instanceof Error ? error.message : String(error) };
  }
}

export function decodeChaosResultSummary(report: RenderedReportView): ChaosResultSummary {
  if (
    report.id !== CHAOS_RESULTS_REPORT_ID
    || report.provenance.synthetic !== false
    || report.provenance.availability !== "available"
  ) {
    throw new Error("invalid chaos result report provenance");
  }
  const source = report.provenance.sources.find(
    (candidate) => candidate.datasource === "chaos_results",
  );
  if (
    source === undefined
    || source.synthetic !== false
    || source.availability !== "available"
  ) {
    throw new Error("invalid chaos result report source");
  }

  const experiments = queryValue(report, "experiments");
  const validated = queryValue(report, "validated");
  const detectionGaps = queryValue(report, "detection-gaps");
  const rollbackFailures = queryValue(report, "rollback-failures");
  const table = report.widgets.find((widget) => widget.id === "experiment-results");
  if (table?.type !== "table" || !Array.isArray(table.data["rows"])) {
    throw new Error("invalid chaos result table");
  }
  const rows = table.data["rows"].map((value, index) => record(value, `row ${index}`));
  if (
    nonNegativeInteger(table.data["total_rows"], "total_rows") !== rows.length
    || experiments !== rows.length
    || validated !== rows.filter((row) => row["outcome"] === "validated").length
    || detectionGaps !== rows.filter((row) => row["outcome"] === "not_detected").length
    || rollbackFailures !== rows.filter((row) => row["outcome"] === "rollback_failed").length
  ) {
    throw new Error("chaos result totals do not reconcile");
  }
  const detected = rows.filter((row) => boolean(row["detected"], "detected")).length;
  const reverted = rows.filter((row) => boolean(row["reverted"], "reverted")).length;
  return {
    experiments,
    validated,
    detectionGaps,
    rollbackFailures,
    detected,
    reverted,
    source: source.source,
    asOf: source.as_of,
  };
}

function queryValue(report: RenderedReportView, widgetId: string): number {
  const widget = report.widgets.find((candidate) => candidate.id === widgetId);
  if (widget?.type !== "query_value") {
    throw new Error(`missing chaos result widget: ${widgetId}`);
  }
  return nonNegativeInteger(widget.data["value"], widgetId);
}

function record(value: unknown, label: string): Readonly<Record<string, unknown>> {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`invalid chaos result ${label}`);
  }
  return value as Readonly<Record<string, unknown>>;
}

function nonNegativeInteger(value: unknown, label: string): number {
  if (typeof value !== "number" || !Number.isInteger(value) || value < 0) {
    throw new Error(`invalid chaos result ${label}`);
  }
  return value;
}

function boolean(value: unknown, label: string): boolean {
  if (typeof value !== "boolean") throw new Error(`invalid chaos result ${label}`);
  return value;
}
