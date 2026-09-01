export interface TeamsWorkflowTestResult {
  readonly requestId: string;
  readonly saved: true;
  readonly bindingVersion: string;
  readonly savedAt: string;
  readonly accepted: true;
  readonly providerStatus: number;
  readonly workflowRunId: string | null;
  readonly testedAt: string;
}

export type TeamsWorkflowBindingView =
  | { readonly visible: false }
  | { readonly visible: true; readonly configured: false }
  | {
      readonly visible: true;
      readonly configured: true;
      readonly webhookUrl: string;
      readonly bindingVersion: string;
      readonly revealedAt: string;
    };

export function decodeTeamsWorkflowBindingView(value: unknown): TeamsWorkflowBindingView {
  const item = record(value, "Teams Workflow binding");
  if (item["visible"] === false) return { visible: false };
  if (item["visible"] !== true) {
    throw new Error("Teams Workflow binding.visible MUST be a boolean");
  }
  if (item["configured"] === false) return { visible: true, configured: false };
  if (item["configured"] !== true) {
    throw new Error("Teams Workflow binding.configured MUST be a boolean");
  }
  const revealedAt = nonEmptyString(
    item["revealed_at"],
    "Teams Workflow binding.revealed_at",
  );
  if (Number.isNaN(Date.parse(revealedAt))) {
    throw new Error("Teams Workflow binding.revealed_at MUST be an ISO timestamp");
  }
  return {
    visible: true,
    configured: true,
    webhookUrl: nonEmptyString(item["webhook_url"], "Teams Workflow binding.webhook_url"),
    bindingVersion: nonEmptyString(
      item["binding_version"],
      "Teams Workflow binding.binding_version",
    ),
    revealedAt,
  };
}

export function decodeTeamsWorkflowTestResult(value: unknown): TeamsWorkflowTestResult {
  const item = record(value, "Teams Workflow test result");
  if (item["accepted"] !== true) {
    throw new Error("Teams Workflow test result.accepted MUST be true");
  }
  if (item["saved"] !== true) {
    throw new Error(
      "Teams Workflow save was not confirmed. Restart or upgrade the Operator API before retrying.",
    );
  }
  const providerStatus = integer(item["provider_status"], "Teams Workflow test result.provider_status");
  if (providerStatus < 200 || providerStatus > 299) {
    throw new Error("Teams Workflow test result.provider_status MUST be a 2xx status");
  }
  const testedAt = nonEmptyString(item["tested_at"], "Teams Workflow test result.tested_at");
  if (Number.isNaN(Date.parse(testedAt))) {
    throw new Error("Teams Workflow test result.tested_at MUST be an ISO timestamp");
  }
  const savedAt = nonEmptyString(item["saved_at"], "Teams Workflow test result.saved_at");
  if (Number.isNaN(Date.parse(savedAt))) {
    throw new Error("Teams Workflow test result.saved_at MUST be an ISO timestamp");
  }
  return {
    requestId: nonEmptyString(item["request_id"], "Teams Workflow test result.request_id"),
    saved: true,
    bindingVersion: nonEmptyString(
      item["binding_version"],
      "Teams Workflow test result.binding_version",
    ),
    savedAt,
    accepted: true,
    providerStatus,
    workflowRunId: nullableString(
      item["workflow_run_id"],
      "Teams Workflow test result.workflow_run_id",
    ),
    testedAt,
  };
}

export function newTeamsWorkflowTestRequestId(): string {
  return `teams-workflow-test-${globalThis.crypto.randomUUID()}`;
}

function record(value: unknown, path: string): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error(`${path} MUST be an object`);
  }
  return value as Record<string, unknown>;
}

function nonEmptyString(value: unknown, path: string): string {
  if (typeof value !== "string" || !value.trim()) {
    throw new Error(`${path} MUST be a non-empty string`);
  }
  return value;
}

function nullableString(value: unknown, path: string): string | null {
  if (value === null) return null;
  return nonEmptyString(value, path);
}

function integer(value: unknown, path: string): number {
  if (typeof value !== "number" || !Number.isInteger(value)) {
    throw new Error(`${path} MUST be an integer`);
  }
  return value;
}
