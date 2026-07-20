import type { AuthContext } from "./auth";
import { loadConfig } from "./config";

export interface UserPreferencePayload {
  readonly principal_id: string;
  readonly locale: "en" | "ko";
  readonly verbosity: "concise" | "detailed";
  readonly answer_detail: "brief" | "standard" | "deep";
  readonly answer_format: "prose" | "bullets" | "numbered_steps" | "table" | "checklist" | "mixed";
  readonly answer_preferences_enabled: boolean;
  readonly answer_intent_detail: Readonly<Record<string, "brief" | "standard" | "deep">>;
  readonly answer_intent_format: Readonly<Record<string, "prose" | "bullets" | "numbered_steps" | "table" | "checklist" | "mixed">>;
  readonly timezone: string | null;
  readonly share_with_learner: boolean;
  readonly revision: number;
}

export interface BriefingRunPayload {
  readonly run_id: string;
  readonly title: string;
  readonly body_markdown: string;
  readonly status: string;
  readonly item_count: number;
  readonly evidence_refs: readonly string[];
  readonly source_errors: readonly string[];
}

export interface BriefingSubscriptionPayload {
  readonly subscription_id: string;
  readonly name: string;
  readonly cron_expression: string;
  readonly timezone: string;
  readonly enabled: boolean;
  readonly next_run_at: string;
  readonly spec: Readonly<Record<string, unknown>>;
  readonly revision: number;
}

export interface ScheduledContinuationPayload {
  readonly anchor_id: string;
  readonly task_id: string;
  readonly run_id: string;
  readonly owner_principal_id: string;
  readonly scope_ref: string;
  readonly mode: "origin_thread" | "dedicated_thread";
  readonly origin: {
    readonly channel_kind: string;
    readonly channel_ref: string;
    readonly conversation_ref: string;
    readonly thread_ref: string | null;
    readonly audience: "direct";
  };
  readonly result_digest: string;
  readonly result_summary: string;
  readonly evidence_refs: readonly string[];
  readonly observation_started_at: string;
  readonly observation_ended_at: string;
  readonly created_at: string;
  readonly expires_at: string;
  readonly state: "active" | "expired";
}

export interface ConversationPolicyPayload {
  readonly policy_id: string;
  readonly kind: "opening_briefing" | "response_defaults";
  readonly enabled: boolean;
  readonly revision: number;
  readonly source_turn_id: string;
  readonly briefing_spec: Readonly<Record<string, unknown>> | null;
  readonly response_defaults: Readonly<Record<string, string>>;
}

export interface UserMemoryPayload {
  readonly memory_id: string;
  readonly category: "preference" | "context" | "goal";
  readonly body: string;
  readonly source_turn_id: string;
  readonly created_at: string;
  readonly expires_at: string | null;
}

export interface ConversationSummaryPayload {
  readonly conversation_id: string;
  readonly channel_id: string;
  readonly started_at: string;
  readonly last_active: string;
  readonly status: string;
  readonly latest_operator_turn_id: string | null;
}

export interface ConversationTurnPayload {
  readonly turn_id: string;
  readonly conversation_id: string;
  readonly turn_index: number;
  readonly role: "operator" | "assistant" | "tool" | "system";
  readonly content: string;
  readonly recorded_at: string;
  readonly metadata: Readonly<Record<string, string>>;
}

export interface ConversationTextRangePayload {
  readonly start: number;
  readonly end: number;
}

export interface ConversationSearchHitPayload {
  readonly result_id: string;
  readonly turn_id: string;
  readonly conversation_id: string;
  readonly channel_id: string;
  readonly role: ConversationTurnPayload["role"];
  readonly snippet: {
    readonly text: string;
    readonly highlights: readonly ConversationTextRangePayload[];
  };
  readonly recorded_at: string;
  readonly rank: number;
  readonly incident_id: string | null;
  readonly correlation_id: string | null;
  readonly evidence_refs: readonly string[];
}

export interface ConversationSearchPayload {
  readonly hits: readonly ConversationSearchHitPayload[];
  readonly result_cap: number;
  readonly index_rows: number;
  readonly index_bytes: number;
}

export interface ConversationSearchContextPayload {
  readonly hit: ConversationSearchHitPayload;
  readonly before: readonly ConversationSearchHitPayload[];
  readonly after: readonly ConversationSearchHitPayload[];
}

export interface UserContextPayload {
  readonly preference: UserPreferencePayload | null;
  readonly memories: readonly UserMemoryPayload[];
  readonly policies: readonly ConversationPolicyPayload[];
  readonly subscriptions: readonly BriefingSubscriptionPayload[];
  readonly briefing_runs: readonly BriefingRunPayload[];
  readonly scheduled_continuations: readonly ScheduledContinuationPayload[];
  readonly conversations: readonly ConversationSummaryPayload[];
}

export class UserContextRequestError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
    this.name = "UserContextRequestError";
  }
}

let authContext: AuthContext | null = null;

export function setUserContextAuth(auth: AuthContext | null): void {
  authContext = auth;
}

export async function fetchUserContext(): Promise<UserContextPayload> {
  return decodeUserContext(await request("/me/context", "GET"));
}

export async function fetchOpeningBriefing(conversationId: string): Promise<BriefingRunPayload | null> {
  const response = await request("/me/opening-briefing", "POST", {
    conversation_id: conversationId,
  });
  return (response.briefing as BriefingRunPayload | null | undefined) ?? null;
}

export async function fetchConversationTurns(
  conversationId: string,
): Promise<readonly ConversationTurnPayload[]> {
  const response = await request(
    `/me/conversations/${encodeURIComponent(conversationId)}/turns?limit=1000`,
    "GET",
  );
  return (response.turns as readonly ConversationTurnPayload[] | undefined) ?? [];
}

export async function searchConversations(input: {
  readonly query: string;
  readonly mode?: "terms" | "phrase" | "prefix";
  readonly limit?: number;
  readonly channel?: string;
  readonly role?: ConversationTurnPayload["role"];
  readonly conversationId?: string;
  readonly incidentId?: string;
  readonly recordedAfter?: string;
  readonly recordedBefore?: string;
}): Promise<ConversationSearchPayload> {
  const params = new URLSearchParams({
    q: input.query,
    mode: input.mode ?? "terms",
    limit: String(input.limit ?? 20),
  });
  if (input.channel) params.append("channel", input.channel);
  if (input.role) params.append("role", input.role);
  if (input.conversationId) params.set("conversation_id", input.conversationId);
  if (input.incidentId) params.set("incident_id", input.incidentId);
  if (input.recordedAfter) params.set("after", input.recordedAfter);
  if (input.recordedBefore) params.set("before", input.recordedBefore);
  return decodeConversationSearch(
    await request(`/me/conversations/search?${params.toString()}`, "GET"),
  );
}

export async function fetchConversationSearchContext(
  resultId: string,
  before = 1,
  after = 1,
): Promise<ConversationSearchContextPayload> {
  return decodeConversationSearchContext(
    await request(
      `/me/conversations/search/${encodeURIComponent(resultId)}/context?before=${before}&after=${after}`,
      "GET",
    ),
  );
}

export async function putUserPreference(input: {
  readonly locale: "en" | "ko";
  readonly verbosity: "concise" | "detailed";
  readonly answer_detail: UserPreferencePayload["answer_detail"];
  readonly answer_format: UserPreferencePayload["answer_format"];
  readonly answer_preferences_enabled: boolean;
  readonly answer_intent_detail: UserPreferencePayload["answer_intent_detail"];
  readonly answer_intent_format: UserPreferencePayload["answer_intent_format"];
  readonly timezone: string | null;
  readonly share_with_learner: boolean;
  readonly expected_revision: number;
}): Promise<UserPreferencePayload> {
  return decodeUserPreference(await request("/me/preferences", "PUT", input));
}

export async function deleteUserPreference(): Promise<void> {
  await request("/me/preferences", "DELETE");
}

export async function putConversationPolicy(input: Record<string, unknown>): Promise<Record<string, unknown>> {
  return request("/me/policies", "PUT", { ...input, confirmed: true });
}

export async function deleteConversationPolicy(policyId: string, revision: number): Promise<void> {
  await request(
    `/me/policies/${encodeURIComponent(policyId)}?expected_revision=${revision}`,
    "DELETE",
  );
}

export async function deleteUserMemory(memoryId: string): Promise<void> {
  await request(`/me/memories/${encodeURIComponent(memoryId)}`, "DELETE");
}

export async function createBriefingSubscription(
  input: Record<string, unknown>,
  idempotencyKey: string,
): Promise<Record<string, unknown>> {
  return request("/me/briefing-subscriptions", "POST", {
    ...input,
    idempotency_key: idempotencyKey,
    confirmed: true,
  });
}

export async function deleteBriefingSubscription(
  subscriptionId: string,
  revision: number,
): Promise<void> {
  await request(
    `/me/briefing-subscriptions/${encodeURIComponent(subscriptionId)}?expected_revision=${revision}`,
    "DELETE",
  );
}

async function request(
  path: string,
  method: "GET" | "POST" | "PUT" | "DELETE",
  body?: Record<string, unknown>,
): Promise<Record<string, unknown>> {
  const base = loadConfig().readApiBaseUrl || window.location.origin;
  const headers: Record<string, string> = { accept: "application/json" };
  if (body !== undefined) headers["content-type"] = "application/json";
  const authorization = authContext ? await authContext.getAuthorizationHeader() : null;
  if (authorization !== null) headers.authorization = authorization;
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), 10_000);
  let response: Response;
  try {
    response = await fetch(`${base.replace(/\/$/, "")}${path}`, {
      method,
      headers,
      credentials: "omit",
      signal: controller.signal,
      ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new UserContextRequestError("User context request timed out", 0);
    }
    throw error;
  } finally {
    window.clearTimeout(timer);
  }
  if (!response.ok) {
    let detail = `HTTP ${response.status}`;
    try {
      const payload = await response.json() as {
        readonly detail?: unknown;
        readonly error?: { readonly message?: unknown };
      };
      if (typeof payload.detail === "string") detail = payload.detail;
      else if (typeof payload.error?.message === "string") detail = payload.error.message;
    } catch {
      /* keep status */
    }
    throw new UserContextRequestError(detail, response.status);
  }
  if (response.status === 204) return {};
  return await response.json() as Record<string, unknown>;
}

export function decodeUserContext(value: unknown): UserContextPayload {
  const root = object(value, "user context");
  return {
    preference: root["preference"] === null
      ? null
      : decodeUserPreference(root["preference"]),
    memories: array(root["memories"], "memories").map(decodeMemory),
    policies: array(root["policies"], "policies").map(decodePolicy),
    subscriptions: array(root["subscriptions"], "subscriptions").map(decodeSubscription),
    briefing_runs: array(root["briefing_runs"], "briefing_runs").map(decodeBriefingRun),
    scheduled_continuations: array(
      root["scheduled_continuations"],
      "scheduled_continuations",
    ).map(decodeScheduledContinuation),
    conversations: array(root["conversations"], "conversations").map(decodeConversation),
  };
}

export function decodeConversationSearch(value: unknown): ConversationSearchPayload {
  const root = object(value, "conversation search");
  return {
    hits: array(root["hits"], "conversation search.hits").map(decodeSearchHit),
    result_cap: positiveInteger(root["result_cap"], "conversation search.result_cap"),
    index_rows: nonNegativeInteger(root["index_rows"], "conversation search.index_rows"),
    index_bytes: nonNegativeInteger(root["index_bytes"], "conversation search.index_bytes"),
  };
}

export function decodeConversationSearchContext(
  value: unknown,
): ConversationSearchContextPayload {
  const root = object(value, "conversation search context");
  return {
    hit: decodeSearchHit(root["hit"]),
    before: array(root["before"], "conversation search context.before").map(decodeSearchHit),
    after: array(root["after"], "conversation search context.after").map(decodeSearchHit),
  };
}

function decodeSearchHit(value: unknown): ConversationSearchHitPayload {
  const item = object(value, "conversation search hit");
  const role = string(item["role"], "conversation search hit.role");
  if (!["operator", "assistant", "tool", "system"].includes(role)) {
    throw new Error("conversation search hit.role is invalid");
  }
  const snippet = object(item["snippet"], "conversation search hit.snippet");
  return {
    result_id: string(item["result_id"], "conversation search hit.result_id"),
    turn_id: string(item["turn_id"], "conversation search hit.turn_id"),
    conversation_id: string(
      item["conversation_id"],
      "conversation search hit.conversation_id",
    ),
    channel_id: string(item["channel_id"], "conversation search hit.channel_id"),
    role: role as ConversationSearchHitPayload["role"],
    snippet: {
      text: string(snippet["text"], "conversation search hit.snippet.text"),
      highlights: array(
        snippet["highlights"],
        "conversation search hit.snippet.highlights",
      ).map((raw) => {
        const range = object(raw, "conversation search highlight");
        return {
          start: nonNegativeInteger(range["start"], "conversation search highlight.start"),
          end: positiveInteger(range["end"], "conversation search highlight.end"),
        };
      }),
    },
    recorded_at: dateString(item["recorded_at"], "conversation search hit.recorded_at"),
    rank: finiteNumber(item["rank"], "conversation search hit.rank"),
    incident_id: nullableString(item["incident_id"], "conversation search hit.incident_id"),
    correlation_id: nullableString(
      item["correlation_id"],
      "conversation search hit.correlation_id",
    ),
    evidence_refs: stringArray(
      item["evidence_refs"],
      "conversation search hit.evidence_refs",
    ),
  };
}

function decodeUserPreference(value: unknown): UserPreferencePayload {
  const item = object(value, "preference");
  const locale = string(item["locale"], "preference.locale");
  const verbosity = string(item["verbosity"], "preference.verbosity");
  const answerDetail = string(item["answer_detail"], "preference.answer_detail");
  const answerFormat = string(item["answer_format"], "preference.answer_format");
  if (locale !== "en" && locale !== "ko") throw new Error("preference.locale is invalid");
  if (verbosity !== "concise" && verbosity !== "detailed") {
    throw new Error("preference.verbosity is invalid");
  }
  if (!["brief", "standard", "deep"].includes(answerDetail)) {
    throw new Error("preference.answer_detail is invalid");
  }
  if (!["prose", "bullets", "numbered_steps", "table", "checklist", "mixed"].includes(answerFormat)) {
    throw new Error("preference.answer_format is invalid");
  }
  return {
    principal_id: string(item["principal_id"], "preference.principal_id"),
    locale,
    verbosity,
    answer_detail: answerDetail as UserPreferencePayload["answer_detail"],
    answer_format: answerFormat as UserPreferencePayload["answer_format"],
    answer_preferences_enabled: boolean(
      item["answer_preferences_enabled"],
      "preference.answer_preferences_enabled",
    ),
    answer_intent_detail: enumRecord(
      item["answer_intent_detail"],
      "preference.answer_intent_detail",
      ["brief", "standard", "deep"] as const,
    ),
    answer_intent_format: enumRecord(
      item["answer_intent_format"],
      "preference.answer_intent_format",
      ["prose", "bullets", "numbered_steps", "table", "checklist", "mixed"] as const,
    ),
    timezone: nullableString(item["timezone"], "preference.timezone"),
    share_with_learner: boolean(item["share_with_learner"], "preference.share_with_learner"),
    revision: nonNegativeInteger(item["revision"], "preference.revision"),
  };
}

function decodeMemory(value: unknown): UserMemoryPayload {
  const item = object(value, "memory");
  const category = string(item["category"], "memory.category");
  if (!["preference", "context", "goal"].includes(category)) {
    throw new Error("memory.category is invalid");
  }
  return {
    memory_id: string(item["memory_id"], "memory.memory_id"),
    category: category as UserMemoryPayload["category"],
    body: string(item["body"], "memory.body"),
    source_turn_id: string(item["source_turn_id"], "memory.source_turn_id"),
    created_at: dateString(item["created_at"], "memory.created_at"),
    expires_at: nullableDateString(item["expires_at"], "memory.expires_at"),
  };
}

function decodePolicy(value: unknown): ConversationPolicyPayload {
  const item = object(value, "policy");
  const kind = string(item["kind"], "policy.kind");
  if (kind !== "opening_briefing" && kind !== "response_defaults") {
    throw new Error("policy.kind is invalid");
  }
  return {
    policy_id: string(item["policy_id"], "policy.policy_id"),
    kind,
    enabled: boolean(item["enabled"], "policy.enabled"),
    revision: nonNegativeInteger(item["revision"], "policy.revision"),
    source_turn_id: string(item["source_turn_id"], "policy.source_turn_id"),
    briefing_spec: nullableRecord(item["briefing_spec"], "policy.briefing_spec"),
    response_defaults: stringRecord(item["response_defaults"], "policy.response_defaults"),
  };
}

function decodeSubscription(value: unknown): BriefingSubscriptionPayload {
  const item = object(value, "subscription");
  return {
    subscription_id: string(item["subscription_id"], "subscription.subscription_id"),
    name: string(item["name"], "subscription.name"),
    cron_expression: string(item["cron_expression"], "subscription.cron_expression"),
    timezone: string(item["timezone"], "subscription.timezone"),
    enabled: boolean(item["enabled"], "subscription.enabled"),
    next_run_at: dateString(item["next_run_at"], "subscription.next_run_at"),
    spec: object(item["spec"], "subscription.spec"),
    revision: positiveInteger(item["revision"], "subscription.revision"),
  };
}

function decodeBriefingRun(value: unknown): BriefingRunPayload {
  const item = object(value, "briefing run");
  return {
    run_id: string(item["run_id"], "briefing_run.run_id"),
    title: string(item["title"], "briefing_run.title"),
    body_markdown: string(item["body_markdown"], "briefing_run.body_markdown"),
    status: string(item["status"], "briefing_run.status"),
    item_count: nonNegativeInteger(item["item_count"], "briefing_run.item_count"),
    evidence_refs: stringArray(item["evidence_refs"], "briefing_run.evidence_refs"),
    source_errors: stringArray(item["source_errors"], "briefing_run.source_errors"),
  };
}

function decodeScheduledContinuation(value: unknown): ScheduledContinuationPayload {
  const item = object(value, "scheduled continuation");
  const origin = object(item["origin"], "scheduled continuation.origin");
  const mode = string(item["mode"], "scheduled continuation.mode");
  const state = string(item["state"], "scheduled continuation.state");
  const audience = string(origin["audience"], "scheduled continuation.origin.audience");
  if (!(["origin_thread", "dedicated_thread"] as const).includes(mode as never)) {
    throw new Error("scheduled continuation.mode is invalid");
  }
  if (!(["active", "expired"] as const).includes(state as never)) {
    throw new Error("scheduled continuation.state is invalid");
  }
  if (audience !== "direct") throw new Error("scheduled continuation audience is invalid");
  const resultDigest = string(item["result_digest"], "scheduled continuation.result_digest");
  if (!/^[a-f0-9]{64}$/.test(resultDigest)) {
    throw new Error("scheduled continuation.result_digest MUST be SHA-256");
  }
  return {
    anchor_id: string(item["anchor_id"], "scheduled continuation.anchor_id"),
    task_id: string(item["task_id"], "scheduled continuation.task_id"),
    run_id: string(item["run_id"], "scheduled continuation.run_id"),
    owner_principal_id: string(
      item["owner_principal_id"],
      "scheduled continuation.owner_principal_id",
    ),
    scope_ref: string(item["scope_ref"], "scheduled continuation.scope_ref"),
    mode: mode as ScheduledContinuationPayload["mode"],
    origin: {
      channel_kind: string(origin["channel_kind"], "scheduled continuation.origin.channel_kind"),
      channel_ref: string(origin["channel_ref"], "scheduled continuation.origin.channel_ref"),
      conversation_ref: string(
        origin["conversation_ref"],
        "scheduled continuation.origin.conversation_ref",
      ),
      thread_ref: nullableString(
        origin["thread_ref"],
        "scheduled continuation.origin.thread_ref",
      ),
      audience: "direct",
    },
    result_digest: resultDigest,
    result_summary: string(item["result_summary"], "scheduled continuation.result_summary"),
    evidence_refs: stringArray(
      item["evidence_refs"],
      "scheduled continuation.evidence_refs",
    ),
    observation_started_at: dateString(
      item["observation_started_at"],
      "scheduled continuation.observation_started_at",
    ),
    observation_ended_at: dateString(
      item["observation_ended_at"],
      "scheduled continuation.observation_ended_at",
    ),
    created_at: dateString(item["created_at"], "scheduled continuation.created_at"),
    expires_at: dateString(item["expires_at"], "scheduled continuation.expires_at"),
    state: state as ScheduledContinuationPayload["state"],
  };
}

function decodeConversation(value: unknown): ConversationSummaryPayload {
  const item = object(value, "conversation");
  return {
    conversation_id: string(item["conversation_id"], "conversation.conversation_id"),
    channel_id: string(item["channel_id"], "conversation.channel_id"),
    started_at: dateString(item["started_at"], "conversation.started_at"),
    last_active: dateString(item["last_active"], "conversation.last_active"),
    status: string(item["status"], "conversation.status"),
    latest_operator_turn_id: nullableString(
      item["latest_operator_turn_id"],
      "conversation.latest_operator_turn_id",
    ),
  };
}

function object(value: unknown, label: string): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error(`${label} MUST be an object`);
  }
  return value as Record<string, unknown>;
}

function array(value: unknown, label: string): readonly unknown[] {
  if (!Array.isArray(value)) throw new Error(`${label} MUST be an array`);
  return value;
}

function string(value: unknown, label: string): string {
  if (typeof value !== "string" || !value) throw new Error(`${label} MUST be a string`);
  return value;
}

function nullableString(value: unknown, label: string): string | null {
  if (value === null) return null;
  return string(value, label);
}

function boolean(value: unknown, label: string): boolean {
  if (typeof value !== "boolean") throw new Error(`${label} MUST be a boolean`);
  return value;
}

function nonNegativeInteger(value: unknown, label: string): number {
  if (typeof value !== "number" || !Number.isInteger(value) || value < 0) {
    throw new Error(`${label} MUST be a non-negative integer`);
  }
  return value;
}

function finiteNumber(value: unknown, label: string): number {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    throw new Error(`${label} MUST be a finite number`);
  }
  return value;
}

function positiveInteger(value: unknown, label: string): number {
  const parsed = nonNegativeInteger(value, label);
  if (parsed < 1) throw new Error(`${label} MUST be positive`);
  return parsed;
}

function dateString(value: unknown, label: string): string {
  const parsed = string(value, label);
  if (!Number.isFinite(Date.parse(parsed))) throw new Error(`${label} MUST be ISO 8601`);
  return parsed;
}

function nullableDateString(value: unknown, label: string): string | null {
  if (value === null) return null;
  return dateString(value, label);
}

function stringArray(value: unknown, label: string): readonly string[] {
  return array(value, label).map((item) => string(item, `${label}[]`));
}

function nullableRecord(value: unknown, label: string): Readonly<Record<string, unknown>> | null {
  if (value === null) return null;
  return object(value, label);
}

function stringRecord(value: unknown, label: string): Readonly<Record<string, string>> {
  const record = object(value, label);
  return Object.fromEntries(
    Object.entries(record).map(([key, item]) => [key, string(item, `${label}.${key}`)]),
  );
}

function enumRecord<const Value extends string>(
  value: unknown,
  label: string,
  allowed: readonly Value[],
): Readonly<Record<string, Value>> {
  const record = stringRecord(value, label);
  if (Object.values(record).some((item) => !allowed.includes(item as Value))) {
    throw new Error(`${label} contains an invalid value`);
  }
  return record as Readonly<Record<string, Value>>;
}
