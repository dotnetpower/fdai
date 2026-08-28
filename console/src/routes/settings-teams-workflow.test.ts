import { describe, expect, test, vi } from "vitest";
import {
  decodeTeamsWorkflowTestResult,
  newTeamsWorkflowTestRequestId,
} from "./settings-teams-workflow.model";

describe("Teams Workflow diagnostic model", () => {
  test("decodes only a secret-free accepted result", () => {
    expect(decodeTeamsWorkflowTestResult({
      request_id: "teams-workflow-test-1",
      accepted: true,
      provider_status: 202,
      workflow_run_id: "run-1",
      tested_at: "2026-08-27T12:00:00+00:00",
    })).toEqual({
      requestId: "teams-workflow-test-1",
      accepted: true,
      providerStatus: 202,
      workflowRunId: "run-1",
      testedAt: "2026-08-27T12:00:00+00:00",
    });
  });

  test.each([
    null,
    { accepted: false, provider_status: 202, request_id: "r", tested_at: "2026-08-27T12:00:00Z" },
    { accepted: true, provider_status: 500, request_id: "r", tested_at: "2026-08-27T12:00:00Z" },
    { accepted: true, provider_status: 202, request_id: "r", tested_at: "not-a-time" },
  ])("rejects malformed result %#", (value) => {
    expect(() => decodeTeamsWorkflowTestResult(value)).toThrow();
  });

  test("generates a fresh namespaced request id", () => {
    vi.spyOn(globalThis.crypto, "randomUUID").mockReturnValue(
      "00000000-0000-0000-0000-000000000000",
    );
    expect(newTeamsWorkflowTestRequestId()).toBe(
      "teams-workflow-test-00000000-0000-0000-0000-000000000000",
    );
  });
});
