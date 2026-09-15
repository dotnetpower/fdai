/** Ownership-only wire values and local input guards. None of these guards grants authority. */
import { identityForMutationIntent } from "../mutation-intent";
import { PANTHEON } from "./agents.model";

export type ScopedDutyKind = "user" | "group" | "schedule";
export type ScopedDuty = "primary" | "backup" | "escalation";
export type ScopedDutyState = "draft" | "pending_review" | "approved"
  | "ownership_pr_open" | "ownership_merged" | "rejected";

/** Exact normalized declaration identity, not a directory search or role claim. */
export interface ScopedDutySubject {
  readonly kind: ScopedDutyKind;
  readonly ref: string;
}

/** One half-open UTC interval; only schedules may carry a static user fallback. */
export interface ScopedDutyBinding {
  readonly subject: ScopedDutySubject;
  readonly agent_name: string;
  readonly scope_ref: string;
  readonly duty: ScopedDuty;
  readonly effective_from: string;
  readonly effective_until: string;
  readonly fallback: ScopedDutySubject | null;
}

/** Immutable shared request shape, deliberately without IAM or approval fields. */
export interface ScopedDutyRequest {
  readonly schema_version: "1.0.0";
  readonly source_revision: string;
  readonly bindings: readonly ScopedDutyBinding[];
  readonly supersedes_case_id: string | null;
}

/** Original server observation bounds; receipt or refresh time never replaces them. */
export interface ScopedDutyWindow {
  readonly source_revision: string;
  readonly observed_at: string;
  readonly expires_at: string;
  readonly execution_authority: false;
}

/** All allowed scopes from one server catalog revision, not observed resource coverage. */
export interface ScopedDutyCatalog extends ScopedDutyWindow {
  readonly scopes: readonly string[];
  readonly artifact_delivery_available: boolean;
}

/** Exact people and limitations reported by Core for one agent and scope. */
export interface ScopedDutyCoverage {
  readonly agent_name: string;
  readonly scope_ref: string;
  readonly primary_refs: readonly string[];
  readonly backup_refs: readonly string[];
  readonly escalation_refs: readonly string[];
  readonly held_reasons: readonly string[];
}

/** Independent artifact evidence, present only for an observed projection. */
export interface ScopedDutyArtifact {
  readonly case_id: string;
  readonly case_revision: number;
  readonly candidate_digest: string;
  readonly merge_commit_sha: string;
  readonly pr_ref: string;
}

/** Exact read projection; held or incomplete evidence never supplies positive coverage. */
export interface ScopedDutyProjection extends ScopedDutyWindow, ScopedDutyCoverage {
  readonly state: "observed" | "held";
  readonly partial: boolean;
  readonly invalid_cases: number;
  readonly artifact: ScopedDutyArtifact | null;
}

/** Current-only source receipt, not a prediction about the declared effective interval. */
export interface ScopedDutyResolution {
  readonly subject: ScopedDutySubject;
  readonly people: readonly ScopedDutySubject[];
  readonly at: string;
  readonly observed_at: string;
  readonly valid_until: string;
  readonly provenance_ref: string;
  readonly provenance_digest: string;
  readonly complete: boolean;
}

/** Server-retained plan; its original digest, timestamps and limitations stay unchanged. */
export interface ScopedDutyPlan {
  readonly kind: "scoped_duty_review";
  readonly schema_version: "1.0.0";
  readonly source_revision: string;
  readonly input_digest: string;
  readonly digest: string;
  readonly resolution_at: string;
  readonly checked_at: string;
  readonly coverage_basis: "current_observation_only";
  readonly current_coverage: boolean;
  readonly review_required: true;
  readonly execution_authority: false;
  readonly policy: {
    readonly max_resolution_age_microseconds: number;
    readonly read_timeout_seconds: number;
    readonly total_timeout_seconds: number;
  };
  readonly bindings: readonly {
    readonly binding: ScopedDutyBinding;
    readonly scope: { readonly scope_ref: string; readonly source_revision: string } | null;
    readonly resolution: ScopedDutyResolution | null;
    readonly held_reason: string | null;
    readonly schedule_failure: string | null;
    readonly used_fallback: boolean;
    readonly digest: string;
  }[];
  readonly coverage: readonly ScopedDutyCoverage[];
  readonly supersedes_case_id?: string;
}

/** A materialized Core case. Only GET may supply this shape and its next usable revision. */
export interface ScopedDutyCase {
  readonly case_id: string;
  readonly core_case_id: string;
  readonly state: ScopedDutyState;
  readonly revision: number;
  readonly requester_ref: string;
  readonly request: ScopedDutyRequest;
  readonly plan: ScopedDutyPlan;
  readonly reviews: readonly {
    readonly reviewer_ref: string;
    readonly decision: "approve" | "reject";
    readonly plan_digest: string;
    readonly reviewed_at: string;
  }[];
  readonly pr_ref: string | null;
  readonly candidate_digest: string | null;
  readonly merge_commit_sha: string | null;
  readonly execution_authority: false;
}

/** GET can report an unmaterialized creation without inventing Core identity or revision. */
export type ScopedDutyCaseRead = ScopedDutyCase | {
  readonly case_id: string;
  readonly state: "awaiting_core";
  readonly revision: null;
  readonly request: ScopedDutyRequest;
  readonly execution_authority: false;
};

/** Every POST returns only this proposal receipt, even submit and the second approval. */
export interface ScopedDutyProposal {
  readonly case_id: string;
  readonly proposal_id: string;
  readonly accepted_at: string;
  readonly state: "awaiting_core";
  readonly execution_authority: false;
}

/** Route-local draft and immutable serialized retry identity; neither is persisted locally. */
export interface ScopedDutyDraft {
  readonly request: ScopedDutyRequest;
  readonly justification: string;
}
export interface ScopedDutyCreation {
  readonly fingerprint: string;
  readonly idempotencyKey: string;
  readonly body: string;
}

export type ScopedDutyErrorCode = "invalid_input" | "unauthorized" | "denied" | "not_found"
  | "conflict" | "unavailable" | "timeout" | "network" | "malformed" | "cancelled";

/** Content-free failures are translated only by the route's paired dictionary. */
export class ScopedDutyError extends Error {
  constructor(readonly code: ScopedDutyErrorCode) {
    super(`Scoped duty request failed: ${code}`);
    this.name = "ScopedDutyError";
  }
}

export type ScopedDutyIssueCode = "catalog" | "catalog_expired" | "source_revision"
  | "bindings" | "agent" | "scope" | "subject" | "duty" | "utc_time" | "interval"
  | "expired_binding" | "fallback" | "overlap" | "supersedes" | "justification" | "size";
/** An accessible input destination accompanies each local correction. */
export interface ScopedDutyIssue {
  readonly code: ScopedDutyIssueCode;
  readonly field: string;
  readonly binding: number | null;
}

/** Validate an exact ASCII token without silently trimming or rewriting it. */
export function isScopedDutyRef(value: unknown, normalized = false): value is string {
  return typeof value === "string" && /^[!-~]{1,256}$/.test(value)
    && (!normalized || value === value.toLowerCase());
}
/** Operator request IDs are not Core case UUIDs or arbitrary path segments. */
export function isScopedDutyCaseId(value: string): boolean {
  return /^operator-[a-f0-9]{32}$/.test(value);
}
/** Supersession pins one canonical Core UUID, never an Operator alias. */
export function isScopedDutyCoreId(value: string): boolean {
  return /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/.test(value);
}

/** Reject naive times, rollover dates and numeric epochs; retain explicit fractional instants. */
export function scopedDutyInstant(value: string): number {
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,6}))?(Z|[+-]\d{2}:\d{2})$/.exec(value);
  if (!match) return NaN;
  const [year, month, day, hour, minute, second] = match.slice(1, 7).map(Number);
  const date = new Date(0);
  date.setUTCFullYear(year!, month! - 1, day!);
  date.setUTCHours(hour!, minute!, second!, 0);
  if (!year || date.getUTCFullYear() !== year || date.getUTCMonth() !== month! - 1
    || date.getUTCDate() !== day || hour! > 23 || minute! > 59 || second! > 59) return NaN;
  const zone = match[8]!;
  const hours = zone === "Z" ? 0 : Number(zone.slice(1, 3));
  const minutes = zone === "Z" ? 0 : Number(zone.slice(4, 6));
  if (hours > 23 || minutes > 59) return NaN;
  const offset = (zone.startsWith("-") ? -1 : 1) * (hours * 60 + minutes) * 60_000;
  return date.getTime() - offset + Number(`0.${match[7] ?? "0"}`) * 1000;
}

/** Freshness is half-open, at most five minutes, and anchored to the server's original start. */
export function isScopedDutyFresh(window: ScopedDutyWindow | null, now: number): boolean {
  if (!window || window.execution_authority !== false || !Number.isFinite(now)) return false;
  const start = scopedDutyInstant(window.observed_at), end = scopedDutyInstant(window.expires_at);
  return start <= now && now < end && end - start <= 300_000;
}

/** Blank scope and times require deliberate selection; no platform or time defaults are inferred. */
export function newScopedDutyBinding(): ScopedDutyBinding {
  return { subject: { kind: "user", ref: "" }, agent_name: PANTHEON[0]!.name, scope_ref: "",
    duty: "primary", effective_from: "", effective_until: "", fallback: null };
}
/** Begin without a catalog revision or inferred scope and require deliberate input. */
export function emptyScopedDutyDraft(): ScopedDutyDraft {
  return { request: { schema_version: "1.0.0", source_revision: "", bindings: [newScopedDutyBinding()],
    supersedes_case_id: null }, justification: "" };
}

/** Semantic declaration identity allows Z/+00:00 equality without changing retained wire bytes. */
export function scopedDutyBindingIdentity(binding: ScopedDutyBinding): string {
  return JSON.stringify([binding.subject.kind, binding.subject.ref, binding.agent_name,
    binding.scope_ref, binding.duty, scopedDutyInstant(binding.effective_from),
    scopedDutyInstant(binding.effective_until), binding.fallback?.kind, binding.fallback?.ref]);
}

/** Structural shared-request checks only; directory resolution and coverage remain server-owned. */
export function scopedDutyRequestIssues(request: ScopedDutyRequest): readonly ScopedDutyIssue[] {
  const issues: ScopedDutyIssue[] = [];
  const add = (code: ScopedDutyIssueCode, field: string, binding: number | null = null) =>
    issues.push({ code, field, binding });
  if (request.schema_version !== "1.0.0" || !isScopedDutyRef(request.source_revision)) add("source_revision", "source_revision");
  if (request.bindings.length < 1 || request.bindings.length > 30) add("bindings", "bindings");
  if (request.supersedes_case_id !== null && !isScopedDutyCoreId(request.supersedes_case_id)) add("supersedes", "supersedes");
  request.bindings.forEach((row, index) => {
    if (!PANTHEON.some((agent) => agent.name === row.agent_name)) add("agent", "agent_name", index);
    if (!isScopedDutyRef(row.scope_ref)) add("scope", "scope_ref", index);
    if (!["user", "group", "schedule"].includes(row.subject.kind) || !isScopedDutyRef(row.subject.ref, true)) add("subject", "subject_ref", index);
    if (!["primary", "backup", "escalation"].includes(row.duty)) add("duty", "duty", index);
    const start = scopedDutyInstant(row.effective_from), end = scopedDutyInstant(row.effective_until);
    for (const field of ["effective_from", "effective_until"] as const) {
      if (!Number.isFinite(scopedDutyInstant(row[field])) || !/(?:Z|\+00:00)$/.test(row[field])) add("utc_time", field, index);
    }
    if (Number.isFinite(start) && Number.isFinite(end) && start >= end) add("interval", "effective_until", index);
    if (row.subject.kind === "schedule"
      ? row.fallback?.kind !== "user" || !isScopedDutyRef(row.fallback.ref, true) || row.fallback.ref === row.subject.ref
      : row.fallback !== null) add("fallback", "fallback", index);
    if (request.bindings.slice(0, index).some((prior) => prior.agent_name === row.agent_name
      && prior.scope_ref === row.scope_ref && prior.subject.kind === row.subject.kind
      && prior.subject.ref === row.subject.ref && start < scopedDutyInstant(prior.effective_until)
      && scopedDutyInstant(prior.effective_from) < end)) add("overlap", "effective_from", index);
  });
  return issues;
}

/** Add current catalog, body-size and user-facing creation limits without proving coverage. */
export function scopedDutyDraftIssues(draft: ScopedDutyDraft, catalog: ScopedDutyCatalog | null, now: number): readonly ScopedDutyIssue[] {
  const issues = [...scopedDutyRequestIssues(draft.request)];
  const add = (code: ScopedDutyIssueCode, field: string, binding: number | null = null) => issues.push({ code, field, binding });
  if (!catalog) add("catalog", "catalog");
  else {
    if (!isScopedDutyFresh(catalog, now)) add("catalog_expired", "catalog");
    if (draft.request.source_revision !== catalog.source_revision) add("source_revision", "source_revision");
    draft.request.bindings.forEach((row, index) => {
      if (!catalog.scopes.includes(row.scope_ref)) add("scope", "scope_ref", index);
    });
  }
  draft.request.bindings.forEach((row, index) => {
    if (scopedDutyInstant(row.effective_until) <= now) add("expired_binding", "effective_until", index);
  });
  const length = [...draft.justification.trim()].length;
  if (length < 20 || length > 2000) add("justification", "justification");
  if (new TextEncoder().encode(JSON.stringify({ idempotency_key: "x".repeat(160), ...draft })).length > 32_000) add("size", "bindings");
  return issues;
}

/** Retry the same serialized body after uncertainty. Any draft edit, including reverting, can rotate its key. */
export function scopedDutyCreationFor(previous: ScopedDutyCreation | null, draft: ScopedDutyDraft, createKey: () => string = () => crypto.randomUUID()): ScopedDutyCreation {
  const identity = identityForMutationIntent(previous, JSON.stringify(draft), createKey);
  if (previous?.fingerprint === identity.fingerprint) return previous;
  if (!isScopedDutyRef(identity.idempotencyKey) || identity.idempotencyKey.length > 160) throw new ScopedDutyError("invalid_input");
  return { ...identity, body: JSON.stringify({ idempotency_key: identity.idempotencyKey,
    request: draft.request, justification: draft.justification.trim() }) };
}

export type ScopedDutyControlReason = "owner" | "identity" | "awaiting_core" | "catalog"
  | "source_revision" | "requester" | "future" | "separation" | "already_reviewed" | "target" | "terminal";

/** UI eligibility only. The server repeats current Owner, predecessor, coverage and revision checks. */
export function scopedDutyControls(current: ScopedDutyCaseRead | null, catalog: ScopedDutyCatalog | null,
  principalOid: string, canManage: boolean, now: number,
): { readonly submit: boolean; readonly review: boolean; readonly reason: ScopedDutyControlReason | null } {
  const blocked = (reason: ScopedDutyControlReason) => ({ submit: false, review: false, reason });
  if (!canManage) return blocked("owner");
  if (!isScopedDutyRef(principalOid)) return blocked("identity");
  if (!current || current.state === "awaiting_core") return blocked("awaiting_core");
  if (!isScopedDutyFresh(catalog, now)) return blocked("catalog");
  if (catalog!.source_revision !== current.request.source_revision
    || current.request.bindings.some((row) => !catalog!.scopes.includes(row.scope_ref))) return blocked("source_revision");
  const actor = principalOid.toLowerCase();
  if (current.state === "draft") {
    if (actor !== current.requester_ref) return blocked("requester");
    if (!current.request.bindings.some((row) => scopedDutyInstant(row.effective_from) <= now && now < scopedDutyInstant(row.effective_until))) return blocked("future");
    return { submit: true, review: false, reason: null };
  }
  if (current.state !== "pending_review") return blocked("terminal");
  if (!current.request.bindings.some((row) => scopedDutyInstant(row.effective_from) <= now
    && now < scopedDutyInstant(row.effective_until))) return blocked("future");
  if (actor === current.requester_ref) return blocked("separation");
  if (current.reviews.some((row) => row.reviewer_ref === actor)) return blocked("already_reviewed");
  if (current.request.bindings.some((row) => (row.subject.kind === "user" && row.subject.ref === actor) || row.fallback?.ref === actor)
    || current.plan.bindings.some((row) => row.resolution?.people.some((person) => person.ref === actor))) return blocked("target");
  return { submit: false, review: true, reason: null };
}
