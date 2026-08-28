export interface SlackWebhookTestResult {
  readonly requestId: string;
  readonly accepted: true;
  readonly providerStatus: 200;
  readonly testedAt: string;
}

export function decodeSlackWebhookTestResult(value: unknown): SlackWebhookTestResult {
  const item = record(value, "Slack webhook test result");
  if (item["accepted"] !== true) {
    throw new Error("Slack webhook test result.accepted MUST be true");
  }
  if (item["provider_status"] !== 200) {
    throw new Error("Slack webhook test result.provider_status MUST be 200");
  }
  const testedAt = nonEmptyString(item["tested_at"], "Slack webhook test result.tested_at");
  if (Number.isNaN(Date.parse(testedAt))) {
    throw new Error("Slack webhook test result.tested_at MUST be an ISO timestamp");
  }
  return {
    requestId: nonEmptyString(item["request_id"], "Slack webhook test result.request_id"),
    accepted: true,
    providerStatus: 200,
    testedAt,
  };
}

export function newSlackWebhookTestRequestId(): string {
  return `slack-webhook-test-${globalThis.crypto.randomUUID()}`;
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
