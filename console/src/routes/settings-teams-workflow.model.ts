export interface TeamsWorkflowTestResult {
  readonly requestId: string;
  readonly saved: true;
  readonly bindingVersion: string;
  readonly savedAt: string;
  readonly accepted: boolean;
  readonly providerStatus: number;
  readonly workflowRunId: string | null;
  readonly testedAt: string;
}

export type TeamsNotificationDeliveryTargetKey =
  | "teams-a2-operational-alert"
  | "teams-a4-digest"
  | "slack-webhook"
  | "email"
  | "console-inbox";

export const ALL_TEAMS_NOTIFICATION_DELIVERY_TARGETS: readonly TeamsNotificationDeliveryTargetKey[] = [
  "teams-a2-operational-alert",
  "teams-a4-digest",
  "slack-webhook",
  "email",
  "console-inbox",
];

export const DEFAULT_TEAMS_NOTIFICATION_DELIVERY_TARGETS: readonly TeamsNotificationDeliveryTargetKey[] = [
  "teams-a2-operational-alert",
  "teams-a4-digest",
  "console-inbox",
];

const DELIVERY_TARGET_SET: ReadonlySet<string> = new Set(
  ALL_TEAMS_NOTIFICATION_DELIVERY_TARGETS,
);

export type TeamsEmailRecipientMode = "login" | "custom";

export interface TeamsWorkflowSavedChannel {
  readonly channelId: string;
  readonly label: string;
  readonly bindingVersion: string;
  readonly endpointIdentifier: string;
  readonly enabled: boolean;
  readonly savedAt: string | null;
}

/**
 * Secret-free saved-binding metadata.
 *
 * The default binding read omits the raw endpoint URL; authorized readers can
 * reveal or copy it through an audited read.
 */
export type TeamsWorkflowBindingView =
  | { readonly visible: false }
  | { readonly visible: true; readonly configured: false }
  | {
      readonly visible: true;
      readonly configured: true;
      readonly bindingVersion: string;
      readonly endpointIdentifier: string;
      readonly observedAt: string;
      readonly savedAt: string | null;
      readonly channels?: readonly TeamsWorkflowSavedChannel[];
      readonly deliveryTargets?: readonly TeamsNotificationDeliveryTargetKey[];
      readonly emailRecipientMode?: TeamsEmailRecipientMode;
      readonly customEmail?: string;
    };

/** Secret-free saved-binding facts the setup panel renders. */
export interface TeamsWorkflowSavedBinding {
  readonly bindingVersion: string;
  readonly endpointIdentifier: string;
  readonly savedAt: string | null;
  readonly observedAt: string;
  readonly channels: readonly TeamsWorkflowSavedChannel[];
  readonly deliveryTargets: readonly TeamsNotificationDeliveryTargetKey[];
  readonly emailRecipientMode: TeamsEmailRecipientMode;
  readonly customEmail: string;
}

/** Audited on-demand reveal payload for Contributor, Approver, and Owner roles. */
export interface TeamsWorkflowRevealedBinding {
  readonly bindingVersion: string;
  readonly endpointIdentifier: string;
  readonly webhookUrl: string;
  readonly revealedAt: string;
  readonly channelId?: string;
}

export interface TeamsWorkflowSubmitOptions {
  readonly channelLabel?: string;
  readonly selectedChannelIds?: readonly string[];
  readonly deliveryTargets?: readonly TeamsNotificationDeliveryTargetKey[];
  readonly removeChannelId?: string;
  readonly emailRecipientMode?: TeamsEmailRecipientMode;
  readonly customEmail?: string;
  readonly selectionOnly?: boolean;
}

export function maskSavedTeamsWorkflowUrl(endpointIdentifier: string): string {
  const match = /workflow\s+(\.\.\.[A-Za-z0-9]+)/.exec(endpointIdentifier);
  const workflowSuffix = match?.[1] ?? "...••••••••";
  return `https://••••••••/workflows/${workflowSuffix}/triggers/manual/paths/invoke?sig=••••••••••••`;
}

export function canSubmitTeamsWorkflow(
  webhookUrl: string,
  hasSavedBinding: boolean,
): boolean {
  return Boolean(webhookUrl.trim()) || hasSavedBinding;
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
  const bindingVersion = nonEmptyString(
    item["binding_version"],
    "Teams Workflow binding.binding_version",
  );
  const endpointIdentifier = nonEmptyString(
    item["endpoint_identifier"],
    "Teams Workflow binding.endpoint_identifier",
  );
  const observedAt = isoTimestamp(item["observed_at"], "Teams Workflow binding.observed_at");
  const savedAt =
    item["saved_at"] === undefined || item["saved_at"] === null
      ? null
      : isoTimestamp(item["saved_at"], "Teams Workflow binding.saved_at");
  const channels = decodeOptionalChannels(item["channels"]);
  const deliveryTargets = decodeOptionalDeliveryTargets(item["delivery_targets"]);
  const emailRecipientMode =
    item["email_recipient_mode"] === "login" || item["email_recipient_mode"] === "custom"
      ? item["email_recipient_mode"]
      : undefined;
  const customEmail =
    typeof item["custom_email"] === "string" ? item["custom_email"].trim() : undefined;
  return {
    visible: true,
    configured: true,
    bindingVersion,
    endpointIdentifier,
    observedAt,
    savedAt,
    ...(channels !== undefined ? { channels } : {}),
    ...(deliveryTargets !== undefined ? { deliveryTargets } : {}),
    ...(emailRecipientMode !== undefined ? { emailRecipientMode } : {}),
    ...(customEmail !== undefined ? { customEmail } : {}),
  };
}

export function resolveTeamsWorkflowChannels(
  binding: Extract<TeamsWorkflowBindingView, { readonly visible: true; readonly configured: true }>,
): readonly TeamsWorkflowSavedChannel[] {
  if (binding.channels && binding.channels.length > 0) {
    return binding.channels;
  }
  return [
    {
      channelId: "ch-primary",
      label: `Teams channel (${binding.endpointIdentifier.split(" / ")[0] ?? "primary"})`,
      bindingVersion: binding.bindingVersion,
      endpointIdentifier: binding.endpointIdentifier,
      enabled: true,
      savedAt: binding.savedAt,
    },
  ];
}

export function resolveTeamsDeliveryTargets(
  binding: Extract<TeamsWorkflowBindingView, { readonly visible: true; readonly configured: true }>,
): readonly TeamsNotificationDeliveryTargetKey[] {
  if (binding.deliveryTargets && binding.deliveryTargets.length > 0) {
    return binding.deliveryTargets;
  }
  return DEFAULT_TEAMS_NOTIFICATION_DELIVERY_TARGETS;
}

export function decodeTeamsWorkflowBindingReveal(
  value: unknown,
): TeamsWorkflowRevealedBinding {
  const item = record(value, "Teams Workflow binding reveal");
  if (item["visible"] !== true || item["configured"] !== true) {
    throw new Error("Teams Workflow binding reveal MUST report an active visible binding");
  }
  const webhookUrl = nonEmptyString(
    item["webhook_url"],
    "Teams Workflow binding reveal.webhook_url",
  );
  if (!webhookUrl.startsWith("https://")) {
    throw new Error("Teams Workflow binding reveal.webhook_url MUST be an HTTPS URL");
  }
  const channelId =
    typeof item["channel_id"] === "string" && item["channel_id"].trim()
      ? item["channel_id"].trim()
      : undefined;
  return {
    bindingVersion: nonEmptyString(
      item["binding_version"],
      "Teams Workflow binding reveal.binding_version",
    ),
    endpointIdentifier: nonEmptyString(
      item["endpoint_identifier"],
      "Teams Workflow binding reveal.endpoint_identifier",
    ),
    webhookUrl,
    revealedAt: isoTimestamp(
      item["revealed_at"],
      "Teams Workflow binding reveal.revealed_at",
    ),
    ...(channelId !== undefined ? { channelId } : {}),
  };
}

export function decodeTeamsWorkflowTestResult(value: unknown): TeamsWorkflowTestResult {
  const item = record(value, "Teams Workflow test result");
  const accepted = boolean(
    item["accepted"],
    "Teams Workflow test result.accepted",
  );
  if (item["saved"] !== true) {
    throw new Error(
      "Teams Workflow save was not confirmed. Restart or upgrade the Operator API before retrying.",
    );
  }
  const providerStatus = integer(item["provider_status"], "Teams Workflow test result.provider_status");
  if (accepted && (providerStatus < 200 || providerStatus > 299)) {
    throw new Error("Teams Workflow test result.provider_status MUST be a 2xx status");
  }
  if (!accepted && (providerStatus < 0 || providerStatus > 599)) {
    throw new Error("Teams Workflow test result.provider_status MUST be a bounded HTTP status");
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
    accepted,
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

function decodeOptionalChannels(
  value: unknown,
): readonly TeamsWorkflowSavedChannel[] | undefined {
  if (value === undefined) return undefined;
  if (!Array.isArray(value)) {
    throw new Error("Teams Workflow binding.channels MUST be an array");
  }
  return value.map((raw, index) => {
    const entry = record(raw, `Teams Workflow binding.channels[${index}]`);
    return {
      channelId: nonEmptyString(
        entry["channel_id"],
        `Teams Workflow binding.channels[${index}].channel_id`,
      ),
      label: nonEmptyString(
        entry["label"],
        `Teams Workflow binding.channels[${index}].label`,
      ),
      bindingVersion: nonEmptyString(
        entry["binding_version"],
        `Teams Workflow binding.channels[${index}].binding_version`,
      ),
      endpointIdentifier: nonEmptyString(
        entry["endpoint_identifier"],
        `Teams Workflow binding.channels[${index}].endpoint_identifier`,
      ),
      enabled: boolean(
        entry["enabled"],
        `Teams Workflow binding.channels[${index}].enabled`,
      ),
      savedAt:
        entry["saved_at"] === undefined || entry["saved_at"] === null
          ? null
          : isoTimestamp(
              entry["saved_at"],
              `Teams Workflow binding.channels[${index}].saved_at`,
            ),
    };
  });
}

function decodeOptionalDeliveryTargets(
  value: unknown,
): readonly TeamsNotificationDeliveryTargetKey[] | undefined {
  if (value === undefined) return undefined;
  if (!Array.isArray(value)) {
    throw new Error("Teams Workflow binding.delivery_targets MUST be an array");
  }
  const targets: TeamsNotificationDeliveryTargetKey[] = [];
  for (const item of value) {
    if (typeof item === "string" && DELIVERY_TARGET_SET.has(item)) {
      targets.push(item as TeamsNotificationDeliveryTargetKey);
    }
  }
  return targets;
}

function integer(value: unknown, path: string): number {
  if (typeof value !== "number" || !Number.isInteger(value)) {
    throw new Error(`${path} MUST be an integer`);
  }
  return value;
}

function boolean(value: unknown, path: string): boolean {
  if (typeof value !== "boolean") {
    throw new Error(`${path} MUST be a boolean`);
  }
  return value;
}
