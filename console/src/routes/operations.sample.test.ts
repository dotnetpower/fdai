import { describe, expect, test } from "vitest";
import { decodeHilQueuePage, decodeIncidentPage } from "../api";
import { decodeAutomationBlueprints } from "./automation-blueprints";
import {
  decodeBackgroundTaskDetail,
  decodeBackgroundTaskPage,
  decodeBackgroundTaskProgress,
} from "./background-tasks.model";
import { decodeConfigurationBaselines } from "./configuration-baselines";
import { decodeConversationDelivery } from "./conversation-delivery";
import { decodeDetectionReadiness } from "./detection-readiness";
import { decodeOnboarding } from "./onboarding";
import {
  OPERATIONS_SAMPLE_CONTINUATIONS,
  OPERATIONS_SAMPLE_LIVE_EVENTS,
  OPERATIONS_SAMPLE_LIVE_EVENTS_PER_LOOP,
  OPERATIONS_SAMPLE_LIVE_HISTORY_COUNT,
  OPERATIONS_SAMPLE_LIVE_LOOP_INTERVAL_MS,
  OPERATIONS_SAMPLE_PROVISION_EVENTS,
  OPERATIONS_SAMPLE_LIVE_STAGE_INTERVAL_MS,
  OPERATIONS_SAMPLE_LIVE_VISIBLE_COUNT,
  sampleLiveEvents,
  operationsSampleResponse,
} from "./operations.sample";
import { decodeProcessJournal, decodeProcessList } from "./processes.model";
import { decodeSchedulerRunPage } from "./scheduler-runs.model";
import { decodeWorkflowApps } from "./workflow-apps.model";

function response(path: string, query = ""): unknown {
  const value = operationsSampleResponse(path, new URLSearchParams(query));
  expect(value).not.toBeUndefined();
  return value;
}

describe("Operations Sample registry", () => {
  test("provides valid list and evidence projections", () => {
    expect(decodeIncidentPage(response("/incidents")).items).toHaveLength(1);
    expect(decodeHilQueuePage(response("/hil-queue")).items).toHaveLength(1);
    expect(decodeOnboarding(response("/onboarding")).blocked).toBe(true);
    const detection = decodeDetectionReadiness(response("/detection-coverage"));
    expect(detection.targets).toHaveLength(1);
    expect(detection.analyzer_run).toMatchObject({
      targets: 5,
      candidate_count: 7,
      held_count: 2,
      source_complete: true,
    });
    expect(detection.analyzer_coverage).toMatchObject({
      status: "available",
      candidate_count: 7,
      evaluated_count: 4,
      held_count: 2,
      finding_count: 1,
    });
    expect(
      detection.analyzer_coverage.status === "available"
        ? detection.analyzer_coverage.resources
        : [],
    ).toHaveLength(5);
    expect(detection.lifecycle.targets).toHaveLength(2);
    expect(detection.pod_lifecycle.targets).toHaveLength(2);
    expect(decodeConfigurationBaselines(response("/configuration-baselines")).baseline.version)
      .toBe("sample-v3");
    expect(decodeProcessList(response("/views/process")).items).toHaveLength(1);
    expect(decodeProcessJournal(response("/views/process/sample-process-1/events")).events)
      .toHaveLength(1);
    expect(decodeWorkflowApps(response("/views/workflow-apps")).items).toHaveLength(1);
    expect(decodeSchedulerRunPage(
      response("/scheduler-runs", "task_id=inventory-reconciliation"),
    ).items).toHaveLength(2);
    expect(decodeBackgroundTaskPage(response("/background-tasks")).tasks).toHaveLength(1);
    expect(decodeBackgroundTaskDetail(response("/background-tasks/sample-task-1")).task_id)
      .toBe("sample-task-1");
    expect(decodeBackgroundTaskProgress(
      response("/background-tasks/sample-task-1/progress"),
    ).events).toHaveLength(2);
    expect(decodeAutomationBlueprints(response("/automation-blueprints")).count).toBe(1);
    expect(decodeConversationDelivery(response("/conversation-delivery")).delivery_count).toBe(48);
  });

  test("keeps direct-stream fixtures bounded and non-authoritative", () => {
    expect(OPERATIONS_SAMPLE_LIVE_EVENTS.length).toBeGreaterThan(720);
    const terminal = OPERATIONS_SAMPLE_LIVE_EVENTS.filter((event) => event.stage === "audit");
    expect(new Set(terminal.map((event) => event.event_id)).size)
      .toBe(OPERATIONS_SAMPLE_LIVE_HISTORY_COUNT);
    expect(terminal.filter((event) => event.detail?.["decision"] === "hil")).toHaveLength(3);
    expect(terminal.filter((event) => event.phase === "failed")).toHaveLength(4);
    expect(OPERATIONS_SAMPLE_LIVE_VISIBLE_COUNT).toBe(30);
    expect(OPERATIONS_SAMPLE_LIVE_LOOP_INTERVAL_MS).toBe(1_000);
    expect(OPERATIONS_SAMPLE_LIVE_EVENTS_PER_LOOP).toBe(3);
    expect(OPERATIONS_SAMPLE_LIVE_STAGE_INTERVAL_MS).toBe(800);
    const dynamic = sampleLiveEvents(OPERATIONS_SAMPLE_LIVE_HISTORY_COUNT, 1);
    expect(new Set(dynamic.map((event) => event.event_id)).size).toBe(1);
    expect(dynamic.map((event) => event.stage)).toEqual([
      "ingest",
      "route",
      "verify",
      "gate",
      "execute",
      "audit",
    ]);
    expect(dynamic.map((event) => event.detail?.["producer_principal"])).toEqual([
      "Huginn",
      "Odin",
      "Heimdall",
      "Forseti",
      "Thor",
      "Saga",
    ]);
    expect(dynamic.filter((event) => event.detail?.["decision"] === "hil")).toHaveLength(0);
    expect(dynamic.every((event) => event.detail?.["target"] === "sample-container-app-01"))
      .toBe(true);
    expect(dynamic.every((event) => event.detail?.["scope"] === "sample-service-ring"))
      .toBe(true);
    expect(dynamic.every((event) => event.detail?.["risk"] === "low")).toBe(true);
    expect(OPERATIONS_SAMPLE_LIVE_EVENTS.some((event) => event.phase === "failed")).toBe(true);
    expect(OPERATIONS_SAMPLE_LIVE_EVENTS.every(
      (event) => event.source === "synthetic-dev",
    )).toBe(true);
    expect(OPERATIONS_SAMPLE_PROVISION_EVENTS).toHaveLength(1);
    expect(OPERATIONS_SAMPLE_PROVISION_EVENTS[0]?.ready).toBe(false);
    expect(OPERATIONS_SAMPLE_CONTINUATIONS).toHaveLength(1);
  });

  test("returns no fallback for unregistered paths", () => {
    expect(operationsSampleResponse("/detection-readiness", new URLSearchParams()))
      .toEqual(operationsSampleResponse("/detection-coverage", new URLSearchParams()));
    expect(operationsSampleResponse("/unknown", new URLSearchParams())).toBeUndefined();
  });
});
