import { describe, expect, test, vi } from "vitest";
import {
  decodeTeamsWorkflowBindingView,
  decodeTeamsWorkflowTestResult,
  newTeamsWorkflowTestRequestId,
} from "./settings-teams-workflow.model";

describe("Teams Workflow binding view", () => {
  test("keeps Reader state secret-free", () => {
    expect(decodeTeamsWorkflowBindingView({ visible: false })).toEqual({ visible: false });
  });

  test("decodes secret-free saved-binding metadata", () => {
    expect(decodeTeamsWorkflowBindingView({
      visible: true,
      configured: true,
      binding_version: "version-1",
      observed_at: "2026-09-01T04:00:00Z",
      saved_at: "2026-09-01T03:00:00Z",
    })).toEqual({
      visible: true,
      configured: true,
      bindingVersion: "version-1",
      observedAt: "2026-09-01T04:00:00Z",
      savedAt: "2026-09-01T03:00:00Z",
    });
  });

  test("treats a missing save record as unknown rather than fabricating a time", () => {
    expect(decodeTeamsWorkflowBindingView({
      visible: true,
      configured: true,
      binding_version: "version-1",
      observed_at: "2026-09-01T04:00:00Z",
    })).toEqual({
      visible: true,
      configured: true,
      bindingVersion: "version-1",
      observedAt: "2026-09-01T04:00:00Z",
      savedAt: null,
    });
  });

  test("refuses a response that returns the saved endpoint value", () => {
    expect(() => decodeTeamsWorkflowBindingView({
      visible: true,
      configured: true,
      binding_version: "version-1",
      observed_at: "2026-09-01T04:00:00Z",
      webhook_url: "https://example.environment.api.powerplatform.com/signed",
    })).toThrow("MUST NOT return the saved endpoint value");
  });

  test("reports an unconfigured binding without metadata", () => {
    expect(decodeTeamsWorkflowBindingView({ visible: true, configured: false })).toEqual({
      visible: true,
      configured: false,
    });
  });

  test.each([
    { visible: true, configured: true, binding_version: "", observed_at: "2026-09-01T04:00:00Z" },
    { visible: true, configured: true, binding_version: "v", observed_at: "not-a-time" },
    { visible: true, configured: true, binding_version: "v" },
  ])("rejects malformed binding metadata %#", (value) => {
    expect(() => decodeTeamsWorkflowBindingView(value)).toThrow();
  });
});

describe("Teams Workflow diagnostic model", () => {
  test("decodes only a secret-free accepted result", () => {
    expect(decodeTeamsWorkflowTestResult({
      request_id: "teams-workflow-test-1",
      saved: true,
      binding_version: "version-1",
      saved_at: "2026-08-27T11:59:59+00:00",
      accepted: true,
      provider_status: 202,
      workflow_run_id: "run-1",
      tested_at: "2026-08-27T12:00:00+00:00",
    })).toEqual({
      requestId: "teams-workflow-test-1",
      saved: true,
      bindingVersion: "version-1",
      savedAt: "2026-08-27T11:59:59+00:00",
      accepted: true,
      providerStatus: 202,
      workflowRunId: "run-1",
      testedAt: "2026-08-27T12:00:00+00:00",
    });
  });

  test.each([
    null,
    { accepted: false, provider_status: 202, request_id: "r", tested_at: "2026-08-27T12:00:00Z" },
    { saved: true, accepted: true, provider_status: 500, request_id: "r", tested_at: "2026-08-27T12:00:00Z" },
    { saved: true, accepted: true, provider_status: 202, request_id: "r", tested_at: "not-a-time" },
  ])("rejects malformed result %#", (value) => {
    expect(() => decodeTeamsWorkflowTestResult(value)).toThrow();
  });

  test("explains a stale Operator API response", () => {
    expect(() => decodeTeamsWorkflowTestResult({
      accepted: true,
      provider_status: 202,
      request_id: "r",
      tested_at: "2026-08-27T12:00:00Z",
    })).toThrow("Restart or upgrade the Operator API");
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
