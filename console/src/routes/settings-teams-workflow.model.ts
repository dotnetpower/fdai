export interface TeamsWorkflowTestResult {
  readonly requestId: string;
  readonly accepted: true;
  readonly providerStatus: number;
  readonly workflowRunId: string | null;
  readonly testedAt: string;
}

export function decodeTeamsWorkflowTestResult(value: unknown): TeamsWorkflowTestResult {
  const item = record(value, "Teams Workflow test result");
  if (item["accepted"] !== true) {
    throw new Error("Teams Workflow test result.accepted MUST be true");
  }
  const providerStatus = integer(item["provider_status"], "Teams Workflow test result.provider_status");
  if (providerStatus < 200 || providerStatus > 299) {
    throw new Error("Teams Workflow test result.provider_status MUST be a 2xx status");
  }
  const testedAt = nonEmptyString(item["tested_at"], "Teams Workflow test result.tested_at");
  if (Number.isNaN(Date.parse(testedAt))) {
    throw new Error("Teams Workflow test result.tested_at MUST be an ISO timestamp");
  }
  return {
    requestId: nonEmptyString(item["request_id"], "Teams Workflow test result.request_id"),
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
