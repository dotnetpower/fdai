import type { Message } from "./workflow-builder.chatpanel";
import type { ChatSlots, ChatStage } from "./workflow-builder.chat";
import {
  APPROVAL_ROLES,
  AUTHORABLE_STEP_KINDS,
  type ApprovalRole,
  type DraftStep,
  type DraftStepKind,
  type FormState,
} from "./workflow-builder.model";

const STORAGE_KEY = "fdai.workflow-builder.chat.v1";
const MAX_STORED_CHARS = 256 * 1024;
const STAGES = new Set<ChatStage>([
  "welcome",
  "need_action",
  "need_trigger",
  "confirm_plan",
  "offer_extra",
  "confirm_safety",
  "confirm_name",
  "ready",
]);

export interface WorkflowChatSession {
  readonly messages: readonly Message[];
  readonly slots: ChatSlots;
}

export function loadWorkflowChatSession(storage: Storage | null): WorkflowChatSession | null {
  if (storage === null) return null;
  const raw = storage.getItem(STORAGE_KEY);
  if (raw === null || raw.length > MAX_STORED_CHARS) return null;
  try {
    return decodeSession(JSON.parse(raw));
  } catch {
    return null;
  }
}

export function saveWorkflowChatSession(
  storage: Storage | null,
  session: WorkflowChatSession,
): void {
  if (storage === null) return;
  const raw = JSON.stringify(session);
  if (raw.length > MAX_STORED_CHARS) {
    storage.removeItem(STORAGE_KEY);
    return;
  }
  storage.setItem(STORAGE_KEY, raw);
}

function decodeSession(value: unknown): WorkflowChatSession | null {
  if (!isRecord(value) || !Array.isArray(value["messages"]) || !isRecord(value["slots"])) {
    return null;
  }
  const slots = decodeSlots(value["slots"]);
  if (slots === null) return null;
  const messages = value["messages"].map(decodeMessage);
  if (messages.some((message) => message === null) || messages.length === 0) return null;
  return { messages: messages as Message[], slots };
}

function decodeSlots(value: Record<string, unknown>): ChatSlots | null {
  const stage = value["stage"];
  const form = decodeForm(value["form"]);
  const booleans = [
    "triggerConfirmed",
    "actionsConfirmed",
    "extraOffered",
    "nameConfirmed",
    "planConfirmed",
    "safetyConfirmed",
  ] as const;
  if (
    typeof stage !== "string"
    || !STAGES.has(stage as ChatStage)
    || form === null
    || booleans.some((key) => typeof value[key] !== "boolean")
    || typeof value["resourceHint"] !== "string"
    || typeof value["goalText"] !== "string"
    || !Array.isArray(value["warnings"])
    || value["warnings"].some((warning) => typeof warning !== "string")
  ) return null;
  return {
    stage: stage as ChatStage,
    form,
    triggerConfirmed: value["triggerConfirmed"] as boolean,
    actionsConfirmed: value["actionsConfirmed"] as boolean,
    extraOffered: value["extraOffered"] as boolean,
    nameConfirmed: value["nameConfirmed"] as boolean,
    planConfirmed: value["planConfirmed"] as boolean,
    safetyConfirmed: value["safetyConfirmed"] as boolean,
    resourceHint: value["resourceHint"],
    goalText: value["goalText"],
    warnings: value["warnings"] as string[],
  };
}

function decodeForm(value: unknown): FormState | null {
  if (!isRecord(value) || !Array.isArray(value["steps"])) return null;
  const stringKeys = [
    "name", "version", "description", "signalType", "schedule",
    "minShadowDays", "minSamples", "minAccuracy", "maxPolicyEscapes", "antiScope",
  ] as const;
  const triggerKind = value["triggerKind"];
  if (
    (triggerKind !== "signal" && triggerKind !== "schedule")
    || stringKeys.some((key) => typeof value[key] !== "string")
  ) return null;
  const steps = value["steps"].map(decodeStep);
  if (steps.some((step) => step === null)) return null;
  return {
    name: value["name"] as string,
    version: value["version"] as string,
    description: value["description"] as string,
    triggerKind,
    signalType: value["signalType"] as string,
    schedule: value["schedule"] as string,
    minShadowDays: value["minShadowDays"] as string,
    minSamples: value["minSamples"] as string,
    minAccuracy: value["minAccuracy"] as string,
    maxPolicyEscapes: value["maxPolicyEscapes"] as string,
    antiScope: value["antiScope"] as string,
    steps: steps as DraftStep[],
  };
}

function decodeStep(value: unknown): DraftStep | null {
  if (!isRecord(value) || !isRecord(value["params"])) return null;
  const strings = ["id", "action_type_ref", "guard_rule_ref", "compensated_by", "on_failure"] as const;
  const kind = value["kind"] ?? "action";
  const waitFor = value["wait_for"] ?? "";
  const timeoutSeconds = value["timeout_seconds"] ?? "";
  const approvalRole = value["approval_role"] ?? "";
  const quorum = value["quorum"] ?? "1";
  const noSelfApproval = value["no_self_approval"] ?? true;
  if (
    typeof value["key"] !== "number"
    || !Number.isSafeInteger(value["key"])
    || strings.some((key) => typeof value[key] !== "string")
    || typeof kind !== "string"
    || !AUTHORABLE_STEP_KINDS.includes(kind as DraftStepKind)
    || typeof waitFor !== "string"
    || typeof timeoutSeconds !== "string"
    || (
      approvalRole !== ""
      && (
        typeof approvalRole !== "string"
        || !APPROVAL_ROLES.includes(approvalRole as ApprovalRole)
      )
    )
    || typeof quorum !== "string"
    || typeof noSelfApproval !== "boolean"
    || Object.values(value["params"]).some((item) => !isPrimitive(item))
  ) return null;
  return {
    key: value["key"],
    id: value["id"] as string,
    kind: kind as DraftStepKind,
    action_type_ref: value["action_type_ref"] as string,
    guard_rule_ref: value["guard_rule_ref"] as string,
    compensated_by: value["compensated_by"] as string,
    on_failure: value["on_failure"] as string,
    params: value["params"] as Record<string, string | number | boolean>,
    wait_for: waitFor,
    timeout_seconds: timeoutSeconds,
    approval_role: approvalRole as ApprovalRole | "",
    quorum,
    no_self_approval: noSelfApproval,
  };
}

function decodeMessage(value: unknown): Message | null {
  if (
    !isRecord(value)
    || typeof value["id"] !== "number"
    || !Number.isSafeInteger(value["id"])
    || (value["role"] !== "bot" && value["role"] !== "operator")
    || typeof value["text"] !== "string"
  ) return null;
  const preview = value["preview"] === undefined ? undefined : decodeForm(value["preview"]);
  if (value["preview"] !== undefined && preview === null) return null;
  const options = value["options"];
  if (
    options !== undefined
    && (!Array.isArray(options) || options.some((option) => !isChatOption(option)))
  ) return null;
  return {
    id: value["id"],
    role: value["role"],
    text: value["text"],
    ...(options === undefined ? {} : { options }),
    ...(preview === undefined ? {} : { preview }),
  } as Message;
}

function isChatOption(value: unknown): boolean {
  return isRecord(value)
    && typeof value["label"] === "string"
    && typeof value["value"] === "string"
    && (value["hint"] === undefined || typeof value["hint"] === "string");
}

function isPrimitive(value: unknown): value is string | number | boolean {
  return typeof value === "string" || typeof value === "number" || typeof value === "boolean";
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}
