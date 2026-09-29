import { chatUrl, requestHeaders } from "./backend-endpoints";
import type { TestContextDraft } from "./test-context";

export interface TestContextCommandStatus {
  readonly proposalId: string;
  readonly operation: "propose" | "review" | "revoke";
  readonly delivery: "pending" | "claimed" | "published" | "rejected";
  readonly acceptedAt: string;
  readonly policyApplication: "unknown" | "recorded";
  readonly currentAuthorization: "not_evaluated" | "unavailable" | "pending" | "active" | "revoked" | "expired";
  readonly application?: {
    readonly state: "proposed" | "reviewed" | "revoked";
    readonly revision: number;
  };
  readonly request: TestContextStatusRequest;
  readonly reviewerTransitionAllowed: boolean;
  readonly requesterIsCurrentPrincipal: boolean;
}

export interface TestContextStatusRequest {
  readonly contextId: string;
  readonly accessScopeDigest: string;
  readonly targetRef: string;
  readonly signalCode: string;
  readonly policyRevision: string;
  readonly sourceRef: string;
  readonly semanticReceipt: string;
  readonly expectedMin?: number;
  readonly expectedMax?: number;
  readonly effectiveFrom?: string;
  readonly effectiveTo?: string;
}

function record(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown> : null;
}

export function validProposalId(value: string): boolean {
  return value.length > 0 && value.length <= 256 && value.trim() === value &&
    !/[\x00-\x1f\x7f]/.test(value);
}

/** Unknown, inconsistent, or authority-bearing projections are never rendered as success. */
export function decodeTestContextStatus(value: unknown, requestedId: string): TestContextCommandStatus | null {
  const status = record(value);
  const application = record(status?.context_application);
  const operation = status?.operation;
  const delivery = status?.dispatch_status;
  const policyApplication = status?.policy_application;
  const currentAuthorization = status?.current_authorization;
  const expectedState = operation === "test-context.propose" ? "proposed"
    : operation === "test-context.review" ? "reviewed"
    : operation === "test-context.revoke" ? "revoked" : null;
  const request = decodeStatusRequest(status?.request);
  if (!status || status.schema_version && status.schema_version !== "1.0.0") return null;
  if (!status || !validProposalId(requestedId) || status.proposal_id !== requestedId ||
    !request || !expectedState || !["pending", "claimed", "published", "rejected"].includes(String(delivery)) ||
    typeof status.accepted_at !== "string" ||
    !/^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|[+-]\d\d:\d\d)$/.test(status.accepted_at) ||
    !Number.isFinite(Date.parse(status.accepted_at)) ||
    !["unknown", "recorded"].includes(String(policyApplication)) ||
    !["not_evaluated", "unavailable", "pending", "active", "revoked", "expired"].includes(String(currentAuthorization)) ||
    status.execution_authority !== false ||
    (policyApplication === "recorded") !== (application !== null) ||
    typeof status.reviewer_transition_allowed !== "boolean" ||
    typeof status.requester_is_current_principal !== "boolean" ||
    (policyApplication === "recorded" && delivery !== "published") ||
    (application && (application.execution_authority !== false ||
      application.state !== expectedState || !Number.isSafeInteger(application.revision) ||
      (application.revision as number) < 1)) ||
    !authorizationStateIsValid(String(currentAuthorization), application)) return null;
  return {
    proposalId: requestedId,
    operation: (operation as string).slice("test-context.".length) as TestContextCommandStatus["operation"],
    delivery: delivery as TestContextCommandStatus["delivery"],
    acceptedAt: status.accepted_at,
    policyApplication: policyApplication as TestContextCommandStatus["policyApplication"],
    currentAuthorization: currentAuthorization as TestContextCommandStatus["currentAuthorization"],
    request,
    reviewerTransitionAllowed: status.reviewer_transition_allowed,
    requesterIsCurrentPrincipal: status.requester_is_current_principal,
    ...(application ? { application: {
      state: application.state as "proposed" | "reviewed" | "revoked",
      revision: application.revision as number,
    } } : {}),
  };
}

function decodeStatusRequest(value: unknown): TestContextStatusRequest | null {
  const request = record(value);
  if (!request) return null;
  const contextId = text(request.context_id);
  const accessScopeDigest = digest(request.access_scope_digest);
  const targetRef = text(request.target_ref);
  const signalCode = text(request.signal_code);
  const policyRevision = text(request.policy_revision);
  const sourceRef = text(request.source_ref);
  const semanticReceipt = typeof request.semantic_receipt === "string" &&
    /^sha256:[a-f0-9]{64}$/.test(request.semantic_receipt) ? request.semantic_receipt : null;
  const expectedMin = finiteOptional(request.expected_min);
  const expectedMax = finiteOptional(request.expected_max);
  const effectiveFrom = timeOptional(request.effective_from);
  const effectiveTo = timeOptional(request.effective_to);
  if (expectedMin === null || expectedMax === null || effectiveFrom === null || effectiveTo === null) return null;
  return contextId && accessScopeDigest && targetRef && signalCode && policyRevision && sourceRef && semanticReceipt
    ? {
      contextId, accessScopeDigest, targetRef, signalCode, policyRevision, sourceRef, semanticReceipt,
      ...(expectedMin !== undefined && expectedMin !== null ? { expectedMin } : {}),
      ...(expectedMax !== undefined && expectedMax !== null ? { expectedMax } : {}),
      ...(effectiveFrom ? { effectiveFrom } : {}),
      ...(effectiveTo ? { effectiveTo } : {}),
    }
    : null;
}

function finiteOptional(value: unknown): number | null | undefined {
  if (value === undefined) return undefined;
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function timeOptional(value: unknown): string | null | undefined {
  if (value === undefined) return undefined;
  return typeof value === "string" &&
    /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|[+-]\d\d:\d\d)$/.test(value) &&
    Number.isFinite(Date.parse(value)) ? value : null;
}

function authorizationStateIsValid(
  state: string,
  application: Record<string, unknown> | null,
): boolean {
  if (state === "active") return application?.state === "reviewed";
  if (state === "revoked") return application?.state === "revoked";
  if (state === "expired") return application?.state === "reviewed";
  if (state === "pending") return application === null || application.state === "proposed";
  return true;
}

export type StatusReadResult =
  | { readonly kind: "ready"; readonly status: TestContextCommandStatus }
  | { readonly kind: "unavailable" | "error" };

/** Read only the authenticated requesting principal's command; do not poll or cache. */
export async function readTestContextStatus(proposalId: string, signal?: AbortSignal): Promise<StatusReadResult> {
  if (!validProposalId(proposalId)) return { kind: "error" };
  try {
    const response = await fetch(
      `${chatUrl().replace(/\/chat$/, "")}/test-context/commands/${encodeURIComponent(proposalId)}`,
      { headers: await requestHeaders(), cache: "no-store", ...(signal ? { signal } : {}) },
    );
    if ([404, 501].includes(response.status)) return { kind: "unavailable" };
    if (!response.ok) return { kind: "error" };
    const status = decodeTestContextStatus(await response.json(), proposalId);
    return status ? { kind: "ready", status } : { kind: "error" };
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    return { kind: "error" };
  }
}


export interface TestContextChoice {
  readonly caseScopeId: string;
  readonly accessScopeDigest: string;
  readonly targetSelectors: readonly string[];
  readonly policyRevision: string;
  readonly sourceRevision: string;
  readonly allowedOperations: readonly ("propose" | "review" | "revoke")[];
}

export interface TestContextChoices {
  readonly sourceRevision: string | null;
  readonly choices: readonly TestContextChoice[];
  readonly unavailableReasons: readonly string[];
}

export type ChoiceReadResult =
  | { readonly kind: "ready"; readonly choices: TestContextChoices }
  | { readonly kind: "unavailable" | "error" };

export type CommandSubmitResult =
  | { readonly kind: "accepted"; readonly proposalId: string; readonly duplicate: boolean }
  | { readonly kind: "unavailable" | "conflict" | "error" };

function text(value: unknown, maximum = 512): string | null {
  return typeof value === "string" && value.length > 0 && value.length <= maximum &&
    value.trim() === value && !/[\x00-\x1f]/.test(value) ? value : null;
}

function digest(value: unknown): string | null {
  return typeof value === "string" && /^[a-f0-9]{64}$/.test(value) ? value : null;
}

export function decodeTestContextChoices(value: unknown): TestContextChoices | null {
  const body = record(value);
  if (!body || body.schema_version !== "1.0.0" || body.execution_authority !== false) return null;
  const sourceRevision = body.source_revision === null ? null : text(body.source_revision, 160);
  if (body.source_revision !== null && !sourceRevision) return null;
  if (!Array.isArray(body.choices) || !Array.isArray(body.unavailable_reasons)) return null;
  const unavailableReasons = body.unavailable_reasons.map((item) => text(item, 128));
  if (unavailableReasons.some((item) => item === null)) return null;
  const choices = body.choices.map((item) => {
    const choice = record(item);
    if (!choice || choice.execution_authority !== false || !Array.isArray(choice.target_selectors) ||
      !Array.isArray(choice.allowed_operations)) return null;
    const targetSelectors = choice.target_selectors.map((selector) => text(selector));
    const operations = choice.allowed_operations;
    if (targetSelectors.some((selector) => selector === null) || !operations.every((op) =>
      ["propose", "review", "revoke"].includes(String(op)))) return null;
    const caseScopeId = text(choice.case_scope_id, 128);
    const accessScopeDigest = digest(choice.access_scope_digest);
    const policyRevision = text(choice.policy_revision);
    const choiceSourceRevision = text(choice.source_revision, 160);
    return caseScopeId && accessScopeDigest && policyRevision && choiceSourceRevision ? {
      caseScopeId, accessScopeDigest, policyRevision, sourceRevision: choiceSourceRevision,
      targetSelectors: targetSelectors as string[],
      allowedOperations: operations as ("propose" | "review" | "revoke")[],
    } : null;
  });
  if (choices.some((choice) => choice === null) || (!choices.length && !unavailableReasons.length)) return null;
  return { sourceRevision, choices: choices as TestContextChoice[], unavailableReasons: unavailableReasons as string[] };
}

export async function readTestContextChoices(signal?: AbortSignal): Promise<ChoiceReadResult> {
  try {
    const response = await fetch(`${chatUrl().replace(/\/chat$/, "")}/test-context/choices`, {
      headers: await requestHeaders(), cache: "no-store", ...(signal ? { signal } : {}),
    });
    if ([404, 501, 503].includes(response.status)) return { kind: "unavailable" };
    if (!response.ok) return { kind: "error" };
    const choices = decodeTestContextChoices(await response.json());
    return choices ? { kind: "ready", choices } : { kind: "error" };
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    return { kind: "error" };
  }
}

export function targetMatchesChoice(draft: TestContextDraft, choice: TestContextChoice): boolean {
  const target = draft.target_ref.toLowerCase();
  return choice.targetSelectors.some((selector) => {
    const value = selector.toLowerCase();
    return value.endsWith("/*") ? target.startsWith(value.slice(0, -1)) && target.length > value.length - 1 : target === value;
  });
}

export async function submitTestContextCommand(
  operation: "propose" | "review" | "revoke",
  draft: TestContextDraft,
  choice: TestContextChoice,
  expectedRevision: number,
  sourceRequest?: TestContextStatusRequest,
  signal?: AbortSignal,
): Promise<CommandSubmitResult> {
  const request = sourceRequest ?? {
    contextId: contextIdForDraft(draft, choice),
    accessScopeDigest: choice.accessScopeDigest,
    targetRef: draft.target_ref,
    signalCode: draft.signal_code,
    policyRevision: choice.policyRevision,
    sourceRef: draft.source_ref,
    semanticReceipt: draft.semantic_receipt,
  };
  const body: Record<string, unknown> = {
    operation, context_id: request.contextId,
    access_scope_digest: request.accessScopeDigest, target_ref: request.targetRef,
    signal_code: request.signalCode, expected_revision: expectedRevision,
    policy_revision: request.policyRevision, source_ref: request.sourceRef,
    semantic_receipt: request.semanticReceipt,
  };
  if (operation === "propose") Object.assign(body, {
    expected_min: draft.window.expected_min, expected_max: draft.window.expected_max,
    effective_from: draft.window.effective_from, effective_to: draft.window.effective_to,
  });
  try {
    const response = await fetch(`${chatUrl().replace(/\/chat$/, "")}/test-context/${operation === "propose" ? "proposals" : operation === "review" ? "reviews" : "revocations"}`, {
      method: "POST", headers: await requestHeaders(true), cache: "no-store", body: JSON.stringify(body), ...(signal ? { signal } : {}),
    });
    if (response.status === 409) return { kind: "conflict" };
    if ([404, 501, 503].includes(response.status)) return { kind: "unavailable" };
    if (!response.ok) return { kind: "error" };
    const payload = record(await response.json());
    const proposalId = text(payload?.proposal_id, 256);
    return proposalId && payload?.accepted === true
      ? { kind: "accepted", proposalId, duplicate: payload.duplicate === true }
      : { kind: "error" };
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    return { kind: "error" };
  }
}


export function contextIdForDraft(draft: TestContextDraft, choice: TestContextChoice): string {
  return `${choice.caseScopeId}:${draft.signal_code}:${draft.semantic_receipt.slice("sha256:".length, "sha256:".length + 16)}`;
}
