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

/**
 * Secret-free saved-binding metadata.
 *
 * The saved Teams Workflows URL is password-equivalent. The Operator API never
 * returns it, so the Console never receives, prefills, stores, or renders it.
 * An Owner replaces a saved binding by submitting a new URL.
 */
export type TeamsWorkflowBindingView =
  | { readonly visible: false }
  | { readonly visible: true; readonly configured: false }
  | {
      readonly visible: true;
      readonly configured: true;
      readonly bindingVersion: string;
      readonly observedAt: string;
      readonly savedAt: string | null;
    };

/** Secret-free saved-binding facts the setup panel renders. */
export interface TeamsWorkflowSavedBinding {
  readonly bindingVersion: string;
  readonly savedAt: string | null;
  readonly observedAt: string;
}

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
  if ("webhook_url" in item) {
    throw new Error("Teams Workflow binding MUST NOT return the saved endpoint value");
  }
  return {
    visible: true,
    configured: true,
    bindingVersion: nonEmptyString(
      item["binding_version"],
      "Teams Workflow binding.binding_version",
    ),
    observedAt: isoTimestamp(item["observed_at"], "Teams Workflow binding.observed_at"),
    savedAt:
      item["saved_at"] === undefined || item["saved_at"] === null
        ? null
        : isoTimestamp(item["saved_at"], "Teams Workflow binding.saved_at"),
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

function isoTimestamp(value: unknown, path: string): string {
  const text = nonEmptyString(value, path);
  if (Number.isNaN(Date.parse(text))) {
    throw new Error(`${path} MUST be an ISO timestamp`);
  }
  return text;
}

function integer(value: unknown, path: string): number {
  if (typeof value !== "number" || !Number.isInteger(value)) {
    throw new Error(`${path} MUST be an integer`);
  }
  return value;
}
