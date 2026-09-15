/** The six scoped-duty routes only: strict read projections and proposal-only, non-retrying writes. */
import type { OperatorApiClient } from "../api";
import { PANTHEON } from "./agents.model";
import {
  ScopedDutyError, isScopedDutyCaseId, isScopedDutyCoreId, isScopedDutyRef,
  scopedDutyBindingIdentity, scopedDutyInstant, scopedDutyRequestIssues,
  type ScopedDutyBinding, type ScopedDutyCase, type ScopedDutyCaseRead,
  type ScopedDutyCatalog, type ScopedDutyCoverage, type ScopedDutyCreation,
  type ScopedDutyErrorCode, type ScopedDutyPlan, type ScopedDutyProjection,
  type ScopedDutyProposal, type ScopedDutyRequest, type ScopedDutyResolution,
  type ScopedDutySubject, type ScopedDutyWindow,
} from "./scoped-duty-model";

type ObjectValue = Record<string, unknown>;
const ROOT = "/handover/scoped-duty-cases";
const HEX = /^[a-f0-9]{64}$/;
const MAX_BYTES = 2_097_152;

function requireValue(condition: unknown): asserts condition {
  if (!condition) throw new ScopedDutyError("malformed");
}
function object(value: unknown): ObjectValue {
  requireValue(value !== null && typeof value === "object" && !Array.isArray(value));
  return value as ObjectValue;
}
function keys(value: ObjectValue, required: readonly string[], optional: readonly string[] = []): void {
  requireValue(required.every((key) => Object.hasOwn(value, key))
    && Object.keys(value).every((key) => required.includes(key) || optional.includes(key)));
}
function token(value: unknown, normalized = false): string {
  requireValue(isScopedDutyRef(value, normalized));
  return value;
}
function digest(value: unknown): string {
  const result = token(value);
  requireValue(HEX.test(result));
  return result;
}
function integer(value: unknown, minimum = 0): number {
  requireValue(typeof value === "number" && Number.isSafeInteger(value) && value >= minimum);
  return value;
}
function boolean(value: unknown): boolean {
  requireValue(typeof value === "boolean");
  return value;
}
function timestamp(value: unknown): string {
  requireValue(typeof value === "string" && Number.isFinite(scopedDutyInstant(value)));
  return value;
}
function list<T>(value: unknown, maximum: number, read: (item: unknown) => T): readonly T[] {
  requireValue(Array.isArray(value) && value.length <= maximum);
  return value.map((item: unknown) => read(item));
}
function unique(values: readonly string[]): readonly string[] {
  requireValue(new Set(values).size === values.length);
  return values;
}
function nullable<T>(value: unknown, read: (item: unknown) => T): T | null {
  return value === null ? null : read(value);
}
function choice<T extends string>(value: unknown, values: readonly T[]): T {
  requireValue(typeof value === "string" && values.includes(value as T));
  return value as T;
}
function subject(value: unknown): ScopedDutySubject {
  const row = object(value);
  keys(row, ["kind", "ref"]);
  return { kind: choice(row.kind, ["user", "group", "schedule"]), ref: token(row.ref, true) };
}
function binding(value: unknown): ScopedDutyBinding {
  const row = object(value);
  keys(row, ["subject", "agent_name", "scope_ref", "duty", "effective_from", "effective_until", "fallback"]);
  return { subject: subject(row.subject), agent_name: token(row.agent_name), scope_ref: token(row.scope_ref),
    duty: choice(row.duty, ["primary", "backup", "escalation"]),
    effective_from: timestamp(row.effective_from), effective_until: timestamp(row.effective_until),
    fallback: nullable(row.fallback, subject) };
}
function request(value: unknown): ScopedDutyRequest {
  const row = object(value);
  keys(row, ["schema_version", "source_revision", "bindings", "supersedes_case_id"]);
  const result: ScopedDutyRequest = { schema_version: choice(row.schema_version, ["1.0.0"]),
    source_revision: token(row.source_revision), bindings: list(row.bindings, 30, binding),
    supersedes_case_id: nullable(row.supersedes_case_id, token) };
  requireValue(scopedDutyRequestIssues(result).length === 0);
  return result;
}
function window(value: ObjectValue): ScopedDutyWindow {
  requireValue(value.execution_authority === false);
  const start = timestamp(value.observed_at), end = timestamp(value.expires_at);
  const duration = scopedDutyInstant(end) - scopedDutyInstant(start);
  requireValue(duration > 0 && duration <= 300_000);
  return { source_revision: token(value.source_revision), observed_at: start,
    expires_at: end, execution_authority: false };
}
function coverage(value: unknown): ScopedDutyCoverage {
  const row = object(value);
  const result: ScopedDutyCoverage = { agent_name: token(row.agent_name), scope_ref: token(row.scope_ref),
    primary_refs: unique(list(row.primary_refs, 3000, (item) => token(item, true))),
    backup_refs: unique(list(row.backup_refs, 3000, (item) => token(item, true))),
    escalation_refs: unique(list(row.escalation_refs, 3000, (item) => token(item, true))),
    held_reasons: unique(list(row.held_reasons, 30, token)) };
  requireValue(PANTHEON.some((agent) => agent.name === result.agent_name));
  requireValue(![...result.backup_refs, ...result.escalation_refs].some((ref) => result.primary_refs.includes(ref)));
  return result;
}
function hasCoverage(row: ScopedDutyCoverage): boolean {
  return row.held_reasons.length === 0 && row.primary_refs.length > 0
    && row.backup_refs.length + row.escalation_refs.length > 0;
}

/** Decode the complete catalog. Missing fields, duplicate scopes or authority flags fail closed. */
export function decodeScopedDutyCatalog(value: unknown): ScopedDutyCatalog {
  const row = object(value);
  keys(row, ["source_revision", "scopes", "observed_at", "expires_at", "artifact_delivery_available", "execution_authority"]);
  const scopes = unique(list(row.scopes, 1000, token));
  requireValue(scopes.length > 0);
  return { ...window(row), scopes, artifact_delivery_available: boolean(row.artifact_delivery_available) };
}

/** Reject another selector's projection and never relabel partial or held rows as observed. */
export function decodeScopedDutyProjection(value: unknown, agent: string, scope: string): ScopedDutyProjection {
  const row = object(value), facts = coverage(row);
  requireValue(facts.agent_name === agent && facts.scope_ref === scope);
  const state = choice(row.state, ["observed", "held"]);
  const partial = boolean(row.partial), invalid = integer(row.invalid_cases);
  if (state === "held") requireValue(facts.held_reasons.length > 0
    && facts.primary_refs.length + facts.backup_refs.length + facts.escalation_refs.length === 0);
  else requireValue(!partial && invalid === 0 && hasCoverage(facts));
  const artifact = state === "held" ? null : {
    case_id: token(row.case_id), case_revision: integer(row.case_revision, 1),
    candidate_digest: digest(row.candidate_digest), merge_commit_sha: token(row.merge_commit_sha),
    pr_ref: token(row.pr_ref),
  };
  if (artifact) requireValue(isScopedDutyCoreId(artifact.case_id) && /^[a-f0-9]{40}$/.test(artifact.merge_commit_sha));
  return { ...facts, ...window(row), state, partial, invalid_cases: invalid, artifact };
}

function resolution(value: unknown): ScopedDutyResolution {
  const row = object(value);
  const people = list(row.people, 100, subject);
  unique(people.map((person) => person.ref));
  requireValue(people.every((person) => person.kind === "user"));
  const source = subject(row.subject);
  requireValue(source.kind !== "user" || people.length === 0 || (people.length === 1 && people[0]!.ref === source.ref));
  const observed = timestamp(row.observed_at), until = timestamp(row.valid_until);
  requireValue(scopedDutyInstant(observed) < scopedDutyInstant(until));
  return { subject: source, people, at: timestamp(row.at), observed_at: observed, valid_until: until,
    provenance_ref: token(row.provenance_ref), provenance_digest: digest(row.provenance_digest), complete: boolean(row.complete) };
}
function plan(value: unknown, input: ScopedDutyRequest): ScopedDutyPlan {
  const row = object(value), policy = object(row.policy);
  requireValue(row.execution_authority === false && row.review_required === true && row.source_revision === input.source_revision);
  requireValue((row.supersedes_case_id ?? null) === input.supersedes_case_id);
  const checked = timestamp(row.checked_at), at = timestamp(row.resolution_at);
  const maxAge = integer(policy.max_resolution_age_microseconds, 1);
  const readTimeout = policy.read_timeout_seconds, totalTimeout = policy.total_timeout_seconds;
  requireValue(typeof readTimeout === "number" && readTimeout > 0 && readTimeout <= 30
    && typeof totalTimeout === "number" && totalTimeout > 0 && totalTimeout <= 120);
  const bindings = list(row.bindings, 30, (item) => {
    const entry = object(item), declared = binding(entry.binding);
    const rawScope = entry.scope === null ? null : object(entry.scope);
    const scope = rawScope === null ? null : { scope_ref: token(rawScope.scope_ref), source_revision: token(rawScope.source_revision) };
    if (scope) requireValue(scope.scope_ref === declared.scope_ref && scope.source_revision === input.source_revision);
    const resolved = nullable(entry.resolution, resolution);
    const held = nullable(entry.held_reason, token), failure = nullable(entry.schedule_failure, token);
    const used = boolean(entry.used_fallback);
    requireValue(used === (failure !== null && resolved !== null));
    if (failure !== null) requireValue(declared.subject.kind === "schedule" && declared.fallback !== null);
    if (resolved) {
      const expected = failure === null ? declared.subject : declared.fallback;
      requireValue(expected !== null && resolved.subject.kind === expected.kind && resolved.subject.ref === expected.ref
        && scopedDutyInstant(resolved.at) === scopedDutyInstant(at));
    }
    if (held === null) {
      requireValue(scope !== null && resolved !== null && resolved.complete && resolved.people.length > 0);
      const instant = scopedDutyInstant(checked), start = scopedDutyInstant(resolved.observed_at);
      requireValue(start <= instant && instant < scopedDutyInstant(resolved.valid_until) && instant - start < maxAge / 1000
        && scopedDutyInstant(declared.effective_from) <= instant && instant < scopedDutyInstant(declared.effective_until));
    }
    return { binding: declared, scope, resolution: resolved, held_reason: held, schedule_failure: failure,
      used_fallback: used, digest: digest(entry.digest) };
  });
  const expectedBindings = input.bindings.map(scopedDutyBindingIdentity).sort();
  requireValue(JSON.stringify(bindings.map((entry) => scopedDutyBindingIdentity(entry.binding)).sort()) === JSON.stringify(expectedBindings));
  const scopes = list(row.coverage, 30, coverage);
  const pair = (entry: { agent_name: string; scope_ref: string }) => JSON.stringify([entry.agent_name, entry.scope_ref]);
  unique(scopes.map(pair));
  requireValue(JSON.stringify(scopes.map(pair).sort()) === JSON.stringify([...new Set(input.bindings.map(pair))].sort()));
  const current = boolean(row.current_coverage);
  requireValue(current === (scopes.length > 0 && scopes.every(hasCoverage)));
  return { kind: choice(row.kind, ["scoped_duty_review"]), schema_version: choice(row.schema_version, ["1.0.0"]),
    source_revision: input.source_revision, input_digest: digest(row.input_digest), digest: digest(row.digest),
    resolution_at: at, checked_at: checked, coverage_basis: choice(row.coverage_basis, ["current_observation_only"]),
    current_coverage: current, review_required: true, execution_authority: false, bindings, coverage: scopes,
    policy: { max_resolution_age_microseconds: maxAge, read_timeout_seconds: readTimeout, total_timeout_seconds: totalTimeout },
    ...(input.supersedes_case_id === null ? {} : { supersedes_case_id: input.supersedes_case_id }) };
}

/** Decode an exact GET, optionally fencing refresh against a previously read case identity/revision. */
export function decodeScopedDutyCase(value: unknown, caseId: string, previous?: ScopedDutyCaseRead): ScopedDutyCaseRead {
  const row = object(value);
  requireValue(isScopedDutyCaseId(caseId) && row.case_id === caseId && row.execution_authority === false);
  const input = request(row.request);
  const requestIdentity = (item: ScopedDutyRequest) => JSON.stringify([item.schema_version, item.source_revision,
    item.bindings.map(scopedDutyBindingIdentity), item.supersedes_case_id]);
  if (previous) requireValue(previous.case_id === caseId && requestIdentity(previous.request) === requestIdentity(input));
  if (row.state === "awaiting_core") {
    keys(row, ["case_id", "state", "revision", "request", "execution_authority"]);
    requireValue(row.revision === null && (!previous || previous.state === "awaiting_core"));
    return { case_id: caseId, state: "awaiting_core", revision: null, request: input, execution_authority: false };
  }
  const state = choice(row.state, ["draft", "pending_review", "approved", "ownership_pr_open", "ownership_merged", "rejected"]);
  const coreId = token(row.core_case_id), requester = token(row.requester_ref, true), retainedPlan = plan(row.plan, input);
  requireValue(isScopedDutyCoreId(coreId));
  const targets = new Set(input.bindings.flatMap((entry) => [
    ...(entry.subject.kind === "user" ? [entry.subject.ref] : []), ...(entry.fallback ? [entry.fallback.ref] : []),
  ]));
  for (const entry of retainedPlan.bindings) for (const person of entry.resolution?.people ?? []) targets.add(person.ref);
  const reviews = list(row.reviews, 2, (item) => {
    const review = object(item), reviewer = token(review.reviewer_ref, true);
    requireValue(reviewer !== requester && !targets.has(reviewer) && review.plan_digest === retainedPlan.digest);
    const reviewedAt = timestamp(review.reviewed_at);
    requireValue(scopedDutyInstant(reviewedAt) >= scopedDutyInstant(retainedPlan.checked_at));
    return { reviewer_ref: reviewer, decision: choice(review.decision, ["approve", "reject"]),
      plan_digest: digest(review.plan_digest), reviewed_at: reviewedAt };
  });
  unique(reviews.map((review) => review.reviewer_ref));
  requireValue(reviews.every((review, index) => index === 0
    || scopedDutyInstant(review.reviewed_at) >= scopedDutyInstant(reviews[index - 1]!.reviewed_at)));
  const approved = reviews.length === 2 && reviews.every((review) => review.decision === "approve");
  requireValue(approved === ["approved", "ownership_pr_open", "ownership_merged"].includes(state)
    && (reviews.some((review) => review.decision === "reject")) === (state === "rejected")
    && (state !== "draft" || reviews.length === 0)
    && (state === "draft" || retainedPlan.current_coverage));
  const pr = nullable(row.pr_ref, token), candidate = nullable(row.candidate_digest, digest), merge = nullable(row.merge_commit_sha, token);
  requireValue((pr === null) === (candidate === null)
    && (pr !== null && candidate !== null) === ["ownership_pr_open", "ownership_merged"].includes(state)
    && (merge !== null) === (state === "ownership_merged") && (merge === null || /^[a-f0-9]{40}$/.test(merge)));
  const result: ScopedDutyCase = { case_id: caseId, core_case_id: coreId, state, revision: integer(row.revision, 1),
    requester_ref: requester, request: input, plan: retainedPlan, reviews, pr_ref: pr,
    candidate_digest: candidate, merge_commit_sha: merge, execution_authority: false };
  if (previous && previous.state !== "awaiting_core") {
    requireValue(result.core_case_id === previous.core_case_id && result.requester_ref === previous.requester_ref
      && result.revision >= previous.revision
      && JSON.stringify(result.reviews.slice(0, previous.reviews.length)) === JSON.stringify(previous.reviews));
    if (previous.state !== "draft") requireValue(JSON.stringify(result.plan) === JSON.stringify(previous.plan));
    const order = ["draft", "pending_review", "approved", "ownership_pr_open", "ownership_merged"];
    requireValue(previous.state === "rejected" ? result.state === "rejected"
      : result.state === "rejected" ? ["draft", "pending_review"].includes(previous.state)
        : order.indexOf(result.state) >= order.indexOf(previous.state));
    if (result.revision === previous.revision) requireValue(JSON.stringify(result) === JSON.stringify(previous));
  }
  return result;
}

/** POST cannot supply a Core revision or state, even when a fixture or older peer advertises one. */
export function decodeScopedDutyProposal(value: unknown, expectedCaseId?: string): ScopedDutyProposal {
  const row = object(value);
  keys(row, ["case_id", "proposal_id", "accepted_at", "state", "execution_authority"]);
  const caseId = token(row.case_id), proposalId = token(row.proposal_id);
  requireValue(isScopedDutyCaseId(caseId) && isScopedDutyCaseId(proposalId)
    && row.state === "awaiting_core" && row.execution_authority === false
    && (expectedCaseId === undefined ? caseId === proposalId : caseId === expectedCaseId));
  return { case_id: caseId, proposal_id: proposalId, accepted_at: timestamp(row.accepted_at),
    state: "awaiting_core", execution_authority: false };
}

/** Inject the already authenticated client and fake fetch in tests; never retain authorization. */
export class ScopedDutyApi {
  constructor(private readonly client: Pick<OperatorApiClient, "operatorApiBaseUrl" | "authorizationHeader">,
    private readonly fetcher: typeof fetch = globalThis.fetch, private readonly timeoutMs = 10_000) {}

  /** Read every allowed scope under its original observation window. */
  async catalog(signal?: AbortSignal): Promise<ScopedDutyCatalog> {
    return decodeScopedDutyCatalog(await this.read("/handover/scoped-duties/catalog", signal));
  }
  /** Read exactly one agent/scope pair, never a list or inferred parent scope. */
  async projection(agent: string, scope: string, signal?: AbortSignal): Promise<ScopedDutyProjection> {
    if (!PANTHEON.some((item) => item.name === agent) || !isScopedDutyRef(scope)) throw new ScopedDutyError("invalid_input");
    const query = new URLSearchParams({ agent_name: agent, scope_ref: scope });
    return decodeScopedDutyProjection(await this.read(`/handover/scoped-duties?${query}`, signal), agent, scope);
  }
  /** Manual authoritative recovery; prior immutable identity may fence the result. */
  async getCase(caseId: string, signal?: AbortSignal, previous?: ScopedDutyCaseRead): Promise<ScopedDutyCaseRead> {
    this.caseInput(caseId);
    return decodeScopedDutyCase(await this.read(`${ROOT}/${caseId}`, signal), caseId, previous);
  }
  /** Submit exactly the retained creation bytes once; callers own any explicit retry. */
  async create(creation: ScopedDutyCreation, signal?: AbortSignal): Promise<ScopedDutyProposal> {
    let body: ObjectValue;
    try {
      body = object(JSON.parse(creation.body));
      keys(body, ["idempotency_key", "request", "justification"]);
      request(body.request);
      requireValue(isScopedDutyRef(body.idempotency_key) && body.idempotency_key.length <= 160
        && body.idempotency_key === creation.idempotencyKey && typeof body.justification === "string"
        && [...body.justification.trim()].length >= 20 && [...body.justification].length <= 2000);
    } catch { throw new ScopedDutyError("invalid_input"); }
    return decodeScopedDutyProposal(await this.send(ROOT, "POST", creation.body, signal));
  }
  /** Propose submission of one observed revision without interpreting acceptance as transition. */
  async submit(caseId: string, revision: number, signal?: AbortSignal): Promise<ScopedDutyProposal> {
    this.caseInput(caseId, revision);
    return decodeScopedDutyProposal(await this.send(`${ROOT}/${caseId}/submit`, "POST",
      JSON.stringify({ expected_revision: revision }), signal), caseId);
  }
  /** Propose a digest-bound review; no current role or quorum is inferred by this client. */
  async review(caseId: string, revision: number, decision: "approve" | "reject", planDigest: string, signal?: AbortSignal): Promise<ScopedDutyProposal> {
    this.caseInput(caseId, revision);
    if (!HEX.test(planDigest) || !["approve", "reject"].includes(decision)) throw new ScopedDutyError("invalid_input");
    return decodeScopedDutyProposal(await this.send(`${ROOT}/${caseId}/review`, "POST",
      JSON.stringify({ expected_revision: revision, decision, plan_digest: planDigest }), signal), caseId);
  }
  private caseInput(id: string, revision?: number): void {
    if (!isScopedDutyCaseId(id) || (revision !== undefined && (!Number.isSafeInteger(revision) || revision < 1))) throw new ScopedDutyError("invalid_input");
  }
  private read(path: string, signal?: AbortSignal): Promise<unknown> {
    return this.send(path, "GET", undefined, signal);
  }
  private async send(path: string, method: "GET" | "POST", body: string | undefined, signal: AbortSignal | undefined): Promise<unknown> {
    if (body !== undefined && new TextEncoder().encode(body).length > 32_000) throw new ScopedDutyError("invalid_input");
    const controller = new AbortController();
    let timedOut = false;
    const cancel = () => controller.abort();
    signal?.addEventListener("abort", cancel, { once: true });
    const timer = globalThis.setTimeout(() => { timedOut = true; cancel(); }, this.timeoutMs);
    const aborted = new Promise<never>((_resolve, reject) => {
      controller.signal.addEventListener("abort", () => reject(new ScopedDutyError(timedOut ? "timeout" : "cancelled")), { once: true });
    });
    const perform = async () => {
      if (signal?.aborted) cancel();
      if (controller.signal.aborted) throw new ScopedDutyError("cancelled");
      const url = new URL(path, this.client.operatorApiBaseUrl);
      requireValue(["http:", "https:"].includes(url.protocol) && !url.username && !url.password);
      const authorization = await this.client.authorizationHeader();
      if (controller.signal.aborted) throw new ScopedDutyError("cancelled");
      const headers: Record<string, string> = { accept: "application/json" };
      if (authorization !== null) headers.authorization = authorization;
      if (body !== undefined) headers["content-type"] = "application/json";
      const response = await this.fetcher(url, { method, headers, credentials: "omit", cache: "no-store",
        redirect: "error", referrerPolicy: "no-referrer", signal: controller.signal, ...(body === undefined ? {} : { body }) });
      if (!response.ok) {
        const codes: Readonly<Record<number, ScopedDutyErrorCode>> = { 400: "invalid_input", 401: "unauthorized", 403: "denied", 404: "not_found", 409: "conflict", 413: "invalid_input", 501: "unavailable", 503: "unavailable" };
        throw new ScopedDutyError(codes[response.status] ?? "network");
      }
      requireValue(response.status === (method === "POST" ? 202 : 200));
      const text = await boundedText(response);
      if (controller.signal.aborted) throw new ScopedDutyError("cancelled");
      try { return JSON.parse(text) as unknown; }
      catch { throw new ScopedDutyError("malformed"); }
    };
    try { return await Promise.race([perform(), aborted]); }
    catch (error) {
      if (error instanceof ScopedDutyError) throw error;
      if (typeof error === "object" && error !== null && "status" in error && error.status === 401) throw new ScopedDutyError("unauthorized");
      throw new ScopedDutyError("network");
    } finally {
      globalThis.clearTimeout(timer);
      signal?.removeEventListener("abort", cancel);
    }
  }
}

async function boundedText(response: Response): Promise<string> {
  const reader = response.body?.getReader();
  if (!reader) throw new ScopedDutyError("malformed");
  const decoder = new TextDecoder("utf-8", { fatal: true });
  let size = 0, text = "";
  try {
    for (;;) {
      const next = await reader.read();
      if (next.done) return text + decoder.decode();
      size += next.value.byteLength;
      if (size > MAX_BYTES) { void reader.cancel(); throw new ScopedDutyError("malformed"); }
      text += decoder.decode(next.value, { stream: true });
    }
  } finally { reader.releaseLock(); }
}
